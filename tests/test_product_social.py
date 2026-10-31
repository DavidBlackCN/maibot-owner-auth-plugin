import json
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.shared.core import AccountKey
from .test_self_service import command
from .test_migration_lifecycle import context

@pytest.mark.asyncio
async def test_public_social_projection_private_filter_scope_and_revocation(tmp_path):
    p=MaiIdentityPlugin();p._set_context(context(tmp_path)[0]);p.set_plugin_config({'plugin':{'config_version':'3'},'identity':{'people':[{'qq':'10001','nickname':'妈妈','prompt_template':'private description'}]}});await p.on_load()
    query={'stream_id':'s1','bot_account_id':'99999','route_scope':None}
    try:
        data=(await p.get_public_social_context(**query))['data']
        assert not any(data['counts'].values()) and data['style']=='neutral'
        assert all(value not in json.dumps(data,ensure_ascii=False) for value in ('10001','妈妈','private description'))
        assert not (await p.get_public_social_context(**{**query,'stream_id':'s2'}))['ok']
        assert not (await p.get_public_social_context(**{**query,'route_scope':'wrong'}))['ok']
        with p.db.transaction():
            p.db.put('relation','historical',{'status':'confirmed','visibility':'public','relation_type':'partner'})
        assert (await p.get_public_social_context(**query))['data']==data
    finally:await p.on_unload()

@pytest.mark.asyncio
async def test_life_management_grant_reload_revoke_and_exact_finite_policy(tmp_path):
    p=MaiIdentityPlugin();p._set_context(context(tmp_path)[0]);p.set_plugin_config({'plugin':{'config_version':'3'},'management':{'vita_admin_accounts':['10001']}});await p.on_load()
    q={'account_id':'10001','bot_account_id':'99999','route_scope':None,'stream_id':'s1','action':'manage_goal'}
    try:
        assert (await p.get_vita_policy(**q))['allowed']
        for action in ('start_sleep','start_activity','end_activity','apply_plan_patch'):
            assert (await p.get_vita_policy(**{**q,'action':action}))['allowed']
        assert not (await p.get_vita_policy(**{**q,'action':'configure'}))['allowed']
        key=AccountKey('qq','host-qq','10001');p.identity.revoke(key,expected_epoch=1,key='revoke')
        await p.on_unload();await p.on_load()
        assert p.identity.lookup(key) is None
        assert not (await p.get_vita_policy(**q))['allowed']
    finally:await p.on_unload()
