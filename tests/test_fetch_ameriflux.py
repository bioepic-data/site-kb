"""AmeriFlux source fidelity, fail-before-write behavior, and offline refresh."""
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner
import yaml

from site_kb.scripts import fetch_ameriflux as amf


def record(code="US-Ha1", **extra):
    return {"SITE_ID": code, "SITE_NAME": "Original source name", "COUNTRY": "USA",
            "STATE": "MA", "GRP_LOCATION": {"LOCATION_LAT": "42.5", "LOCATION_LONG": "-72.1", "LOCATION_ELEV": "0"},
            "IGBP": "DBF", "GRP_CLIM_AVG": {"MAT": "-12.6", "MAP": "0", "CLIMATE_KOEPPEN": "Dfb"},
            "TOWER_BEGAN": "1991", **extra}


def snapshot(*records):
    return {"source_url": amf.API_URL, "retrieved_at": "2026-10-15T00:00:00+00:00",
            "response_sha256": amf.checksum(list(records)), "records": list(records)}


def test_source_metadata_does_not_invent_observations_facility_or_status():
    site = amf.ameriflux_to_site(record())
    assert site["id"] == "site_kb:ameriflux-us-ha1"
    assert site["network_registrations"][0]["network_id"] == "US-Ha1"
    assert site["location"]["country"] == "United States"
    assert site["location"]["elevation_meters"] == 0
    assert "-12.6" in site["notes"] and "1991" in site["notes"]
    assert not set(site) & {"variables", "site_type", "ecosystem_terms", "status", "established", "closed"}


def test_signs_and_zero_values_are_preserved():
    source = record("BR-Npw", COUNTRY="Brazil", GRP_LOCATION={
        "LOCATION_LAT": "-16.4980", "LOCATION_LONG": "-56.4120", "LOCATION_ELEV": "-4"})
    loc = amf.ameriflux_to_site(source)["location"]
    assert (loc["latitude"], loc["longitude"], loc["elevation_meters"]) == (-16.498, -56.412, -4)
    source["GRP_LOCATION"] = {"LOCATION_LAT": "0", "LOCATION_LONG": "0"}
    assert amf.ameriflux_to_site(source)["location"]["latitude"] == 0


def test_missing_location_keeps_verified_country_without_coordinates():
    site = amf.ameriflux_to_site(record(GRP_LOCATION=None, STATE=None, GRP_CLIM_AVG=None))
    assert site["location"] == {"country": "United States"}


@pytest.mark.parametrize("key,value", [("LOCATION_LAT", "91"), ("LOCATION_LONG", "-181"),
                                      ("LOCATION_LAT", "NaN"), ("LOCATION_ELEV", "Infinity"),
                                      ("LOCATION_ELEV", "-9999"), ("LOCATION_LAT", True)])
def test_invalid_coordinates_are_rejected(key, value):
    source = record()
    source["GRP_LOCATION"][key] = value
    with pytest.raises(ValueError):
        amf.ameriflux_to_site(source)


@pytest.mark.parametrize("payload", [{"error": "unavailable"}, [], [record(), record()],
                                   [record("US-HA1"), record("US-Ha1")],
                                   [record("../bad")], [record(SITE_NAME="")]])
def test_error_payloads_and_duplicate_identities_rejected(payload):
    with pytest.raises(ValueError):
        amf.validate_records(payload)


def test_http_200_error_object_is_rejected(monkeypatch):
    monkeypatch.setattr(amf.httpx, "get", lambda *a, **kw: httpx.Response(
        200, json={"error": "broken"}, request=httpx.Request("GET", amf.API_URL)))
    with pytest.raises(ValueError):
        amf.fetch_snapshot()


