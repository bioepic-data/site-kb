"""Curation must survive refreshes and ambiguous builds must fail safely."""

import pytest
import yaml

from site_kb.scripts.build_db import build_database
from site_kb.scripts.fetch_deims import OUTPUT_DIR as DEIMS_OUTPUT
from site_kb.scripts.fetch_neon import OUTPUT_DIR as NEON_OUTPUT


def write_sites(path, *sites):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"sites": list(sites)}))


def test_refresh_preserves_curation_and_updates_other_fields(tmp_path):
    imported = tmp_path / "imported"
    curated = tmp_path / "curated"
    output = tmp_path / "built/sites.yaml"
    source = imported / "neon/example.yaml"
    override = curated / "overrides/example.yaml"
    base = {"id": "site_kb:example", "name": "API name", "notes": "Old notes",
            "location": {"latitude": 1.0, "longitude": 2.0, "country": "API country"},
            "variables": [{"name": "Source variable"}]}
    write_sites(source, base)
    write_sites(override, {"id": base["id"], "name": "Curated name", "notes": None,
                           "location": {"country": "Curated country"},
                           "variables": [{"name": "Curated variable"}]})
    write_sites(curated / "sites/manual.yaml", {"id": "site_kb:manual", "name": "Manual site"})
    original_override = override.read_bytes()
    assert build_database(imported, curated, output) == 2
    base["location"]["latitude"] = 3.0
    base["description"] = "New source description"
    write_sites(source, base)
    source_bytes = source.read_bytes()
    build_database(imported, curated, output)
    result = yaml.safe_load(output.read_text())["sites"][0]
    assert result["name"] == "Curated name"
    assert result["description"] == "New source description"
    assert result["location"] == {"latitude": 3.0, "longitude": 2.0, "country": "Curated country"}
    assert result["variables"] == [{"name": "Curated variable"}]
    assert "notes" not in result
    assert source.read_bytes() == source_bytes
    assert override.read_bytes() == original_override
    first_build = output.read_bytes()
    build_database(imported, curated, output)
    assert output.read_bytes() == first_build
    (curated / "sites/manual.yaml").unlink()
    assert build_database(imported, curated, output) == 1


@pytest.mark.parametrize("failure", ["duplicate", "collision", "unknown_override", "missing_name"])
def test_invalid_inputs_preserve_previous_output(tmp_path, failure):
    imported, curated, output = tmp_path / "imported", tmp_path / "curated", tmp_path / "output.yaml"
    site = {"id": "site_kb:example", "name": "Example"}
    write_sites(imported / "source.yaml", site)
    build_database(imported, curated, output)
    previous = output.read_bytes()
    if failure == "duplicate":
        write_sites(imported / "another.yaml", site)
    elif failure == "collision":
        write_sites(curated / "sites/example.yaml", site)
    elif failure == "unknown_override":
        write_sites(curated / "overrides/example.yaml", {"id": "site_kb:unknown", "name": "Unknown"})
    else:
        write_sites(curated / "overrides/example.yaml", {"id": site["id"], "name": None})
    with pytest.raises(ValueError):
        build_database(imported, curated, output)
    assert output.read_bytes() == previous


def test_output_cannot_overwrite_inputs(tmp_path):
    with pytest.raises(ValueError, match="outside input"):
        build_database(tmp_path / "imported", tmp_path / "curated", tmp_path / "imported/sites.yaml")


def test_importers_default_to_separate_source_directories():
    assert str(DEIMS_OUTPUT) == "db/imported/deims"
    assert str(NEON_OUTPUT) == "db/imported/neon"


def test_site_evidence_rejects_dangling_field_references():
    from site_kb.scripts.build_db import validate_site_evidence
    site = {'id': 'site_kb:test', 'location': {'latitude': 0.0},
            'network_registrations': [{'network': 'NGEE_TROPICS'}],
            'evidence': [{'supports': ['/location/latitude', '/network_registrations/0']}]}
    validate_site_evidence(site)
    for pointer in ['/location/longitude', '/network_registrations/1', '/network_registrations/-1']:
        site['evidence'][0]['supports'] = [pointer]
        with pytest.raises(ValueError, match='evidence targets absent field'):
            validate_site_evidence(site)
