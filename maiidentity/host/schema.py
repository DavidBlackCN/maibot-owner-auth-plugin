"""Default-constructible WebUI drafts, never used for runtime validation."""
from copy import deepcopy
from maibot_sdk import PluginConfigBase
from maibot_sdk.config import generate_plugin_config_schema
from pydantic import Field, create_model
from .config import PersonEntry, IdentitySection, MaiIdentityConfig


def draft_model(model, defaults, annotations=None):
    fields = {}
    for name, info in model.model_fields.items():
        draft = deepcopy(info)
        if draft.is_required():
            draft.default = defaults[name]
        fields[name] = ((annotations or {}).get(name, info.annotation), draft)
    # Do not inherit the runtime validators: empty UI rows are incomplete drafts.
    return create_model(model.__name__ + 'Draft', __base__=PluginConfigBase, **fields)


def build_schema(**metadata):
    person = draft_model(PersonEntry, {'qq': '', 'nickname': ''})
    identity = create_model('IdentityDraft', __base__=IdentitySection,
        people=(list[person], Field(default_factory=list, description='QQ、称呼与相处说明', json_schema_extra={'label': '固定身份名单'})))
    config = create_model('IdentityConfigDraft', __base__=MaiIdentityConfig,
        identity=(identity, Field(default_factory=identity)))
    schema = generate_plugin_config_schema(config, **metadata)
    for section in schema['sections'].values():
        for field in section['fields'].values():
            if field['name'] == 'config_version':
                field['disabled'] = True
    return schema
