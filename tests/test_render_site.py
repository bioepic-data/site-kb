"""Validate portable pages, source provenance, and safe source rendering."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml

from site_kb.scripts.render_site import render, slug


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.links.extend(attrs[key] for key in ('href', 'src') if key in attrs)
        if tag == 'script':
            self.scripts.append(attrs.get('src'))


def check_links(output):
    for page in output.rglob('*.html'):
        parser = Links()
        parser.feed(page.read_text())
        for url in parser.links:
            parsed = urlsplit(url)
            assert parsed.scheme in ('', 'http', 'https')
            if not parsed.scheme and parsed.path:
                assert not parsed.path.startswith('/'), (page, url)
                assert (page.parent / unquote(parsed.path)).exists(), (page, url)
        assert parser.scripts == [('../' if page.parent.name == 'sites' else '') + 'assets/app.js']


def test_full_catalog_has_working_relative_links(tmp_path):
    output = tmp_path / 'site'
    count = render(output)
    assert count == len(list(output.joinpath('sites').glob('*.html')))
    check_links(output)
    before = (output / 'index.html').read_bytes()
    render(output)
    assert (output / 'index.html').read_bytes() == before


def test_untrusted_text_and_curated_provenance(tmp_path):
    imported, curated, output = tmp_path / 'imported', tmp_path / 'curated', tmp_path / 'site'
    imported.mkdir()
    (curated / 'overrides').mkdir(parents=True)
    site = {'id': 'site_kb:test', 'name': '<script>alert(1)</script>',
            'description': '<img src=x onerror=alert(1)>',
            'network_registrations': [{'network': 'NEON', 'network_id': 'TEST', 'network_url': 'javascript:alert(1)'}],
            'variables': [{'name': 'Temperature', 'term': {'id': 'ENVO:09200001', 'label': 'temperature of air'}, 'units': {'id': 'UO:0000027', 'label': 'degree Celsius'}}]}
    (imported / 'test.yaml').write_text(yaml.safe_dump({'sites': [site]}))
    (curated / 'overrides/test.yaml').write_text(yaml.safe_dump({'sites': [{'id': site['id'], 'notes': 'A curated note'}]}))
    render(output, imported, curated)
    html = (output / 'sites' / (slug(site['id']) + '.html')).read_text()
    assert '<script>alert' not in html
    assert '<img src=x' not in html
    assert 'href="javascript:' not in html
    assert '&lt;script&gt;' in html
    assert 'purl.obolibrary.org/obo/ENVO_09200001' in html
    assert 'Record origin: <strong>Enriched</strong>' in html
    assert 'sources/imported/test.yaml' in html
    assert 'sources/curated/overrides/test.yaml' in html
    check_links(output)


def test_refuses_to_replace_unrecognized_directory(tmp_path):
    (tmp_path / 'important.txt').write_text('preserve')
    with pytest.raises(ValueError, match='unrecognized'):
        render(tmp_path)
    assert (tmp_path / 'important.txt').read_text() == 'preserve'


def test_source_and_curated_crosswalk_are_rendered_separately(tmp_path):
    imported, curated, output = tmp_path / 'imported', tmp_path / 'curated', tmp_path / 'site'
    imported.mkdir()
    (curated / 'variable_mappings').mkdir(parents=True)
    site = {'id': 'site_kb:example', 'name': 'Example', 'variables': [{'name': 'Soil parameter',
        'declaration_kind': 'UNSPECIFIED', 'source_variables': [{'source': 'DEIMS',
        'source_id': 'http://example.org/source', 'source_name': 'Soil parameter',
        'record_url': 'https://example.org/record', 'field_path': '/properties/0'}]}]}
    mapping = {'source': 'DEIMS', 'source_id': 'http://example.org/source',
        'source_name': 'Soil parameter', 'target': {'id': 'BERVO:9999999', 'label': 'Synthetic test concept'},
        'relation': 'BROAD', 'origin': 'CURATED', 'evidence': ['https://example.org/review']}
    (imported / 'example.yaml').write_text(yaml.safe_dump({'sites': [site]}))
    (curated / 'variable_mappings/example.yaml').write_text(yaml.safe_dump({'mappings': [mapping]}))
    render(output, imported, curated)
    html = (output / 'sites' / (slug(site['id']) + '.html')).read_text()
    assert 'granularity unclassified' in html
    assert 'Source ID' in html
    assert 'Curated crosswalk' in html
    assert 'BROAD' in html
    assert 'Synthetic test concept' in html
    assert 'sources/curated/variable_mappings/example.yaml' in html
    assert 'Canonical term' not in html
    assert 'Record origin: <strong>Enriched</strong>' in html
    check_links(output)


def test_mixs_links_use_the_standard_w3id_namespace():
    from site_kb.scripts.render_site import term
    html = term({'id': 'MIXS:0000657', 'label': 'efficiency_percent'})
    assert 'https://w3id.org/mixs/0000657' in html
    assert 'purl.obolibrary.org' not in html


def test_study_context_catalog_and_dataset_availability_are_visible(tmp_path):
    output = tmp_path / 'site'
    render(output)
    html = (output / 'sites' / (slug('site_kb:wwtp-tatlar') + '.html')).read_text()
    assert 'SAMEA4527663' in html and 'PUBLIC' in html
    assert 'Site evidence' in html and 'Study sampling period' in html
    assert '../variables.html#' in html
    catalog = (output / 'variables.html').read_text()
    assert 'Candidate profiles' in catalog
    assert 'efficiency_percent' in catalog
    assert 'No site declarations reference this definition yet.' in catalog
    assert 'sources/curated/variables/wastewater_studies.yaml' in html


def test_ameriflux_raw_provenance_links(tmp_path):
    from site_kb.scripts.fetch_ameriflux import API_URL, checksum, ingest
    imported, curated, output = tmp_path / 'imported', tmp_path / 'curated', tmp_path / 'site'
    records = [{'SITE_ID': 'US-Ha1', 'SITE_NAME': 'Harvard Forest'}]
    ingest({'source_url': API_URL, 'retrieved_at': '2026-10-15T00:00:00+00:00',
            'response_sha256': checksum(records), 'records': records},
           imported / 'ameriflux', tmp_path / 'raw/ameriflux')
    render(output, imported, curated)
    html = (output / 'sites' / (slug('site_kb:ameriflux-us-ha1') + '.html')).read_text()
    assert 'sources/raw/ameriflux/US-Ha1.json' in html
    assert 'sources/imported/ameriflux/ameriflux_us-ha1.yaml' in html
    assert 'import-report.json' not in html
    check_links(output)
