import json
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.host.config import MaiIdentityConfig
from maibot_sdk.config import extract_plugin_config_version


def test_host_webui_schema_builds_required_row_drafts_without_runtime_defaults():
    schema = MaiIdentityPlugin().get_webui_config_schema(plugin_id='identity', plugin_version='test')
    assert schema['plugin_id'] == 'identity'
    assert set(schema['sections']) == {'plugin', 'identity', 'context', 'management'}
    people = schema['sections']['identity']['fields']['people']
    assert people['default'] == [] and people['item_fields']['qq']['default'] == ''
    assert people['item_fields']['nickname']['default'] == ''
    assert people['item_fields']['prompt_template']['default'] == ''
    config = {name: {k: v['default'] for k, v in s['fields'].items()} for name, s in schema['sections'].items()}
    assert MaiIdentityConfig.model_validate(json.loads(json.dumps(config))) == MaiIdentityConfig()
    for section in schema['sections'].values():
        for field in section['fields'].values():
            if field['ui_type'] == 'select': assert '' not in (field.get('choices') or [])
    assert schema['sections']['plugin']['fields']['config_version']['disabled']


@pytest.mark.parametrize('patch', [
    {'identity': {'accounts': [{}]}}, {'roles': {'entries': [{}]}},
    {'identity': {'people': [{}]}},
    {'integrations': {'cross_plugin_privileged_enabled': True}},
])
def test_editor_drafts_are_not_valid_accounts_or_roles(patch):
    MaiIdentityPlugin.build_config_schema()
    with pytest.raises(ValueError):
        MaiIdentityConfig.model_validate(patch)


def test_minimal_host_config_needs_explicit_version_before_plugin_normalization():
    with pytest.raises(ValueError, match='config_version'):
        extract_plugin_config_version({'plugin': {'enabled': True}})
    minimal = {'plugin': {'enabled': True, 'config_version': '4'}}
    assert extract_plugin_config_version(minimal) == '4'
    normalized, _ = MaiIdentityPlugin().normalize_plugin_config(minimal)
    assert MaiIdentityConfig.model_validate(normalized).management.admin_accounts == []
