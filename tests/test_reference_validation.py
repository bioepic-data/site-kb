"""Exercise real excerpt matching against independently fetched source text."""
from copy import deepcopy
from pathlib import Path

import pytest
import requests
import yaml
from linkml.validator import Validator
from linkml_reference_validator.cli.shared import load_validation_config
from linkml_reference_validator.plugins.reference_validation_plugin import ReferenceValidationPlugin

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / 'src/site_kb/schema/site_kb.yaml'


@pytest.fixture
def reference_validator(monkeypatch):
    # Committed reference text must suffice; tests must never refresh it online.
    def no_network(*args, **kwargs):
        raise AssertionError('Reference validation unexpectedly accessed the network')
    monkeypatch.setattr(requests.sessions.Session, 'request', no_network)
    config = load_validation_config(ROOT / '.linkml-reference-validator.yaml', load_custom_sources=False)
    config.cache_dir = ROOT / config.cache_dir
    config.fetch_full_text = False
    plugin = ReferenceValidationPlugin(config=config)
    return Validator(schema=str(SCHEMA), validation_plugins=[plugin]), plugin


def quoted_site():
    data = yaml.safe_load((ROOT / 'db/curated/sites/ngee_tropics.yaml').read_text())
    return deepcopy(next(s for s in data['sites'] if s['id'].endswith('barro-colorado-island')))


def test_all_ngee_quotations_are_actually_checked_offline(reference_validator):
    validator, plugin = reference_validator
    data = yaml.safe_load((ROOT / 'db/curated/sites/ngee_tropics.yaml').read_text())
    report = validator.validate(data, target_class='SiteCollection')
    assert not report.results, report.results
    assert plugin.snippets_checked == 5  # Prevent a vacuous pass if annotations disappear.
    assert plugin.snippets_skipped == plugin.snippets_unavailable == 0
    assert plugin.titles_checked == 0  # Display labels are not bibliographic title claims.


def test_fabricated_quotation_is_rejected(reference_validator):
    validator, plugin = reference_validator
    site = quoted_site()
    evidence = next(e for e in site['evidence'] if e.get('quotation'))
    evidence['quotation'] = 'This island has a latitude of 42.123456 and contains a permanent Martian field station.'
    report = validator.validate({'sites': [site]}, target_class='SiteCollection')
    assert report.results
    assert any(r.type == 'reference_validation' for r in report.results)
    assert plugin.snippets_checked == 1


def test_unavailable_reference_fails_instead_of_skipping(reference_validator):
    validator, plugin = reference_validator
    site = quoted_site()
    next(e for e in site['evidence'] if e.get('quotation'))['source_url'] = 'unsupported:missing-source'
    report = validator.validate({'sites': [site]}, target_class='SiteCollection')
    assert any(str(r.severity.value) == 'ERROR' for r in report.results), report.results
    assert plugin.snippets_unavailable == 1
    assert plugin.snippets_checked == plugin.snippets_skipped == 0


def test_source_links_without_quotes_do_not_claim_verification(reference_validator):
    validator, plugin = reference_validator
    site = quoted_site()
    site['evidence'] = [e for e in site['evidence'] if not e.get('quotation')]
    report = validator.validate({'sites': [site]}, target_class='SiteCollection')
    assert not report.results
    assert plugin.snippets_checked == plugin.titles_checked == 0
