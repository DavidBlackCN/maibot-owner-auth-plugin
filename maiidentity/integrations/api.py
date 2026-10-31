from .. import API_MAJOR, CONFIG_VERSION, DB_SCHEMA, PLUGIN_ID, PLUGIN_VERSION
from ..shared.core import Clock
from ..runtime_versions import runtime_descriptor

PROTECTED = ("resolve_identity", "get_identity", "authorize", "get_confirmed_relations", "build_context", "get_diagnostics")


def envelope(*, data=None, code=None):
    return {"api_version": int(API_MAJOR), "ok": code is None, "data": data,
            "error": {"code": code, "retryable": False} if code else None,
            "request_id": None, "as_of": Clock().iso()}


def descriptor(ready=False):
    from ..policy.service import MAIHUSH
    return envelope(data={"plugin_id": PLUGIN_ID, "plugin_version": PLUGIN_VERSION, "config_version": CONFIG_VERSION,
        **runtime_descriptor(), "maihush_capabilities": sorted(MAIHUSH),
        "maihush_delegation": "forbidden", "maihush_policy": "external_business_policy_required",
        "maihush_scope": {"kind":"stream","resource_type":"group","platform":"qq","identity_source":"local_command_until_H03"},
        "db_schema": DB_SCHEMA, "api_major": API_MAJOR, "ready": ready, "get_contract": "public", "features":["life_policy_v2","public_social_context_v1","fixed_profiles_v1"],
        "protected_methods": {name: "denied_no_trusted_transport" for name in PROTECTED},
        "write_methods": "unsupported", "binding_challenge": "disabled", "legacy_templates": "inactive_only",
        "alias_transport": "disabled_no_complete_attested_history", "planner_actor": "disabled",
        "planner_typed_items": "schema_1_append_only", "local_projection": "unsupported", "guard_mode": "context_only",
        "cross_plugin_privileged_enabled": False, "H01": "unsupported", "H02": "unsupported",
        "local_command_adapter": {"host_patch_required":False,
            "commands":["help","status"],
            "vita_policy":"read_only_boolean_not_actor_proof_or_execution_token",
            "vita_execution":"Vita_own_official_Command_entry_only",
            "general_remote_privileges":False},
        "H03": "disabled_no_trusted_caller_actor_context", "atomic_remote_consume": "unsupported",
        "maivita_contract": "1.0.0", "policy_transport": "read_only_vita_rules_no_delegation", "authorization_from_payload": False})


class PublicAPI:
    """No string proof, caller field or historical message grants API access."""
    def call(self, method, /, **untrusted_payload):
        if method == "get_contract":
            return descriptor()
        if method in PROTECTED:
            return envelope(code="UNTRUSTED_CONTEXT")
        return envelope(code="UNSUPPORTED")
