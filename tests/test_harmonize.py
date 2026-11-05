"""Same-site merging, relation inference, geo consistency, and curated NEON seed drift."""
import gzip
import json
from pathlib import Path

import pytest
import yaml

from site_kb.scripts.build_db import read_records
from site_kb.scripts.harmonize import containment, harmonize, merge, read_harmonization
from site_kb.scripts.propose_site_links import outstanding, propose, slugify

ROOT = Path(__file__).parents[1]
EVIDENCE = ["https://example.org/link"]
BOX = {"west": -72.2, "south": 42.5, "east": -72.1, "north": 42.6}


def record(identifier, name, lat=42.53, lon=-72.17, **extra):
    return {"id": identifier, "name": name, "location": {"latitude": lat, "longitude": lon}, **extra}


def neon():
    return record("site_kb:neon-harv", "Harvard Forest NEON", status="ACTIVE",
                  network_registrations=[{"network": "NEON", "network_id": "HARV"},
                                         {"network": "DEIMS", "network_id": "uuid"}],
                  land_cover_terms=[{"id": "ENVO:01000816", "label": "area of deciduous forest"}],
                  variables=[{"name": "Air temperature"}],
                  evidence=[{"supports": ["/land_cover_terms/0", "/location/latitude"], "source_url": "https://neon",
                             "source_label": "NEON", "locator": "row"}])


def deims():
    return record("site_kb:deims-harvard", "Harvard Forest NEON - USA", lat=42.5369, lon=-72.1727,
                  description="DEIMS abstract", notes="Biogeographical region: none",
                  network_registrations=[{"network": "DEIMS", "network_id": "uuid", "name": "DEIMS title"}],
                  land_cover_terms=[{"id": "ENVO:01000843", "label": "area of evergreen forest"},
                                    {"id": "ENVO:01000816", "label": "area of deciduous forest"}],
                  variables=[{"name": "snow depth"}],
                  evidence=[{"supports": ["/land_cover_terms/1", "/location/latitude", "/description"],
                             "source_url": "https://deims", "source_label": "DEIMS", "locator": "geo"}])


def cluster(*members, **extra):
    return {"id": "site_kb:harvard-forest", "name": "Harvard Forest",
            "members": [{"record": m, "origin": "SOURCE", "evidence": EVIDENCE} for m in members], **extra}


def test_merge_follows_member_precedence_and_remaps_evidence():
    first, second = neon(), deims()
    second["location"]["bounding_box"] = BOX
    site = merge(cluster(first["id"], second["id"]), [first, second])
    assert site["location"] == {"latitude": 42.53, "longitude": -72.17, "bounding_box": BOX}
    assert site["description"] == "DEIMS abstract" and site["status"] == "ACTIVE"
    assert site["aliases"] == ["Harvard Forest NEON", "Harvard Forest NEON - USA"]
    assert site["network_registrations"] == [{"network": "NEON", "network_id": "HARV"},
                                             {"network": "DEIMS", "network_id": "uuid", "name": "DEIMS title"}]
    assert [t["id"] for t in site["land_cover_terms"]] == ["ENVO:01000816", "ENVO:01000843"]
    assert [(v["name"], v["source_record"]) for v in site["variables"]] == [
        ("Air temperature", "site_kb:neon-harv"), ("snow depth", "site_kb:deims-harvard")]
    assert site["notes"] == "site_kb:deims-harvard: Biogeographical region: none"
    # DEIMS latitude evidence is dropped: NEON supplied the coordinates.
    assert [e["supports"] for e in site["evidence"]] == [["/land_cover_terms/0", "/location/latitude"],
                                                         ["/land_cover_terms/0", "/description"]]
    assert [m["name"] for m in site["members"]] == ["Harvard Forest NEON", "Harvard Forest NEON - USA"]


