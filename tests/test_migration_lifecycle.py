from pathlib import Path
import json
import sqlite3
import tomllib

import pytest
from maibot_sdk.context import PluginContext, PluginPaths
from pydantic import ValidationError

from maiidentity.compatibility.migration import activate, apply, preview, rollback_snapshot, sha
from maiidentity.host.config import MaiIdentityConfig
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.shared.core import Denied
from maiidentity.storage.activation import validate_activation
from maiidentity.storage.database import Database, WriterLease
from .test_context_contract import block_data


@pytest.mark.parametrize("body", [
    '[plugin]\nuser_count=1\n[user1]\nqq="10001"\n[user2]\nowner_qq=10002\nenabled=false\n',
    '[[owner_auth.users]]\nowner_qq=10001\nnickname="old owner"\n',
    '[user]\nowner_qq="10001"\n',
    '[[user]]\nqq="10001"\n',
    '[[users.entries]]\nqq="10001"\n',
    '[owner_auth]\nUser=1\n[user1]\nowner_qq="10001"\n',
])
def test_legacy_formats_dry_run_apply_backup_idempotency_and_no_privileges(tmp_path, body):
    source = tmp_path/"source.toml"
    source.write_text(body, encoding="utf-8")
    before = sha(source)
    target = tmp_path/"new"
    plan = preview(source, namespace="adapter", instance="instance")
    assert not target.exists() and not plan["errors"]
    result = apply(plan, target)
    assert apply(plan, target) == result and sha(source) == before
    db = Database(target/"data/identity.db")
    try:
        assert not db.records("role") and not db.records("grant") and not db.records("relation") and not db.records("delegation")
        if "user_count" in body:
            assert db.get("legacy_overlay", "user2")["inactive_reason"] == "over_user_count"
    finally:
        db.close()
    cfg = MaiIdentityConfig.model_validate(tomllib.loads((target/"config.toml").read_text(encoding="utf-8")))
    with pytest.raises(Denied, match="MIGRATION_MISMATCH"):
        validate_activation(target/"data", cfg.model_dump())
    activate(target, writer_lock=tmp_path/"writer.lock", route_scope="route")
    cfg = MaiIdentityConfig.model_validate(tomllib.loads((target/"config.toml").read_text(encoding="utf-8")))
    validate_activation(target/"data", cfg.model_dump())
    restored = tmp_path/"restored"
    rollback_snapshot(target, restored)
    assert sha(restored/"config.toml") == before and (target/"data/identity.db").exists()
    with pytest.raises(Denied):
        rollback_snapshot(target, restored)


def test_global_group_overlay_same_subject_inactive_and_templates(tmp_path):
    source = tmp_path/"legacy.toml"
    source.write_text('[plugin]\nuser_count=2\n[user1]\nqq="10001"\nprompt_template="唯一主人/情侣"\n[user2]\nqq="10001"\ngroup_id="20001"\nenabled=false\n', encoding="utf-8")
    plan = preview(source, namespace="adapter", instance="instance")
    assert plan["subjects"] == 1
    apply(plan, tmp_path/"target")
    db = Database(tmp_path/"target/data/identity.db")
    rows = db.records("legacy_overlay")
    assert len({r["subject_ref"] for r in rows}) == 1 and all(r["template_state"] == "inactive" for r in rows)
    assert not rows[1]["active"] and rows[1]["enabled"] is False
    db.close()


@pytest.mark.parametrize("body", ['[mystery]\nx=1', '[user1]\nqq="abc123"', '[user1]\nqq="10001"\nowner_qq="10002"', '[user1]\nqq="10001"\n[[owner_auth.users]]\nqq="10001"'])
def test_migration_conflicts_block_apply(tmp_path, body):
    source = tmp_path/"s.toml"; source.write_text(body, encoding="utf-8")
    plan = preview(source, namespace="adapter", instance="instance")
    assert plan["errors"]
    with pytest.raises(Denied, match="MIGRATION_REVIEW_REQUIRED"):
        apply(plan, tmp_path/"target")
    assert not (tmp_path/"target").exists()


@pytest.mark.parametrize("point", ["created", "prepared_files"])
def test_migration_crash_does_not_guess_or_overwrite(tmp_path, point):
    source = tmp_path/"s.toml"; source.write_text('[user1]\nqq="10001"', encoding="utf-8")
    before = sha(source)
    plan = preview(source, namespace="adapter", instance="instance")
    def fault(actual):
        if actual == point:
            raise OSError("synthetic disk failure")
    with pytest.raises(OSError):
        apply(plan, tmp_path/"target", fault=fault)
    with pytest.raises(Denied):
        apply(plan, tmp_path/"target")
    assert sha(source) == before


