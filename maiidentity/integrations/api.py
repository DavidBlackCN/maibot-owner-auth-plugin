from .. import API_MAJOR, CONFIG_VERSION, DB_SCHEMA, PLUGIN_ID, PLUGIN_VERSION
from ..shared.core import Clock
from ..runtime_versions import runtime_descriptor


def envelope(*, data=None, code=None):
    return {"api_version": int(API_MAJOR), "ok": code is None, "data": data,
            "error": {"code": code, "retryable": False} if code else None,
            "request_id": None, "as_of": Clock().iso()}


def descriptor(ready=False):
    return envelope(data={"plugin_id": PLUGIN_ID, "plugin_version": PLUGIN_VERSION,
        "config_version": CONFIG_VERSION, "db_schema": DB_SCHEMA, "api_major": API_MAJOR,
        **runtime_descriptor(), "ready": ready,
        "features": ["fixed_profiles_v1", "admin_query_v1", "life_policy_v2", "public_social_context_v1"],
        "methods": ["get_contract", "is_admin", "get_vita_policy", "get_public_social_context"],
        "commands": ["help", "status"], "write_methods": "unsupported",
        "authorization_from_payload": False,
        "policy_transport": "read_only_config_query_not_actor_proof_or_execution_token",
        "maihush_management": "independent", "planner_typed_items": "schema_1_append_only"})
