"""NEON site data-product declarations, validation, and offline replay."""
import gzip
import json

import pytest
import yaml

from site_kb.scripts import fetch_neon as neon
from site_kb.scripts.fetch_ameriflux import checksum


WHEN = "2026-10-25T00:00:00+00:00"


def snapshot(data, url):
    record = {"data": data}
    return {"source_url": url, "retrieved_at": WHEN, "record": record, "sha256": checksum(record)}


def product_entry(code="DP1.00001.001", title="2D wind speed and direction", months=("2019-12", "2020-01")):
    return {"dataProductCode": code, "dataProductTitle": title, "availableMonths": list(months),
            "availableReleases": [{"release": "RELEASE-2026", "availableMonths": list(months)},
                                  {"release": "PROVISIONAL", "availableMonths": []}]}


def site(code="HARV", products=None):
    return {"siteCode": code, "siteName": "Harvard Forest & Quabbin Watershed NEON", "siteType": "CORE",
            "siteLatitude": 42.5, "siteLongitude": -72.2, "stateName": "Massachusetts",
            "domainCode": "D01", "domainName": "Northeast",
            "deimsId": "https://deims.org/9dbbd9ea-21dc-43e3-b55d-42623427e642",
            "dataProducts": [product_entry()] if products is None else products}


def catalog():
    return snapshot([{"productCode": "DP1.00001.001", "productName": "2D wind speed and direction",
                      "productCategory": "Level 1 Data Product",
                      "productScienceTeam": "Terrestrial Instrument System (TIS)"}], neon.PRODUCTS_URL)


def test_site_products_become_unclassified_declarations_with_provenance():
    [result] = neon.convert(snapshot([site()], neon.SITES_URL), catalog())
    [variable] = result["variables"]
    assert variable["name"] == "2D wind speed and direction"
    assert variable["declaration_kind"] == "UNSPECIFIED"
    assert variable["data_product"] == "DP1.00001.001"
    assert variable["source_category"] == "Level 1 Data Product"
    assert variable["available_years"] == [2019, 2020]
    assert variable["data_versions"] == ["RELEASE-2026"]  # releases without months are not claimed
    assert "term" not in variable and "mappings" not in variable
    [source] = variable["source_variables"]
    assert source == {"source": "NEON", "source_id": "DP1.00001.001", "source_name": "2D wind speed and direction",
                      "vocabulary": "NEON data product catalog", "record_url": neon.SITES_URL,
                      "field_path": "/data/0/dataProducts/0", "retrieved_at": WHEN}
    assert "not in-situ" in result["variable_notes"]
    assert result["network_registrations"][1]["network_id"] == "9dbbd9ea-21dc-43e3-b55d-42623427e642"


def test_products_absent_from_catalog_keep_verbatim_site_listing():
    entry = product_entry("DP1.99999.001", "Uncatalogued product")
    [result] = neon.convert(snapshot([site(products=[entry])], neon.SITES_URL), catalog())
    [variable] = result["variables"]
    assert variable["name"] == "Uncatalogued product" and "source_category" not in variable


def test_site_without_products_has_no_variables():
    [result] = neon.convert(snapshot([site(products=[])], neon.SITES_URL), catalog())
    assert "variables" not in result and "variable_notes" not in result


@pytest.mark.parametrize("change", [
    lambda s: s["dataProducts"][0].update(dataProductCode="DP9.1"),
    lambda s: s["dataProducts"][0].update(availableMonths=["2020-13"]),
    lambda s: s["dataProducts"][0].update(dataProductTitle=" "),
    lambda s: s["dataProducts"].append(product_entry()),
    lambda s: s.update(siteCode="harv"),
])
def test_malformed_batches_are_rejected(change):
    record = site()
    change(record)
    with pytest.raises(ValueError):
        neon.convert(snapshot([record], neon.SITES_URL), catalog())


def test_checksum_mismatch_is_rejected():
    sites = snapshot([site()], neon.SITES_URL)
    sites["record"]["data"][0]["siteName"] = "Tampered"
    with pytest.raises(ValueError, match="checksum"):
        neon.convert(sites, catalog())


def test_offline_replay_writes_byte_stable_records(tmp_path):
    raw = tmp_path / "raw"
    neon.write_snapshot(raw / "sites.json.gz", snapshot([site()], neon.SITES_URL))
    neon.write_snapshot(raw / "products.json.gz", catalog())
    first = (raw / "sites.json.gz").read_bytes()
    neon.write_snapshot(raw / "sites.json.gz", json.loads(gzip.decompress(first)))
    assert (raw / "sites.json.gz").read_bytes() == first
    out = tmp_path / "out"
    neon.main(output_dir=out, raw_dir=raw, offline=True, summary_only=False)
    written = yaml.safe_load((out / "neon_harv.yaml").read_text())
    assert written["sites"][0]["variables"][0]["source_variables"][0]["retrieved_at"] == WHEN