def test_field_sources_override_precedence_and_site_type_conflicts_need_one():
    first, second = neon(), deims()
    first["site_type"] = {"id": "ENVO:00000023", "label": "stream"}
    second["site_type"] = {"id": "ENVO:00000020", "label": "lake"}
    with pytest.raises(ValueError, match="site_type"):
        merge(cluster(first["id"], second["id"]), [first, second])
    chosen = cluster(first["id"], second["id"], field_sources=[{"field": "site_type", "record": second["id"]},
                                                               {"field": "location", "record": second["id"]}])
    site = merge(chosen, [first, second])
    assert site["site_type"]["label"] == "lake" and site["location"]["latitude"] == 42.5369


def test_unknown_fields_must_get_an_explicit_merge_rule():
    first = neon()
    first["established"] = "2014-01-01"
    first["future_field"] = 1
    with pytest.raises(ValueError, match="no merge rule"):
        merge(cluster(first["id"], "site_kb:deims-harvard"), [first, deims()])


@pytest.mark.parametrize("change, message", [
    (lambda c, r: c.update(id="site_kb:neon-harv"), "collides"),
    (lambda c, r: c["members"].append({"record": "site_kb:missing", "origin": "SOURCE", "evidence": EVIDENCE}), "unknown member"),
])
def test_cluster_identity_errors(change, message):
    records = {r["id"]: r for r in (neon(), deims())}
    c = cluster(*records)
    change(c, records)
    with pytest.raises(ValueError, match=message):
        harmonize(records, [c], [])


def test_record_cannot_belong_to_two_clusters():
    records = {r["id"]: r for r in (neon(), deims(), record("site_kb:other", "Other"))}
    second = {**cluster("site_kb:neon-harv", "site_kb:other"), "id": "site_kb:other-cluster"}
    with pytest.raises(ValueError, match="member of both"):
        harmonize(records, [cluster("site_kb:neon-harv", "site_kb:deims-harvard"), second], [])


def test_member_locations_must_agree_unless_waived():
    far = deims()
    far["location"] = {"latitude": 31.85, "longitude": -88.16}
    records = {r["id"]: r for r in (neon(), far)}
    with pytest.raises(ValueError, match="member locations disagree"):
        harmonize(records, [cluster(*records)], [])
    sites, source_records = harmonize(records, [cluster(*records, geo_check_waiver="DEIMS copy error")], [])
    assert set(sites) == {"site_kb:harvard-forest"} and len(source_records) == 2


def relation(subject, obj, predicate="PART_OF", **extra):
    return {"subject": subject, "predicate": predicate, "object": obj, "origin": "CURATED", "evidence": EVIDENCE, **extra}


def towered(lat, lon, box=BOX):
    whole = deims()
    whole["location"]["bounding_box"] = box
    tower = record("site_kb:ameriflux-us-xha", "Tower", lat=lat, lon=lon)
    return {r["id"]: r for r in (neon(), whole, tower)}


def test_part_of_is_checked_against_the_merged_box_and_inverse_is_inferred():
    records = towered(42.54, -72.17)
    # Subject and object may be given as member record IDs.
    sites, _ = harmonize(records, [cluster("site_kb:neon-harv", "site_kb:deims-harvard")],
                         [relation("site_kb:ameriflux-us-xha", "site_kb:neon-harv")])
    [part] = sites["site_kb:ameriflux-us-xha"]["relations"]
    [whole] = sites["site_kb:harvard-forest"]["relations"]
    assert (part["predicate"], part["object"], part["geo_check"]) == ("PART_OF", "site_kb:harvard-forest", "CONSISTENT")
    assert (whole["predicate"], whole["object"], whole["inferred"]) == ("HAS_PART", "site_kb:ameriflux-us-xha", True)
    assert whole["object_name"] == "Tower"


