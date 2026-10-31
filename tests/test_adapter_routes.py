"""Regression for adapter identity with an empty/stale global fallback."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.host.routes import command_route
from maiidentity.shared.core import AccountKey
from .test_self_service import command
from .test_lifecycle import context


def route(bot='99999', stream='s1'):
    return dict(session_id=stream,stream_id=stream,platform='qq',account_id=bot,
        scope=None,is_group_session=True,group_id='20001')


@pytest.mark.asyncio
async def test_empty_fallback_registration_denials_receipts_and_route_isolation(tmp_path,monkeypatch):
    p=MaiIdentityPlugin();ctx,calls=context(tmp_path);p._set_context(ctx);p.set_plugin_config({})
    await p.on_load()
    send=AsyncMock(return_value=True)
    monkeypatch.setattr(ctx.send,'text',send)
    try:
        await p.self_command(**command('10001','/maiidentity register'))
        assert not p.active.management.admin_accounts
        assert '此命令不可用' in send.call_args.args[0]
        assert send.await_count==1 and send.call_args.args[1]=='s1'
        assert 'config.get' not in calls
        for update in ({'user_id':'10002'},{'platform':'webui'}):
            await p.self_command(**{**command('10003','/maiidentity register'),**update})
            assert 'UNTRUSTED_CONTEXT' in send.call_args.args[0]
        c=command('99999','/maiidentity register')
        await p.self_command(**c)
        assert 'IDENTITY_UNRESOLVED' in send.call_args.args[0]
        before=send.await_count
        for field,value in [('account_id','88888'),('scope','other'),('session_id','other')]:
            c=command('10003','/maiidentity register');c['message'][field]=value
            await p.self_command(**c)
        assert send.await_count==before
        assert not p.active.management.admin_accounts
        send.return_value=False
        result=await p.self_command(**command('99999','/maiidentity register'))
        assert 'normal send denied' in result[1] and send.await_count==before+1
        assert not p.active.management.admin_accounts
    finally:await p.on_unload()


@pytest.mark.asyncio
async def test_validation_failure_and_reload_have_visible_safe_receipts(tmp_path,monkeypatch):
    p=MaiIdentityPlugin();ctx,_=context(tmp_path);p._set_context(ctx);p.set_plugin_config({});await p.on_load()
    send=AsyncMock(return_value=True);monkeypatch.setattr(ctx.send,'text',send)
    try:
        from maiidentity.host import local_command
        def fail(*a):raise OSError('secret database path')
        with monkeypatch.context() as patch:
            patch.setattr(local_command,'validate',fail)
            await p.self_command(**command('10001','/maiidentity register'))
            assert '操作未确认' in send.call_args.args[0] and 'secret' not in send.call_args.args[0]
        async def reload(**kw):
            p.active=p.active.model_copy(deep=True)
            return [route()]
        monkeypatch.setattr(ctx.chat,'get_all_streams',reload)
        await p.self_command(**command('10001','/maiidentity register'))
        assert 'NOT_READY' in send.call_args.args[0]
    finally:await p.on_unload()


@pytest.mark.asyncio
async def test_routes_are_exact_private_aware_and_cancel_safe():
    ctx=SimpleNamespace(chat=SimpleNamespace(get_all_streams=AsyncMock(return_value=[route()])))
    c=command('10001','/maiidentity register')
    for rows in ([],[route(),route()],{},[dict(route(),account_id='')],
                 [dict(route(),group_id='other')],[dict(route(),scope='wrong')]):
        ctx.chat.get_all_streams.return_value=rows
        with pytest.raises(ValueError):await command_route(ctx,c)
    private=dict(route(),is_group_session=False,group_id=None,user_id='10001')
    c['message']['message_info']['group_info']=None;c['group_id']=''
    ctx.chat.get_all_streams.return_value=[private]
    assert (await command_route(ctx,c))['account_id']=='99999'
    private['user_id']='10002'
    with pytest.raises(ValueError):await command_route(ctx,c)
    ctx.chat.get_all_streams.side_effect=asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):await command_route(ctx,c)


@pytest.mark.asyncio
async def test_multiple_adapter_accounts_public_policy_never_uses_fallback(tmp_path,monkeypatch):
    p=MaiIdentityPlugin();ctx,_=context(tmp_path);p._set_context(ctx)
    p.set_plugin_config({'plugin':{'config_version':'4'},'management':{'admin_accounts':['10001']}});await p.on_load()
    monkeypatch.setattr(ctx.chat,'get_all_streams',AsyncMock(return_value=[route(),route('88888','s2')]))
    try:
        q=dict(account_id='10001',bot_account_id='88888',route_scope=None,stream_id='s2',action='manage_goal')
        assert (await p.get_vita_policy(**q))['allowed']
        for change in ({'bot_account_id':'99999'},{'stream_id':'unknown'},{'account_id':'10002'},{'account_id':'88888'}):
            assert not (await p.get_vita_policy(**{**q,**change}))['allowed']
        assert not (await p.get_public_social_context(stream_id='s2',bot_account_id='99999',route_scope=None))['ok']
    finally:await p.on_unload()
