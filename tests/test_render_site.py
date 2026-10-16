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


def test_location_evidence_is_linked_and_escaped():
    from site_kb.scripts.render_site import detail
    site = {'id': 'site_kb:evidence', 'name': 'Evidence test',
            'location': {'latitude': 0.0, 'longitude': -79.543},
            'evidence': [{'supports': ['/location/latitude', '/location/longitude'],
                          'source_url': 'https://example.org/source.pdf#page=54',
                          'source_label': 'Source <title>', 'locator': 'Printed p. 46 (PDF p. 54)',
                          'quotation': '<script>alert(1)</script>',
                          'notes': 'Decimal degrees; datum unspecified.'}]}
    html = detail(site, 'Curated', [])
    assert html.count('href="#evidence-1"') == 2
    assert 'id="evidence-1"' in html
    assert 'source.pdf#page=54' in html and 'Printed p. 46 (PDF p. 54)' in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html
    assert 'Coordinate datum: not reported' in html
    assert 'Coordinates not recorded' not in html
    site['location'] = {'country': 'Panama'}
    site.pop('evidence')
    assert 'Coordinates not recorded' in detail(site, 'Curated', [])


def test_curated_ngee_coordinates_have_field_specific_evidence():
    for path in Path('db/curated/sites').glob('ngee_*.yaml'):
        for site in yaml.safe_load(path.read_text())['sites']:
            for key in ('latitude', 'longitude', 'elevation_meters'):
                if key in site.get('location', {}):
                    matches = [e for e in site.get('evidence', []) if '/location/' + key in e['supports']]
                    assert matches, (site['id'], key)
                    assert all(e.get('quotation') and e.get('locator') and e.get('notes') for e in matches)