def test_containment_violation_requires_waiver_and_stale_waivers_fail():
    records = towered(39.06, -78.07)
    c = [cluster("site_kb:neon-harv", "site_kb:deims-harvard")]
    with pytest.raises(ValueError, match="outside"):
        harmonize(towered(39.06, -78.07), c, [relation("site_kb:ameriflux-us-xha", "site_kb:harvard-forest")])
    sites, _ = harmonize(records, c, [relation("site_kb:ameriflux-us-xha", "site_kb:harvard-forest", geo_check_waiver="Box is partial")])
    assert sites["site_kb:ameriflux-us-xha"]["relations"][0]["geo_check"] == "WAIVED"
    with pytest.raises(ValueError, match="stale"):
        harmonize(towered(42.54, -72.17), c, [relation("site_kb:ameriflux-us-xha", "site_kb:harvard-forest", geo_check_waiver="x")])


def test_containment_statuses():
    assert containment(record("a", "A"), record("b", "B")) == "UNCHECKABLE"
    whole = record("b", "B")
    whole["location"]["bounding_box"] = BOX
    assert containment({"id": "a", "name": "A"}, whole) == "UNCHECKABLE"
    part = record("a", "A")
    part["location"]["bounding_box"] = {**BOX, "east": -71.0}
    assert containment(part, whole) == "VIOLATION"


def test_symmetric_duplicates_self_links_and_cycles_are_rejected():
    records = {r["id"]: r for r in (record("site_kb:a", "A"), record("site_kb:b", "B"), record("site_kb:c", "C"))}
    for relations, message in [
        ([relation("site_kb:a", "site_kb:b", "COLOCATED_WITH"), relation("site_kb:b", "site_kb:a", "COLOCATED_WITH")], "Duplicate"),
        ([relation("site_kb:a", "site_kb:a", "OVERLAPS")], "itself"),
        ([relation("site_kb:a", "site_kb:b"), relation("site_kb:b", "site_kb:c"), relation("site_kb:c", "site_kb:a")], "cycle"),
        ([relation("site_kb:a", "site_kb:missing")], "unknown"),
    ]:
        with pytest.raises(ValueError, match=message):
            harmonize({k: dict(v) for k, v in records.items()}, [], relations)


def test_harmonization_files_reject_curated_inverses(tmp_path):
    (tmp_path / "h.yaml").write_text(yaml.safe_dump({"relations": [relation("site_kb:a", "site_kb:b", "HAS_PART")]}))
    with pytest.raises(ValueError, match="PART_OF"):
        read_harmonization(tmp_path)


def test_slugs_are_ascii():
    assert slugify("Utqiaġvik NEON") == "site_kb:utqiagvik-neon"
    assert slugify("Harvard Forest & Quabbin Watershed NEON") == "site_kb:harvard-forest-quabbin-watershed-neon"


def test_curated_neon_links_match_current_sources():
    """Every source-asserted link is curated, and curated SOURCE links are still asserted."""
    records = read_records(ROOT / "db/imported") | read_records(ROOT / "db/curated/sites")
    snapshot = json.loads(gzip.decompress((ROOT / "db/raw/neon/field-sites.json.gz").read_bytes()))
    proposals = propose(records, snapshot)
    curated = read_harmonization(ROOT / "db/curated/harmonization")
    assert outstanding(proposals, curated) == {"clusters": [], "relations": []}
    proposed_members = {(c["id"], m["record"]) for c in proposals["clusters"] for m in c["members"]}
    proposed_pairs = {(r["subject"], r["predicate"], r["object"]) for r in proposals["relations"]}
    for c in curated[0]:
        for member in c["members"]:
            if member["origin"] == "SOURCE":
                assert (c["id"], member["record"]) in proposed_members
    for r in curated[1]:
        if r["origin"] == "SOURCE":
            assert (r["subject"], r["predicate"], r["object"]) in proposed_pairs


def test_every_site_point_must_lie_in_its_own_box():
    stray = record("site_kb:stray", "Stray", lat=46.49, lon=13.59)
    stray["location"]["bounding_box"] = {"west": 11.43, "south": 46.27, "east": 11.77, "north": 46.59}
    with pytest.raises(ValueError, match="outside its own bounding_box"):
        harmonize({stray["id"]: stray}, [], [])
