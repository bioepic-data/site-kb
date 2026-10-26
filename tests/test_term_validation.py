"""Ensure term checks actually run on nested annotations, not just schema shape."""
from pathlib import Path

import pytest
import yaml
from linkml.validator import Validator
from linkml_term_validator.plugins import BindingValidationPlugin
from linkml_runtime.utils.schemaview import SchemaView

SCHEMA = Path(__file__).parents[1] / 'src/site_kb/schema/site_kb.yaml'


def test_every_ontology_term_field_has_a_validator_binding():
    sv = SchemaView(str(SCHEMA))
    for cls in sv.all_classes():
        for slot in sv.class_induced_slots(cls):
            if slot.range == 'OntologyTerm':
                assert any(binding.binds_value_of == 'id' for binding in slot.bindings), (cls, slot.name)


@pytest.mark.parametrize('field', ['site_type', 'ecosystem_terms', 'land_cover_terms'])
def test_linkml_term_validator_rejects_bad_nested_labels_and_ids(tmp_path, field):
    # Offline excerpt of the pinned ENVO release, not a mock of validator behavior.
    ontology = tmp_path / 'envo.obo'
    ontology.write_text('format-version: 1.2\nontology: envo\n\n[Term]\nid: ENVO:00002043\nname: wastewater treatment plant\n')
    config = tmp_path / 'oak.yaml'
    config.write_text(yaml.safe_dump({'ontology_adapters': {'ENVO': 'simpleobo:' + str(ontology)}}))
    plugin = BindingValidationPlugin(oak_config_path=config, cache_labels=False, cache_dir=tmp_path / 'cache')
    validator = Validator(schema=str(SCHEMA), validation_plugins=[plugin])
    for identifier, label, valid in [('ENVO:00002043', 'wastewater treatment plant', True),
                                      ('ENVO:00002043', 'incorrect label', False),
                                      ('ENVO:99999999', 'wastewater treatment plant', False)]:
        term = {'id': identifier, 'label': label}
        data = {'sites': [{'id': 'site_kb:test', 'name': 'Test', field: [term] if field == 'ecosystem_terms' else term}]}
        report = validator.validate(data, target_class='SiteCollection')
        assert (not report.results) == valid, report.results


def test_catalog_terms_are_checked_even_without_site_references(tmp_path):
    ontology = tmp_path / 'envo.obo'
    ontology.write_text('format-version: 1.2\nontology: envo\n\n[Term]\nid: ENVO:00002043\nname: wastewater treatment plant\n')
    config = tmp_path / 'oak.yaml'
    config.write_text(yaml.safe_dump({'ontology_adapters': {'ENVO': 'simpleobo:' + str(ontology)}}))
    plugin = BindingValidationPlugin(oak_config_path=config, cache_labels=False, cache_dir=tmp_path / 'cache')
    validator = Validator(schema=str(SCHEMA), validation_plugins=[plugin])
    data = {'sites': [], 'variable_definitions': [{'id': 'site_kb:test', 'name': 'Test',
            'term': {'id': 'ENVO:00002043', 'label': 'incorrect label'}}]}
    assert validator.validate(data, target_class='SiteCollection').results
    data['variable_definitions'][0]['term']['label'] = 'wastewater treatment plant'
    assert not validator.validate(data, target_class='SiteCollection').results


def test_bervo_mapping_target_rejects_wrong_canonical_label(tmp_path):
    # Canonical capitalization from BERVO releases/2026-09-03, independent of mappings.
    ontology = tmp_path / 'bervo.obo'
    ontology.write_text('format-version: 1.2\nontology: bervo\n\n[Term]\nid: BERVO:8000133\nname: Temperature\n')
    config = tmp_path / 'oak.yaml'
    config.write_text(yaml.safe_dump({'ontology_adapters': {'BERVO': 'simpleobo:' + str(ontology)}}))
    plugin = BindingValidationPlugin(oak_config_path=config, cache_labels=False, cache_dir=tmp_path / 'cache')
    validator = Validator(schema=str(SCHEMA), validation_plugins=[plugin])
    data = {'mappings': [{'source': 'site-kb', 'source_id': 'site_kb:temperature',
            'target': {'id': 'BERVO:8000133', 'label': 'Air temperature'},
            'relation': 'BROAD', 'origin': 'CURATED', 'evidence': ['https://example.org/review']}]}
    assert validator.validate(data, target_class='VariableMappingCollection').results
    data['mappings'][0]['target']['label'] = 'Temperature'
    assert not validator.validate(data, target_class='VariableMappingCollection').results


def test_classification_mapping_target_rejects_wrong_canonical_label(tmp_path):
    ontology = tmp_path / 'envo.obo'
    ontology.write_text('format-version: 1.2\nontology: envo\n\n[Term]\nid: ENVO:00000020\nname: lake\n')
    config = tmp_path / 'oak.yaml'
    config.write_text(yaml.safe_dump({'ontology_adapters': {'ENVO': 'simpleobo:' + str(ontology)}}))
    plugin = BindingValidationPlugin(oak_config_path=config, cache_labels=False, cache_dir=tmp_path / 'cache')
    validator = Validator(schema=str(SCHEMA), validation_plugins=[plugin])
    data = {'mappings': [{'source': 'NEON', 'scheme': 'site_subtype', 'value': 'Lake', 'target_slot': 'SITE_TYPE',
            'target': {'id': 'ENVO:00000020', 'label': 'pond'}, 'relation': 'CLOSE', 'origin': 'CURATED',
            'evidence': ['https://example.org/review']}]}
    assert validator.validate(data, target_class='ClassificationMappingCollection').results
    data['mappings'][0]['target']['label'] = 'lake'
    assert not validator.validate(data, target_class='ClassificationMappingCollection').results
