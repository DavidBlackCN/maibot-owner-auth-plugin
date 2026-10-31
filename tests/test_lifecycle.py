import pytest
from maibot_sdk.context import PluginContext, PluginPaths
from pydantic import ValidationError
from maiidentity.host.config import MaiIdentityConfig
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.shared.core import Denied
from .test_context_contract import block_data


def enabled_config(tmp_path):
    return MaiIdentityConfig.model_validate({'identity': {'adapter_namespace': 'adapter', 'route_scope': 'route'}})


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
    assert await plugin.is_admin(is_owner=True) == {"is_admin": False}
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
