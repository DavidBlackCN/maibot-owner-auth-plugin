"""T2 basic isolated Host runtime: real Supervisor, services, DB and dispatcher.

Does not start the full bot CLI, WebUI, adapter or model scheduler. No Host
module is replaced and no fake capability implementation is registered.
"""
from datetime import datetime
from pathlib import Path
import asyncio
import json
import os
import sys
import shutil
import tomlkit

from .support import CONSUMER, PLUGIN_ID, projection


async def run(work):
    from src.config.config import config_manager
    config_manager.initialize()
    cfg = config_manager.get_global_config()
    cfg.bot.qq_account = "99999"
    cfg.bot.platform = "qq"
    cfg.telemetry.enable = False
    cfg.maim_message.enabled = False
    from src.common.database.database import initialize_database, get_db_session, engine
    initialize_database()
    from src.plugin_runtime.integration import PluginRuntimeManager
    from src.plugin_runtime.host.supervisor import PluginSupervisor
    from src.plugin_runtime.hook_payloads import serialize_session_message
    from src.chat.message_receive.message import SessionMessage
    from src.common.data_models.mai_message_data_model import MessageInfo, UserInfo
    from src.common.data_models.message_component_data_model import MessageSequence, TextComponent
    from src.services.message_service import get_message_by_id
    from maiidentity.storage.database import Database, WriterLease
    from maiidentity.identity.service import IdentityService
    from maiidentity.shared.core import AccountKey, Denied
    manager = PluginRuntimeManager()
    manager.ensure_builtin_hook_specs_registered()
    supervisor = PluginSupervisor(plugin_dirs=[work/"plugins"], group_name="maiidentity-test", hook_spec_registry=manager._hook_spec_registry,
                                  max_restart_attempts=0, health_check_interval_sec=300, runner_spawn_timeout_sec=20)
    manager._third_party_supervisor = supervisor
    manager._register_capability_impls(supervisor)
    report = {"layer": "T2", "scope": "basic_native_Host_runtime", "full_bot_cli": "not_started", "module_replacements": 0,
              "platform_sends": 0, "model_requests": 0, "cases": []}
    async def call(component, args=None, plugin=PLUGIN_ID):
        response = await supervisor.invoke_api(plugin, component, args=args or {}, timeout_ms=6000)
        assert response.error is None and response.payload.get("success"), response
        return response.payload["result"]
    try:
        config_path = work/"plugins/candidate/config.toml"
        enabled_bytes = config_path.read_bytes()
        disabled = tomlkit.parse(enabled_bytes.decode("utf-8"))
        disabled["plugin"]["enabled"] = False
        config_path.write_text(tomlkit.dumps(disabled), encoding="utf-8")
        await supervisor.start()
        assert not supervisor.api_registry.get_apis(plugin_id=PLUGIN_ID)
        assert not (work/"data/plugins"/PLUGIN_ID/"identity.db").exists()
        config_path.write_bytes(enabled_bytes)
        assert await supervisor.reload_plugins([PLUGIN_ID], reason="explicit-synthetic-enable")
        report["cases"].append("native_disabled_discovery_without_identity_data_then_explicit_enable")
        status = await call("get_contract")
        assert status["data"]["ready"] and PLUGIN_ID in supervisor._registered_plugins
        assert len([h for h in supervisor.component_registry.get_hook_handlers("maisaka.replyer.before_request") if h.plugin_id == PLUGIN_ID]) == 1
        report["cases"].append("native_supervisor_discovery_and_registration")
        assert (await call("call_peer", {"route": PLUGIN_ID+".get_contract"}, CONSUMER))["ok"]
        denied = await call("call_peer", {"route": PLUGIN_ID+".authorize", "payload": {
            "context_ref": "fake", "proof_ref": "fake", "is_owner": True, "caller_plugin_id": PLUGIN_ID}}, CONSUMER)
        assert denied["error"]["code"] == "UNTRUSTED_CONTEXT"
        report["cases"].append("native_cross_plugin_API_public_and_forgery_denial")
        messages = []
        for account, mid, name in (("10001", "native-A", "改名的小明"), ("10002", "native-B", "麦麦的妈妈")):
            message = SessionMessage(message_id=mid, timestamp=datetime.now(), platform="qq")
            message.message_info = MessageInfo(user_info=UserInfo(account, name), group_info=None)
            message.session_id = "test-stream"
            message.account_id = "99999"
            message.scope = "route"
            message.raw_message = MessageSequence([TextComponent("synthetic hello")])
            message.processed_plain_text = "synthetic hello"
            with get_db_session() as session:
                session.add(message.to_db_instance())
            messages.append(message)
            hook = await manager.invoke_hook("chat.receive.after_process", message=serialize_session_message(message))
            assert not hook.aborted and not hook.errors, hook
        assert get_message_by_id("native-A", "test-stream").message_info.user_info.user_id == "10001"
        first = await manager.invoke_hook("maisaka.replyer.before_request", session_id="test-stream", reply_message_id="native-A", extra_prompt="other-plugin", unknown=7)
        assert not first.aborted and not first.errors, first
        a = projection(first.kwargs["extra_prompt"])
        assert '称呼为"妈妈"的人' in a and '自然亲近' in a and '改名的小明' not in a
        b = await manager.invoke_hook("maisaka.replyer.before_request", session_id="test-stream", reply_message_id="native-B", extra_prompt="other-plugin")
        assert '此账号在当前会话没有适用的固定身份配置' in projection(b.kwargs['extra_prompt'])
        assert '麦麦的妈妈' not in projection(b.kwargs['extra_prompt'])
        repeat = await manager.invoke_hook("maisaka.replyer.before_request", **{k: v for k, v in first.kwargs.items() if k != "hook_name"})
        assert repeat.kwargs["extra_prompt"].count("[MaiIdentity context v1]") == 1 and "other-plugin" in repeat.kwargs["extra_prompt"] and repeat.kwargs["unknown"] == 7
        assert repeat.kwargs["extra_prompt"].count("[Synthetic other context]") == 1
        planner = await manager.invoke_hook("maisaka.planner.before_request", session_id="test-stream", items=[{"type": "unknown"}])
        assert not planner.aborted and "extra_prompt" not in planner.kwargs
        report["cases"].extend(["native_message_DB_query_and_serializer", "exact_A_B_fixed_profile_and_unlisted", "nickname_claim_does_not_define_identity",
                               "multi_hook_context_preservation_and_idempotence", "planner_typed_items_unchanged"])
        lock = WriterLease(work/"writer.lock")
        try:
            lock.acquire()
        except Denied:
            pass
        else:
            lock.release(); raise AssertionError("native loaded writer lease not held")
        assert await supervisor.reload_plugins([PLUGIN_ID], reason="isolated-test")
        assert (await call("get_contract"))["data"]["ready"]
        across_reload = await manager.invoke_hook("maisaka.replyer.before_request", **{k: v for k, v in first.kwargs.items() if k != "hook_name"})
        assert across_reload.kwargs["extra_prompt"].count("[MaiIdentity context v1]") == 1
        assert len([h for h in supervisor.component_registry.get_hook_handlers("maisaka.replyer.before_request") if h.plugin_id == PLUGIN_ID]) == 1
        report["cases"].append("native_reload_single_handler_and_writer_lease")
        unloaded = await supervisor.unload_plugins([PLUGIN_ID], reason="offline-revocation-test")
        assert unloaded.success
        lock.acquire(); lock.release()
        db = Database(work/"data/plugins"/PLUGIN_ID/"identity.db")
        identity = IdentityService(db)
        identity.revoke(AccountKey("qq", "adapter", "10001"), expected_epoch=1, key="synthetic-offline-revoke")
        db.close()
        assert await supervisor.reload_plugins([PLUGIN_ID], reason="offline-revocation-reload")
        after = await manager.invoke_hook("maisaka.replyer.before_request", **{k: v for k, v in first.kwargs.items() if k != "hook_name"})
        assert '称呼为"妈妈"的人' in projection(after.kwargs['extra_prompt'])
        db = Database(work/"data/plugins"/PLUGIN_ID/"identity.db")
        assert IdentityService(db).lookup(AccountKey('qq', 'adapter', '10001')) is None
        db.close()
        assert after.kwargs["extra_prompt"].count("[MaiIdentity context v1]") == 1
        report["cases"].append("account_revocation_persists_and_does_not_change_fixed_profile")
        changed = tomlkit.parse(config_path.read_text(encoding='utf-8'))
        changed['identity']['people'][0]['nickname'] = '姐姐'
        config_path.write_text(tomlkit.dumps(changed), encoding='utf-8')
        assert await supervisor.reload_plugins([PLUGIN_ID], reason='fixed-profile-edit')
        edited = await manager.invoke_hook('maisaka.replyer.before_request', **{k:v for k,v in first.kwargs.items() if k!='hook_name'})
        assert '称呼为"姐姐"的人' in projection(edited.kwargs['extra_prompt'])
        assert '称呼为"妈妈"的人' not in edited.kwargs['extra_prompt']
        changed['identity']['people'] = []
        config_path.write_text(tomlkit.dumps(changed), encoding='utf-8')
        assert await supervisor.reload_plugins([PLUGIN_ID], reason='fixed-profile-remove')
        removed = await manager.invoke_hook('maisaka.replyer.before_request', **{k:v for k,v in edited.kwargs.items() if k!='hook_name'})
        assert '此账号在当前会话没有适用' in projection(removed.kwargs['extra_prompt'])
        report['cases'].append('native_config_edit_and_remove_replace_context_after_reload')
        response = await supervisor.invoke_plugin("plugin.invoke_command", PLUGIN_ID, "owner_auth_status", args={}, timeout_ms=3000)
        assert response.payload["result"][0] is True
        report["cases"].append("native_registered_status_command_no_send")
        # An invalid own store must fail the genuine load path and release the
        # lease. Preserve a verified snapshot and restore it only while stopped.
        assert (await supervisor.unload_plugins([PLUGIN_ID], reason="synthetic-storage-fault")).success
        store = work/"data/plugins"/PLUGIN_ID/"identity.db"
        snapshot = work/"identity-offline-snapshot.db"
        shutil.copyfile(store, snapshot)
        store.write_bytes(b"synthetic-invalid-sqlite")
        assert not await supervisor.reload_plugins([PLUGIN_ID], reason="synthetic-storage-fault")
        assert not supervisor.api_registry.get_apis(plugin_id=PLUGIN_ID)
        lock.acquire(); lock.release()
        shutil.copyfile(snapshot, store)
        assert await supervisor.reload_plugins([PLUGIN_ID], reason="restore-synthetic-snapshot")
        assert (await call("get_contract"))["data"]["ready"]
        report["cases"].append("native_storage_failure_denies_load_and_releases_lease")
    finally:
        await supervisor.stop()
        engine.dispose()
    lock = WriterLease(work/"writer.lock"); lock.acquire(); lock.release()
    assert not supervisor.authorization_manager.list_plugins() and not supervisor.api_registry.get_apis()
    report["cases"].append("native_shutdown_registry_and_lock_cleanup")
    report["passed"] = True
    return report


if __name__ == "__main__":
    try:
        result = asyncio.run(asyncio.wait_for(run(Path(os.environ["MAIBOT_INSTANCE_DIR"])), 55))
        (Path(os.environ["MAIBOT_INSTANCE_DIR"])/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        from src.common.logger import shutdown_logging
        shutdown_logging()