def test_batch_failure_does_not_touch_existing_files(tmp_path):
    output, raw = tmp_path / "imported", tmp_path / "raw"
    good = snapshot(record())
    amf.ingest(good, output, raw)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    bad = record("US-Zzz", GRP_LOCATION={"LOCATION_LAT": "bad"})
    with pytest.raises(ValueError):
        amf.ingest(snapshot(record(SITE_NAME="Changed"), bad), output, raw)
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_refresh_replay_provenance_and_no_pruning(tmp_path, monkeypatch):
    output, raw = tmp_path / "imported", tmp_path / "raw"
    first = snapshot(record(), record("US-Ne1"))
    amf.ingest(first, output, raw)
    path = output / "ameriflux_us-ha1.yaml"
    data = yaml.safe_load(path.read_text())
    data["sites"][0]["id"] = "site_kb:stable-local-id"
    custom = output / "existing.yaml"
    custom.write_text(yaml.safe_dump(data))
    path.unlink()
    updated = snapshot(record(SITE_NAME="New upstream name", EXTRA={"unmodeled": [1, 2]}))
    saved = tmp_path / "snapshot.json"
    saved.write_text(json.dumps(updated))
    monkeypatch.setattr(amf, "fetch_snapshot", lambda: pytest.fail("Offline replay attempted HTTP"))
    result = CliRunner().invoke(amf.app, ["--from-snapshot", str(saved), "--refresh-existing",
        "--output-dir", str(output), "--raw-dir", str(raw), "--comparison-dir", str(tmp_path / "none")])
    assert result.exit_code == 0, result.output
    site = yaml.safe_load(custom.read_text())["sites"][0]
    assert site["id"] == "site_kb:stable-local-id" and site["name"] == "New upstream name"
    assert (output / "ameriflux_us-ne1.yaml").exists()
    source = json.loads((raw / "US-Ha1.json").read_text())
    assert source["record"] == updated["records"][0]
    assert source["retrieved_at"] == updated["retrieved_at"]
    assert source["field_path"] == "/0"
    assert source["response_sha256"] == updated["response_sha256"]
    assert "us-ne1" in result.output
    before = custom.read_bytes()
    amf.ingest(updated, output, raw, refresh_existing=True)
    assert custom.read_bytes() == before


def test_selection_summary_and_checksum(tmp_path):
    source = snapshot(record("US-Ne1"), record())
    output, raw = tmp_path / "imported", tmp_path / "raw"
    report = amf.ingest(source, output, raw, limit=1, summary_only=True)
    assert report["selected"] == ["US-Ha1"]
    assert not output.exists() and not raw.exists()
    with pytest.raises(ValueError, match="Unknown"):
        amf.ingest(source, output, raw, site_ids=["US-ha1"])
    corrupt = deepcopy(source)
    corrupt["records"][0]["SITE_NAME"] = "Tampered"
    with pytest.raises(ValueError, match="checksum"):
        amf.ingest(corrupt, output, raw)
    amf.ingest(source, output, raw, site_ids=["US-Ne1"])
    assert [p.name for p in output.glob("*.yaml")] == ["ameriflux_us-ne1.yaml"]


def test_existing_filename_collision_is_rejected(tmp_path):
    output, raw = tmp_path / "imported", tmp_path / "raw"
    amf.ingest(snapshot(record()), output, raw)
    (output / "ameriflux_us-ha1.yaml").rename(output / "ameriflux_us-ne1.yaml")
    with pytest.raises(ValueError, match="collides"):
        amf.ingest(snapshot(record(), record("US-Ne1")), output, raw)


def test_neon_overlap_is_reported_without_adding_registration(tmp_path):
    other = {"id": "site_kb:neon-abby", "name": "Abby Road", "location": {"latitude": 45.762439, "longitude": -122.330317},
             "network_registrations": [{"network": "NEON", "network_id": "ABBY"}]}
    tmp_path.joinpath("neon.yaml").write_text(yaml.safe_dump({"sites": [other]}))
    source = record("US-xAB", SITE_NAME="NEON Abby Road (ABBY)", GRP_LOCATION={"LOCATION_LAT": "45.7624", "LOCATION_LONG": "-122.3303"})
    site = amf.ameriflux_to_site(source)
    overlaps = amf.overlap_candidates([site], tmp_path)
    assert len(overlaps) == 1 and len(overlaps[0]["reasons"]) == 2
    assert overlaps[0]["resolution"] == "UNREVIEWED"
    assert len(site["network_registrations"]) == 1
