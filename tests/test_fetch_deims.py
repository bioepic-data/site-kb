"""Tests for DEIMS API mapping helpers."""

import pytest

from site_kb.scripts.fetch_deims import bounding_box, deims_to_site, environment_classifications


def test_deims_list_country_without_coordinates_does_not_emit_location():
    site = deims_to_site(
        {
            "id": {"suffix": "90e55d56-fb0a-44c3-aeb6-c750d0eeefc4"},
            "title": "Changshu Agro-Ecological Experimental Station - China",
        },
        {
            "attributes": {
                "geographic": {
                    "country": ["China"],
                    "elevation": {"avg": "3"},
                }
            }
        },
    )

    assert "location" not in site
    assert "DEIMS country: China" in site["notes"]
    assert "DEIMS average elevation: 3 m" in site["notes"]


def test_deims_coordinates_emit_schema_compatible_location():
    site = deims_to_site(
        {
            "id": {"suffix": "abc"},
            "title": "Example Site",
            "coordinates": "120.6984,31.5497",
        },
        {
            "attributes": {
                "geographic": {
                    "country": ["China"],
                    "elevation": {"avg": "3"},
                }
            }
        },
    )

    assert site["location"] == {
        "latitude": 31.5497,
        "longitude": 120.6984,
        "country": "China",
        "elevation_meters": 3.0,
    }


def test_deims_mapper_normalizes_scalar_and_list_detail_fields():
    site = deims_to_site(
        {
            "id": "abc",
            "title": None,
            "coordinates": {"lat": "45.0", "lng": "-122.0"},
        },
        {
            "attributes": {
                "general": {"abstract": ["First sentence.", "Second sentence."]},
                "geographic": {
                    "country": "United States",
                    "elevation": "42",
                },
                "environmentalCharacteristics": {
                    "biogeographicalRegion": ["Region A", "Region B"],
                },
            }
        },
    )

    assert site["id"] == "site_kb:deims-unknown"
    assert site["network_registrations"][0]["network_id"] == "abc"
    assert site["description"] == "First sentence., Second sentence."
    assert site["location"]["elevation_meters"] == 42.0
    assert site["notes"] == "Biogeographical region: Region A, Region B"


def test_live_json_shape_preserves_source_identity_without_inventing_mappings():
    import json
    from pathlib import Path
    detail = json.loads((Path(__file__).parent / 'data/deims_observed_properties.json').read_text())
    when = '2026-09-23T00:00:00+00:00'
    site = deims_to_site({'id': detail['id'], 'title': detail['title']}, detail, when)
    assert site['location']['latitude'] == 24.5439
    assert site['location']['longitude'] == 101.0276
    assert len(site['variables']) == 6
    variable = site['variables'][0]
    assert variable['name'] == 'atmospheric parameter'
    assert variable['declaration_kind'] == 'UNSPECIFIED'
    assert not any(k in variable for k in ('term', 'mappings', 'units', 'temporal_resolution'))
    source = variable['source_variables'][0]
    assert source['source_id'] == 'http://vocabs.lter-europe.net/EnvThes/20937'
    assert source['source_name'] == variable['name']
    assert source['vocabulary'] == 'EnvThes'
    assert source['field_path'] == '/attributes/focusDesignScale/observedProperties/0'
    assert source['retrieved_at'] == when
    assert source['source_modified_at'] == detail['changed']


def test_coordinate_and_elevation_zeros_and_wkt():
    from site_kb.scripts.fetch_deims import _parse_coordinates
    assert _parse_coordinates('POINT(0 0)') == (0, 0)
    assert _parse_coordinates(' POINT (-1.5 4.2) ') == (4.2, -1.5)
    assert _parse_coordinates({'latitude': 0, 'longitude': 0}) == (0, 0)
    assert _parse_coordinates('POINT EMPTY') == (None, None)
    site = deims_to_site({'id': 'abc', 'title': 'Zero', 'coordinates': 'POINT (0 0)'},
                         {'attributes': {'geographic': {'elevation': {'avg': 0}}}})
    assert site['location']['elevation_meters'] == 0


def test_missing_property_uri_preserves_label_and_does_not_guess_identifier():
    site = deims_to_site({'id': 'abc'}, {'attributes': {'focusDesignScale': {'observedProperties': [
        {'label': 'A source label', 'uri': None}]}}})
    source = site['variables'][0]['source_variables'][0]
    assert source['source_name'] == 'A source label'
    assert 'source_id' not in source
    assert 'vocabulary' not in source