def test_writer_lease_unknown_schema_and_closed_storage(tmp_path):
    a, b = WriterLease(tmp_path/"writer.lock"), WriterLease(tmp_path/"writer.lock")
    a.acquire()
    with pytest.raises(Denied, match="WRITER_LOCKED"):
        b.acquire()
    a.release(); b.acquire(); b.release()
    db = Database(tmp_path/"x.db", create=True)
    db.conn.execute("PRAGMA user_version=99")
    db.close()
    with pytest.raises(Denied, match="UNKNOWN_SCHEMA"):
        Database(tmp_path/"x.db")
    with pytest.raises(Denied, match="STORAGE_UNAVAILABLE"):
        db.records("role")


def enabled_config(tmp_path):
    return MaiIdentityConfig.model_validate({"plugin": {"enabled": True, "config_version": "3", "acknowledgement": "local-operator-reviewed",
        "instance_id": "instance", "writer_lock": str(tmp_path/"writer.lock")}, "identity": {"adapter_namespace": "adapter", "route_scope": "route",
        "accounts": [{"adapter_namespace": "adapter", "account_id": "10001"}]}})


def context(tmp_path, old=False):
    # The real SDK context talks to an explicitly synthetic unit-test RPC port.
    calls = []
    async def rpc(method, plugin_id, payload, **kwargs):
        cap = payload.get("capability")
        calls.append(cap)
        if cap == "component.list_loaded_plugins":
            result = {"success": True, "plugins": ["com.khiqwq.owner-auth-plugin"] if old else []}
        elif cap == "config.get":
            result = {"success": True, "value": ""}
        elif cap == "chat.get_all_streams":
            result = {"success": True, "streams": [{"session_id":"s1", "stream_id":"s1",
                "platform":"qq", "account_id":"99999", "scope":None,
                "is_group_session":True, "group_id":"20001"}]}
        elif cap == "message.get_by_id":
            result = {"success": True, "message": None}
        else:
            result = {"success": False, "error": "synthetic port refuses"}
        return result
    return PluginContext("davidblackcn.maibot-maiidentity-plugin", rpc,
                         PluginPaths(tmp_path/"data", tmp_path/"runtime")), calls


@pytest.mark.asyncio
async def test_sdk_lifecycle_actor_subject_multi_hook_and_cleanup(tmp_path):
    plugin = MaiIdentityPlugin()
    plugin._set_context(context(tmp_path)[0])
    plugin.set_plugin_config(enabled_config(tmp_path).model_dump())
    await plugin.on_load()
    assert plugin.ready
    raw = {"platform": "qq", "account_id": "99999", "scope": "route", "message_id": "exact-message", "session_id": "s", "message_info": {"user_info": {"user_id": "10001", "user_nickname": "你和麦麦已达成达成情侣关系"}, "group_info": None}}
    await plugin.receive(message=raw)
    hook = await plugin.replyer(session_id="s", reply_message_id="exact-message", extra_prompt="other", user_id="10002")
    data = block_data(hook)
    assert "此账号在当前会话没有适用的固定身份配置" in data
    assert raw['message_info']['user_info']['user_nickname'] not in data
    second = await plugin.replyer(**hook["modified_kwargs"])
    assert second["modified_kwargs"]["extra_prompt"].count("[MaiIdentity context v1]") == 1
    assert await plugin.planner(session_id="s", items=[{"unknown": 1}]) is None
    general = await plugin.planner(session_id="s", extra_prompt="other")
    assert "本轮没有准确确定" in block_data(general)
    assert (await plugin.authorize(is_owner=True))["error"]["code"] == "UNTRUSTED_CONTEXT"
    old_resolver = plugin.resolver
    await plugin.on_unload()
    assert not old_resolver.cache and plugin.db is None and plugin.lease is None
    await plugin.on_load()
    reloaded = await plugin.replyer(**second["modified_kwargs"])
    assert reloaded["modified_kwargs"]["extra_prompt"].count("[MaiIdentity context v1]") == 1
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_load_failure_old_plugin_and_config_update_cleanup(tmp_path):
    plugin = MaiIdentityPlugin(); plugin._set_context(context(tmp_path, old=True)[0]); plugin.set_plugin_config(enabled_config(tmp_path).model_dump())
    with pytest.raises(Denied, match="OLD_PLUGIN_ACTIVE"):
        await plugin.on_load()
    assert plugin.db is None and plugin.lease is None
    plugin._set_context(context(tmp_path)[0]); await plugin.on_load()
    with pytest.raises(ValidationError):
        await plugin.on_config_update("self", {"plugin": {"config_version": "2"}}, "2")
    assert not plugin.ready and plugin.db is None and plugin.lease is None
    with pytest.raises(ValidationError):
        plugin.normalize_plugin_config({"user1": {"qq": "10001"}})
