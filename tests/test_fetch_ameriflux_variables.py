"""Site evidence, product semantics, coverage, refresh, and replay regression tests."""
import json

import httpx
import pytest
import yaml

from site_kb.scripts import fetch_ameriflux as meta
from site_kb.scripts import fetch_ameriflux_variables as amf
from site_kb.scripts.render_site import detail, render


WHEN = "2026-10-15T00:00:00+00:00"


def snapshot(record, url):
    return {"source_url": url, "retrieved_at": WHEN, "record": record, "sha256": meta.checksum(record)}


def definitions():
    return snapshot({"values": [
        {"name": "CO2", "type": "GASES", "description": "Carbon dioxide concentration", "units": "µmolCO2 mol-1"},
        {"name": "TA", "type": "MET_ATM", "description": "Air temperature", "units": "deg C"},
        {"name": "GPP", "type": "PRODUCTS", "description": "Gross Primary Productivity", "units": "µmolCO2 m-2 s-1"},
        {"name": "FC_SSITC_TEST", "type": "QC_FLAG", "description": "Quality flag", "units": "nondimensional"},
    ]}, amf.DEFINITIONS_URL)


def record(**kwargs):
    return {"site_id": "US-Ha1", "flux_measurements_variables": ["CO2", "CO2", "Other"],
            "base_variables": ["CO2", "TA", "GPP", "FC_SSITC_TEST"], **kwargs}


def site_snapshot(source=None):
    result = snapshot(source or record(), amf.SITE_URL)
    result["field_path"] = "/values/0"
    return result


def row(variable="TA", **kwargs):
    return {"variable": variable, "version": "1-5", "resolution": "HH", "qualifiers": "1_1_1",
            "year": 2024, "coverage_percent": 50.0, **kwargs}


def coverage(*rows):
    return snapshot({"site_id": "US-Ha1", "data_product": "BASE", "records": list(rows)}, amf.COVERAGE_URL + "US-Ha1")


def test_reported_flux_and_concentration_have_separate_source_identities():
    variables, note, counts = amf.convert_variables(site_snapshot(), amf.definition_index(definitions()),
                                                   coverage(row("CO2"), row(), row("GPP"), row("FC_SSITC_TEST")))
    co2 = [v for v in variables if v["source_variables"][0]["source_id"] == "CO2"]
    assert len(co2) == 2
    assert {v["source_variables"][0]["source"] for v in co2} == {"AMERIFLUX_BADM_SGI", "AMERIFLUX_BASE"}
    reported = next(v for v in co2 if v["data_product"] == "BADM Site General Information")
    assert reported["declaration_kind"] == "UNSPECIFIED" and "reported_units" not in reported
    assert reported["source_variables"][0]["source_name"] == "CO2"
    assert counts["excluded_diagnostics"] == 1
    assert not any(v["source_variables"][0]["source_id"] == "FC_SSITC_TEST" for v in variables)
    assert "not concentration" in note
    assert not any(set(v) & {"term", "mappings", "units"} for v in variables)


def test_positive_coverage_gap_filling_qualifiers_and_years():
    cov = coverage(row(coverage_percent=0), row(year=2025, qualifiers="PI_F_1_1_1"),
                   row(year=2023, qualifiers="2_1_1", resolution="HR", version="2-5"),
                   row("CO2", coverage_percent=0), row("GPP"))
    variables, _, counts = amf.convert_variables(site_snapshot(), amf.definition_index(definitions()), cov)
    ta = [v for v in variables if v["source_variables"][0]["source_id"] == "TA"]
    assert len(ta) == 2
    filled = next(v for v in ta if v["gap_filled"])
    unfilled = next(v for v in ta if not v["gap_filled"])
    assert filled["available_years"] == [2025]
    assert filled["source_qualifiers"] == ["PI_F_1_1_1"]
    assert unfilled["available_years"] == [2023]
    assert unfilled["temporal_resolution"] == "hourly" and unfilled["data_versions"] == ["2-5"]
    assert filled["source_variables"][0]["field_path"] == "/records/1/variable"
    assert counts["zero_coverage_variables"] == 1
    gpp = next(v for v in variables if v.get("source_category") == "PRODUCTS")
    assert "Derived" in gpp["description"]


def test_missing_coverage_does_not_invent_gap_flags_or_per_variable_years():
    variables, note, _ = amf.convert_variables(site_snapshot(), amf.definition_index(definitions()), None)
    base = [v for v in variables if v["data_product"] == "AmeriFlux BASE"]
    assert len(base) == 3
    assert all("gap_filled" not in v and "available_years" not in v for v in base)
    assert "unavailable" in note
    variables, note, _ = amf.convert_variables(site_snapshot(record(base_variables=[])), {}, None)
    assert len(variables) == 2 and all(v["data_product"] == "BADM Site General Information" for v in variables)
    assert "No published BASE" in note


@pytest.mark.parametrize("change", [{"coverage_percent": -1}, {"coverage_percent": 101}, {"coverage_percent": float('nan')},
                                    {"year": "2024"}, {"resolution": "DAILY"}, {"qualifiers": []}])