def test_invalid_properties_raise_instead_of_silently_dropping_data():
    import pytest
    for properties in ({'unexpected': 'shape'}, [{'uri': 'http://example.org/x'}]):
        with pytest.raises(ValueError):
            deims_to_site({'id': 'abc'}, {'attributes': {'focusDesignScale': {'observedProperties': properties}}})


def test_refresh_preserves_local_id_and_saves_complete_snapshot(tmp_path, monkeypatch):
    import json
    import yaml
    from typer.testing import CliRunner
    from site_kb.scripts import fetch_deims
    output, raw = tmp_path / 'imported', tmp_path / 'raw'
    output.mkdir()
    original = output / 'original.yaml'
    original.write_text(yaml.safe_dump({'sites': [{'id': 'site_kb:stable', 'name': 'Old name',
        'network_registrations': [{'network': 'DEIMS', 'network_id': 'abc'}]}]}))
    detail = {'id': {'suffix': 'abc'}, 'title': 'Renamed upstream', 'type': 'site',
              'attributes': {'unmodeled': {'keep': 'all of this'}, 'focusDesignScale': {'observedProperties': []}}}
    monkeypatch.setattr(fetch_deims, 'fetch_site_detail', lambda _: detail)
    monkeypatch.setattr(fetch_deims, 'fetch_site_list', lambda: (_ for _ in ()).throw(AssertionError('Must not fetch all sites')))
    result = CliRunner().invoke(fetch_deims.app, ['--refresh-existing', '--output-dir', str(output), '--raw-dir', str(raw)])
    assert result.exit_code == 0, result.output
    site = yaml.safe_load(original.read_text())['sites'][0]
    assert site['id'] == 'site_kb:stable'
    assert site['name'] == 'Renamed upstream'
    assert len(list(output.glob('*.yaml'))) == 1
    snapshot = json.loads((raw / 'abc.json').read_text())
    assert snapshot['record'] == detail
    assert snapshot['retrieved_at']


def test_http_200_api_error_payload_is_rejected(monkeypatch):
    import httpx
    import pytest
    from site_kb.scripts import fetch_deims
    monkeypatch.setattr(fetch_deims.httpx, 'get', lambda *a, **kw: httpx.Response(
        200, json={'errors': {'status': 400}}, request=httpx.Request('GET', 'https://deims.org/api/sites')))
    with pytest.raises(ValueError):
        fetch_deims.fetch_site_detail('abc')
    with pytest.raises(ValueError):
        fetch_deims.fetch_site_list()


def test_boundary_polygons_give_bounding_boxes():
    assert bounding_box("MULTIPOLYGON (((-72.19 42.53, -72.16 42.55, -72.17 42.52, -72.19 42.53)))") == {
        "west": -72.19, "south": 42.52, "east": -72.16, "north": 42.55}
    assert bounding_box("POINT (-72.1 42.5)") is None and bounding_box(None) is None
    with pytest.raises(ValueError, match="antimeridian"):
        bounding_box("POLYGON ((179 0, -179 0, -179 1, 179 0))")


def test_boundary_excluding_the_record_point_is_omitted_with_a_note():
    detail = {"attributes": {"geographic": {
        "coordinates": "POINT (13.59 46.49)",
        "boundaries": "POLYGON ((11.43 46.27, 11.77 46.27, 11.77 46.59, 11.43 46.27))"}}}
    site = deims_to_site({"id": "x", "title": "Tarvisio"}, detail)
    assert "bounding_box" not in site["location"]
    assert "DEIMS boundary omitted" in site["notes"] and "km" in site["notes"]
    detail["attributes"]["geographic"]["coordinates"] = "POINT (11.6 46.4)"
    assert deims_to_site({"id": "x", "title": "Tarvisio"}, detail)["location"]["bounding_box"]["west"] == 11.43


def test_environmental_characteristics_become_verbatim_classifications():
    env = {"biome": "mixed_forest", "geoBonBiome": ["Terrestrial"], "ecosystemType": [{"label": "Forest", "uri": None}],
           "eunisHabitat": None}
    result = environment_classifications(env, "abc", "2026-11-06T00:00:00+00:00")
    assert [(c["scheme"], c["value"], c["field_path"]) for c in result] == [
        ("geoBonBiome", "Terrestrial", "/attributes/environmentalCharacteristics/geoBonBiome/0"),
        ("biome", "mixed_forest", "/attributes/environmentalCharacteristics/biome"),
        ("ecosystemType", "Forest", "/attributes/environmentalCharacteristics/ecosystemType/0")]
    assert result[0]["record_url"].endswith("/sites/abc") and result[0]["retrieved_at"].startswith("2026")
    with pytest.raises(ValueError, match="not text"):
        environment_classifications({"biome": 3}, "abc", None)
