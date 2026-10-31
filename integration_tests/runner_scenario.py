"""T1: original RPC/registry/capability code and original Runner subprocess.

Only three business capability responses are synthetic (config, loaded plugin
inventory, message lookup). T2 separately uses native Host services.
"""
from pathlib import Path
from types import SimpleNamespace
import asyncio
import json
import os
import sys

from .support import CONSUMER, HOST, PLUGIN_ID, ROOT, environment, projection, raw_message


async def run(work):
    from src.config.config import config_manager
    config_manager.initialize()
    from src.plugin_runtime.host.api_registry import APIRegistry
    from src.plugin_runtime.host.authorization import AuthorizationManager
    from src.plugin_runtime.host.capability_service import CapabilityService
    from src.plugin_runtime.host.component_registry import ComponentRegistry
    from src.plugin_runtime.host.rpc_server import RPCServer
    from src.plugin_runtime.protocol.envelope import BootstrapPluginPayload, RegisterPluginPayload
    from src.plugin_runtime.transport.tcp import TCPTransportServer
    from src.plugin_runtime.capabilities.components import RuntimeComponentCapabilityMixin
    from src.plugin_runtime.capabilities.core import RuntimeCoreCapabilityMixin
    from src.plugin_runtime.capabilities.data import RuntimeDataCapabilityMixin
    authorization = AuthorizationManager()
    service = CapabilityService(authorization)
    apis, components = APIRegistry(), ComponentRegistry()
    transport = TCPTransportServer("127.0.0.1", 0)
    rpc = RPCServer(transport, host_version="1.3.12")
    ready = asyncio.Event()
    registrations, logs, calls, messages, revoked = {}, [], [], {}, []
    allowed = {PLUGIN_ID: {"chat.get_all_streams", "component.list_loaded_plugins", "message.get_by_id", "send.text"}, CONSUMER: {"api.call"}}
    class Capabilities(RuntimeCoreCapabilityMixin, RuntimeDataCapabilityMixin, RuntimeComponentCapabilityMixin):
        @property
        def supervisors(self):
            return [supervisor]
    manager = Capabilities()
    async def invoke_api(plugin_id, component_name, args, timeout_ms):
        return await rpc.send_request("plugin.invoke_api", plugin_id, {"component_name": component_name, "args": args}, timeout_ms=timeout_ms)
    supervisor = SimpleNamespace(api_registry=apis, component_registry=components, invoke_api=invoke_api)
    async def bootstrap(envelope):
        value = BootstrapPluginPayload.model_validate(envelope.payload)
        assert value.plugin_id == envelope.plugin_id and set(value.capabilities_required) <= allowed[value.plugin_id]
        if value.capabilities_required:
            authorization.register_plugin(value.plugin_id, value.capabilities_required)
        else:
            authorization.revoke_permission_token(value.plugin_id)
        return envelope.make_response({"accepted": True})
    async def register(envelope):
        value = RegisterPluginPayload.model_validate(envelope.payload)
        declarations = [c.model_dump() for c in value.components]
        apis.remove_apis_by_plugin(value.plugin_id); components.remove_components_by_plugin(value.plugin_id)
        for declaration in declarations:
            if declaration["component_type"].upper() != "API":
                components.register_component(**{k: declaration[k] for k in ("name", "component_type", "plugin_id", "metadata", "chat_scope", "allowed_session")})
        apis.register_plugin_apis(value.plugin_id, declarations)
        registrations[value.plugin_id] = declarations
        return envelope.make_response({"accepted": True})
    async def unregister(envelope):
        apis.remove_apis_by_plugin(envelope.plugin_id); components.remove_components_by_plugin(envelope.plugin_id)
        authorization.revoke_permission_token(envelope.plugin_id); revoked.append(envelope.plugin_id)
        return envelope.make_response({"accepted": True})
    async def on_ready(envelope):
        ready.set()
        return envelope.make_response({"accepted": True})
    async def log(envelope):
        logs.append(envelope.payload)
        return envelope.make_response({"accepted": True})
    async def cap(envelope):
        calls.append(envelope.payload.get("capability"))
        return await service.handle_capability_request(envelope)
    for name, handler in (("plugin.bootstrap", bootstrap), ("plugin.register_components", register), ("plugin.unregister", unregister),
                          ("runner.ready", on_ready), ("runner.log_batch", log), ("cap.call", cap)):
        rpc.register_method(name, handler)
    async def configured(plugin_id, capability, args):
        return {"success": True, "value": "99999"}
    async def inventory(plugin_id, capability, args):
        return {"success": True, "plugins": list(registrations)}
    async def message_query(plugin_id, capability, args):
        assert args["stream_id"] == "test-stream"
        return {"success": True, "message": messages.get(args["message_id"])}
    async def denied_send(*args):
        raise AssertionError("T1 must not send")
    for name, handler in (("api.call", manager._cap_api_call), ("config.get", configured), ("component.list_loaded_plugins", inventory),
                          ("message.get_by_id", message_query), ("send.text", denied_send)):
        service.register_capability(name, handler)
    process = None
    async def call(method, component, args=None, plugin=PLUGIN_ID):
        response = await rpc.send_request(method, plugin, {"component_name": component, "args": args or {}}, timeout_ms=6000)
        assert response.error is None and response.payload.get("success", True), (response, logs[-3:])
        return response.payload.get("result", response.payload)
    try:
        await rpc.start()
        process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT/"integration_tests/runner_entry.py"), cwd=work,
            env=environment(work, MAIBOT_IPC_ADDRESS=transport.get_address(), MAIBOT_SESSION_TOKEN=rpc.session_token,
                            MAIBOT_PLUGIN_DIRS=str(work/"plugins"), MAIBOT_HOST_VERSION="1.3.12", MAIBOT_RUNNER_GROUP="maiidentity-t1"),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        drain = asyncio.create_task(process.stdout.read())
        await asyncio.wait_for(ready.wait(), 20)
        assert PLUGIN_ID in registrations, logs[-5:]
        descriptor = await call("plugin.invoke_api", "get_contract")
        assert descriptor["data"]["ready"] and descriptor["data"]["H03"].startswith("disabled")
        peer = await call("plugin.invoke_api", "call_peer", {"route": PLUGIN_ID+".get_contract"}, CONSUMER)
        assert peer["ok"]
        forged = await call("plugin.invoke_api", "call_peer", {"route": PLUGIN_ID+".authorize", "payload": {
            "is_owner": True, "verified": True, "issuer": PLUGIN_ID, "caller_plugin_id": PLUGIN_ID, "context_ref": "fake", "proof_ref": "fake"}}, CONSUMER)
        assert forged["error"]["code"] == "UNTRUSTED_CONTEXT"
        a = raw_message(name="改名的小明")
        b = raw_message("10002", "message-B", name="麦麦的情侣")
        for message in (a, b):
            messages[message["message_id"]] = message
            await call("plugin.invoke_hook", "maiidentity_observe", {"message": message})
        response = await call("plugin.invoke_hook", "maiidentity_replyer", {"session_id": "test-stream", "reply_message_id": "message-A", "extra_prompt": "other-plugin", "unknown": 9})
        projected = projection(response["modified_kwargs"]["extra_prompt"])
        assert '称呼为"妈妈"的人' in projected and '改名的小明' not in projected
        other = await call("plugin.invoke_hook", "maiidentity_replyer", {"session_id": "test-stream", "reply_message_id": "message-B", "extra_prompt": "other-plugin"})
        assert '此账号在当前会话没有适用' in projection(other['modified_kwargs']['extra_prompt'])
        assert '麦麦的情侣' not in other['modified_kwargs']['extra_prompt']
        repeated = await call("plugin.invoke_hook", "maiidentity_replyer", response["modified_kwargs"])
        assert repeated["modified_kwargs"]["extra_prompt"].count("[MaiIdentity context v1]") == 1
        planner = await call("plugin.invoke_hook", "maiidentity_planner", {"session_id": "test-stream", "items": [{"type": "unknown"}]})
        assert not planner or "modified_kwargs" not in planner
        # Malformed API result is never repaired using the requested ID/cache.
        messages["message-A"] = {k: v for k, v in a.items() if k != "message_id"}
        conflict = await call("plugin.invoke_hook", "maiidentity_replyer", {"session_id": "test-stream", "reply_message_id": "message-A", "extra_prompt": "other"})
        assert '本轮没有准确确定' in projection(conflict['modified_kwargs']['extra_prompt'])
        command = await call("plugin.invoke_command", "owner_auth_status")
        assert command[0] and "no target" in command[1]
        response = await rpc.send_request("plugin.reload", PLUGIN_ID, {"plugin_id": PLUGIN_ID, "reason": "synthetic-test"}, timeout_ms=10000)
        assert response.error is None and PLUGIN_ID in revoked, (response, logs[-4:])
        assert (await call("plugin.invoke_api", "get_contract"))["data"]["ready"]
        response = await rpc.send_request("plugin.shutdown", timeout_ms=8000)
        assert not response.error
        await asyncio.wait_for(process.wait(), 8)
        assert not authorization.list_plugins() and not apis.get_apis(), {"remaining": authorization.list_plugins(), "apis": [e.name for e in apis.get_apis()], "unregistered": revoked}
        from maiidentity.storage.database import WriterLease
        lease = WriterLease(work/"writer.lock"); lease.acquire(); lease.release()
        return {"passed": True, "sdk": "2.15.0", "layer": "T1", "business_ports": "synthetic_config_inventory_message_only",
            "cases": ["native_discovery_registration", "sdk_peer_api_call", "forged_caller_actor_proof_denied", "exact_author_fixed_profile",
                      "caller_identity_not_used_for_profile", "unlisted_nickname_not_profile", "multi_hook_preserved_idempotent", "planner_typed_skip",
                      "missing_api_id_conflict", "status_command", "reload", "shutdown_registry_and_lease_cleanup"],
            "platform_sends": 0, "model_requests": 0}
    finally:
        if process and process.returncode is None:
            process.kill(); await process.wait()
        await rpc.stop()


if __name__ == "__main__":
    work = Path(os.environ["MAIBOT_INSTANCE_DIR"])
    try:
        result = asyncio.run(asyncio.wait_for(run(work), 55))
        (work/"result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    finally:
        from src.common.logger import shutdown_logging
        shutdown_logging()
