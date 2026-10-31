import asyncio
from unittest.mock import AsyncMock
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.host.vita_management import ACTIONS
from .test_lifecycle import context

QUERY = dict(account_id='10001', bot_account_id='99999', route_scope=None, stream_id='s1')


@pytest.mark.asyncio
async def test_config_is_only_authority_read_only_actions_hot_removal_and_restart(tmp_path):
    p=MaiIdentityPlugin(); p._set_context(context(tmp_path)[0])
    cfg={'plugin':{'config_version':'4'}, 'management': {'admin_accounts': ['10001']}, 'identity': {'people': [{'qq': '10002', 'nickname': '妈妈'}]}}
    p.set_plugin_config(cfg); await p.on_load()
    try:
        before=p.db.conn.total_changes
        assert await p.is_admin(**QUERY)=={'is_admin': True}
        for action in ACTIONS:
            assert await p.get_vita_policy(**QUERY,action=action)=={'policy_version':1,'allowed':True}
        for change in ({'account_id':'10002'}, {'account_id':'99999'}, {'bot_account_id':'88888'},
                       {'route_scope':'wrong'}, {'stream_id':'missing'}, {'account_id': True}):
            assert not (await p.is_admin(**{**QUERY,**change}))['is_admin']
            assert not (await p.get_vita_policy(**{**QUERY,**change},action='wake'))['allowed']
        for action in ('configure', 'delegate', 'maihush.mute', '', None, []):
            assert not (await p.get_vita_policy(**QUERY,action=action))['allowed']
        assert not (await p.is_admin(**QUERY,owner=True))['is_admin']
        assert not (await p.get_vita_policy(**QUERY,action='wake',verified=True))['allowed']
        assert p.db.conn.total_changes==before
        db=p.db
        p.set_plugin_config({})
        await p.on_config_update('self',p.get_plugin_config_data(),'4')
        assert p.ready and p.db is db
        assert not (await p.is_admin(**QUERY))['is_admin']
        assert not (await p.get_vita_policy(**QUERY,action='wake'))['allowed']
        await p.on_unload(); await p.on_load()
        assert not (await p.is_admin(**QUERY))['is_admin']
    finally: await p.on_unload()


@pytest.mark.asyncio
@pytest.mark.parametrize('method', ['is_admin', 'get_vita_policy'])
async def test_inflight_route_read_cannot_use_revoked_config(tmp_path,monkeypatch,method):
    p=MaiIdentityPlugin(); ctx,_=context(tmp_path); p._set_context(ctx)
    p.set_plugin_config({'plugin':{'config_version':'4'}, 'management': {'admin_accounts':['10001']}}); await p.on_load()
    started,gate=asyncio.Event(),asyncio.Event()
    original=ctx.chat.get_all_streams
    async def delayed(**kw):
        started.set(); await gate.wait(); return await original(**kw)
    monkeypatch.setattr(ctx.chat,'get_all_streams',delayed)
    try:
        args=QUERY if method=='is_admin' else dict(QUERY,action='wake')
        task=asyncio.create_task(getattr(p,method)(**args)); await started.wait()
        await p.on_config_update('self',{},'4'); gate.set()
        assert not any(v is True for v in (await task).values())
        monkeypatch.setattr(ctx.chat,'get_all_streams',AsyncMock(side_effect=OSError('private path')))
        assert not any(v is True for v in (await getattr(p,method)(**args)).values())
    finally: await p.on_unload()
