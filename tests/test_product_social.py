import json
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.shared.core import AccountKey
from .test_self_service import command
from .test_lifecycle import context

@pytest.mark.asyncio
async def test_public_social_projection_private_filter_scope_and_revocation(tmp_path):
    p=MaiIdentityPlugin();p._set_context(context(tmp_path)[0]);p.set_plugin_config({'plugin':{'config_version':'4'},'identity':{'people':[{'qq':'10001','nickname':'妈妈','prompt_template':'private description'}]}});await p.on_load()
    query={'stream_id':'s1','bot_account_id':'99999','route_scope':None}
    try:
        data=(await p.get_public_social_context(**query))['data']
        assert not any(data['counts'].values()) and data['style']=='neutral'
        assert all(value not in json.dumps(data,ensure_ascii=False) for value in ('10001','妈妈','private description'))
        assert not (await p.get_public_social_context(**{**query,'stream_id':'s2'}))['ok']
        assert not (await p.get_public_social_context(**{**query,'route_scope':'wrong'}))['ok']
        with p.db.transaction():
            p.db.conn.execute('CREATE TABLE historical_records(value TEXT)')
            p.db.conn.execute("INSERT INTO historical_records VALUES ('private partner')")
        assert (await p.get_public_social_context(**query))['data']==data
    finally:await p.on_unload()
