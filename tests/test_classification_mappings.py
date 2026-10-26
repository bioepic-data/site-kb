"""Source classification crosswalks: application, provenance, override precedence, coverage."""
from pathlib import Path

import pytest
import yaml

from site_kb.scripts.build_db import assemble
from site_kb.scripts.classification_mappings import apply_classification_mappings, read_classification_mappings

ROOT = Path(__file__).parents[1]
URL = "https://example.org/field-sites.csv"


def mapping(value, slot, identifier, label, relation="CLOSE"):
    return {"source": "NEON", "scheme": "site_subtype", "value": value, "target_slot": slot,
            "target": {"id": identifier, "label": label}, "relation": relation, "origin": "CURATED",
            "evidence": ["https://example.org/review"]}


def site(*values, **extra):
    return {"id": "site_kb:neon-test", "name": "Test", **extra,
            "source_classifications": [{"source": "NEON", "scheme": "site_subtype", "value": v,
                                        "record_url": URL, "field_path": "/0/site_subtype"} for v in values]}


def test_mapped_terms_carry_field_level_evidence():
    sites = {"s": site("Lake")}
    apply_classification_mappings(sites, [mapping("Lake", "SITE_TYPE", "ENVO:00000020", "lake"),
                                          mapping("Lake", "ECOSYSTEM", "ENVO:01000252", "freshwater lake biome", "RELATED")])
    result = sites["s"]
    assert result["site_type"] == {"id": "ENVO:00000020", "label": "lake"}
    assert result["ecosystem_terms"] == [{"id": "ENVO:01000252", "label": "freshwater lake biome"}]
    assert [e["supports"] for e in result["evidence"]] == [["/site_type"], ["/ecosystem_terms/0"]]
    assert result["evidence"][1]["source_url"] == URL and "RELATED" in result["evidence"][1]["notes"]
    assert "land_cover_terms" not in result


def test_unmapped_values_and_existing_site_types_are_left_alone():
    curated_type = {"id": "ENVO:00002043", "label": "wastewater treatment plant"}
    sites = {"s": site("Lake", "Unknown", site_type=curated_type)}
    apply_classification_mappings(sites, [mapping("Lake", "SITE_TYPE", "ENVO:00000020", "lake")])
    assert sites["s"]["site_type"] == curated_type and "evidence" not in sites["s"]


def test_conflicting_site_type_crosswalks_are_rejected():
    sites = {"s": site("Lake", "Wadeable Stream")}
    with pytest.raises(ValueError, match="conflicting site_type"):
        apply_classification_mappings(sites, [mapping("Lake", "SITE_TYPE", "ENVO:00000020", "lake"),
                                              mapping("Wadeable Stream", "SITE_TYPE", "ENVO:00000023", "stream")])


def test_duplicate_or_malformed_mapping_files_are_rejected(tmp_path):
    (tmp_path / "a.yaml").write_text(yaml.safe_dump({"mappings": [mapping("Lake", "SITE_TYPE", "ENVO:00000020", "lake")] * 2}))
    with pytest.raises(ValueError, match="duplicate"):
        read_classification_mappings(tmp_path)
    (tmp_path / "a.yaml").write_text(yaml.safe_dump({"mappings": [mapping("Lake", "HABITAT", "ENVO:00000020", "lake")]}))
    with pytest.raises(ValueError, match="target_slot"):
        read_classification_mappings(tmp_path)


def test_overrides_replace_crosswalk_lists(tmp_path):
    imported, curated = tmp_path / "imported", tmp_path / "curated"
    for directory in (imported, curated / "sites", curated / "overrides", curated / "classification_mappings"):
        directory.mkdir(parents=True)
    (imported / "s.yaml").write_text(yaml.safe_dump({"sites": [site("Lake")]}))
    (curated / "classification_mappings" / "m.yaml").write_text(yaml.safe_dump(
        {"mappings": [mapping("Lake", "ECOSYSTEM", "ENVO:01000252", "freshwater lake biome", "RELATED")]}))
    (curated / "overrides" / "o.yaml").write_text(yaml.safe_dump(
        {"sites": [{"id": "site_kb:neon-test", "ecosystem_terms": [{"id": "ENVO:01001789", "label": "freshwater ecosystem"}]}]}))
    [result] = assemble(imported, curated)["sites"]
    assert result["ecosystem_terms"] == [{"id": "ENVO:01001789", "label": "freshwater ecosystem"}]


def test_curated_neon_crosswalk_covers_every_imported_value():
    mapped = {(m["source"], m["scheme"], m["value"])
              for m in read_classification_mappings(ROOT / "db/curated/classification_mappings")}
    values = set()
    for path in (ROOT / "db/imported/neon").glob("*.yaml"):
        for record in yaml.safe_load(path.read_text())["sites"]:
            values |= {(c["source"], c["scheme"], c["value"]) for c in record.get("source_classifications", [])}
    # Aquatic design classes carry no ecosystem beyond their subtype-specific crosswalks.
    intentionally_unmapped = {("NEON", "site_type", "Core Aquatic"), ("NEON", "site_type", "Gradient Aquatic")}
    assert values and values - mapped == intentionally_unmapped


def test_neon_bervo_crosswalks_target_imported_products():
    data = yaml.safe_load((ROOT / "db/curated/variable_mappings/neon_bervo.yaml").read_text())
    products = set()
    for path in (ROOT / "db/imported/neon").glob("*.yaml"):
        for record in yaml.safe_load(path.read_text())["sites"]:
            products |= {v["data_product"] for v in record.get("variables", [])}
    assert {m["source_id"] for m in data["mappings"]} <= products
    assert all(m["source"] == "NEON" and m["relation"] != "EXACT" for m in data["mappings"])