def test_invalid_coverage_rejected(change):
    # NaN cannot enter a canonical snapshot in the first place.
    with pytest.raises(ValueError):
        amf.coverage_groups(coverage(row(**change)), "US-Ha1")


def test_duplicate_or_mismatched_coverage_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        amf.coverage_groups(coverage(row(), row()), "US-Ha1")
    with pytest.raises(ValueError, match="source or checksum"):
        amf.coverage_groups(coverage(row()), "US-Ne1")
    with pytest.raises(ValueError, match="Unknown FP"):
        amf.convert_variables(site_snapshot(record(base_variables=["UNKNOWN"])), amf.definition_index(definitions()), None)


def prepare_cache(cache):
    cache.mkdir()
    sites = snapshot({"values": [record()]}, amf.SITE_URL)
    (cache / "sites.json").write_text(json.dumps(sites))
    (cache / "definitions.json").write_text(json.dumps(definitions()))
    (cache / "fetch-report.json").write_text(json.dumps({"site_sha256": sites["sha256"], "coverage_failures": {}}))
    amf.write_compressed(cache / "coverage/US-Ha1.json.gz", coverage(row(), row("CO2"), row("GPP")))


def metadata():
    records = [{"SITE_ID": "US-Ha1", "SITE_NAME": "Harvard Forest"}]
    return {"source_url": meta.API_URL, "retrieved_at": WHEN, "response_sha256": meta.checksum(records), "records": records}


def test_import_replay_refresh_and_browser_provenance(tmp_path, monkeypatch):
    output, raw, cache = tmp_path / "imported/ameriflux", tmp_path / "raw/ameriflux", tmp_path / "cache"
    meta.ingest(metadata(), output, raw)
    prepare_cache(cache)
    monkeypatch.setattr(httpx.Client, "get", lambda *a, **kw: pytest.fail("Offline import attempted HTTP"))
    report = amf.import_variables(cache, output, raw)
    assert report["sites"]["US-Ha1"]["base_variables"] == 3
    path = output / "ameriflux_us-ha1.yaml"
    before = path.read_bytes()
    meta.ingest(metadata(), output, raw)
    assert path.read_bytes() == before
    amf.import_variables(cache, output, raw)
    assert path.read_bytes() == before
    site = yaml.safe_load(path.read_text())["sites"][0]
    html = detail(site, "Imported", [])
    assert "Source product" in html and "Not marked as gap-filled" in html
    assert "Years with data" in html and "Derived BASE product" in html
    rendered = tmp_path / "site"
    render(rendered, output.parent, tmp_path / "curated")
    from tests.test_render_site import check_links
    check_links(rendered)
    assert list((rendered / "sources/raw/ameriflux/variables/coverage").glob("*.gz"))


def test_corrupt_response_does_not_replace_imported_files(tmp_path):
    output, raw, cache = tmp_path / "imported", tmp_path / "raw", tmp_path / "cache"
    meta.ingest(metadata(), output, raw)
    prepare_cache(cache)
    path = output / "ameriflux_us-ha1.yaml"
    before = path.read_bytes()
    bad = coverage(row())
    bad["record"]["records"][0]["coverage_percent"] = 99
    amf.write_compressed(cache / "coverage/US-Ha1.json.gz", bad)
    with pytest.raises(ValueError, match="checksum"):
        amf.import_variables(cache, output, raw)
    assert path.read_bytes() == before
    assert not (raw / "variables").exists()


def test_archived_definitions_and_coverage_have_checksums(tmp_path):
    output, raw, cache = tmp_path / "imported", tmp_path / "raw", tmp_path / "cache"
    meta.ingest(metadata(), output, raw)
    prepare_cache(cache)
    amf.import_variables(cache, output, raw)
    path = next((raw / "variables/definitions").glob("*.json"))
    data = json.loads(path.read_text())
    data["record"]["values"][0]["units"] = "invented unit"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="checksum"):
        meta.ingest(metadata(), output, raw)


def test_fetch_error_is_not_treated_as_empty_inventory():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404, json={"error": "missing"})))
    with client, pytest.raises(httpx.HTTPStatusError):
        amf.get_snapshot(amf.SITE_URL, client)


def test_resume_retries_failed_refresh_instead_of_reusing_stale_coverage(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    prepare_cache(cache)
    report_path = cache / "fetch-report.json"
    report = json.loads(report_path.read_text())
    report["coverage_failures"] = {"US-Ha1": "previous refresh failed"}
    report_path.write_text(json.dumps(report))
    calls = []
    def get_snapshot(url, client):
        calls.append(url)
        return coverage(row(year=2026))
    monkeypatch.setattr(amf, "get_snapshot", get_snapshot)
    assert amf.fetch_inputs(cache)["coverage_failures"] == {}
    assert calls == [amf.COVERAGE_URL + "US-Ha1"]
    saved = amf.read_snapshot(cache / "coverage/US-Ha1.json.gz")
    assert saved["record"]["records"][0]["year"] == 2026
    amf.fetch_inputs(cache)
    assert len(calls) == 1
