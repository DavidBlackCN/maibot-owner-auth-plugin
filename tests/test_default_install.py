"""Fresh install exercises the actual null-scope Snowluma message shape."""
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.host.config import MaiIdentityConfig
from maiidentity.identity.messages import host_message
from maiidentity.shared.core import Denied
from .test_lifecycle import context


def message(**changes):
    return dict(platform='qq', account_id='99999', scope=None,
                message_id='m1', session_id='s1',
                message_info={'user_info': {'user_id': '10001', 'user_nickname': 'owner'}}, **changes)


@pytest.mark.asyncio
async def test_default_load_null_scope_reload_lock_and_no_implicit_privileges(tmp_path):
    first=MaiIdentityPlugin(); first._set_context(context(tmp_path)[0]); first.set_plugin_config({})
    await first.on_load()
    try:
        assert first.ready and first.instance_id
        instance=first.instance_id
        evidence=first._parse(message())
        assert evidence.instance_id==instance and evidence.account.account_id=='10001'
        assert not first.active.management.admin_accounts
        assert [r[0] for r in first.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")] == ['metadata']
        await first.on_config_update('self',first.config.model_dump(),2)
        assert first.ready  # Generated defaults don't appear as user config changes.
        second=MaiIdentityPlugin(); second._set_context(context(tmp_path)[0]); second.set_plugin_config({})
        with pytest.raises(Denied,match='WRITER_LOCKED'): await second.on_load()
        assert first.ready
    finally: await first.on_unload()
    await second.on_load()
    try: assert second.instance_id==instance
    finally: await second.on_unload()


@pytest.mark.parametrize('field,value', [('scope','named'),('scope',''),('account_id','88888'),('platform','other'),('is_bot',True)])
def test_null_scope_default_is_not_wildcard(field,value):
    raw=message(); raw[field]=value
    with pytest.raises(Denied):
        host_message(raw,instance='i',namespace='host-qq',bot_account='99999',route_scope='')


def test_explicit_scope_still_exact_and_blank_namespace_rejected():
    with pytest.raises(ValueError):
        MaiIdentityConfig.model_validate({'identity':{'adapter_namespace':''}})
    raw=message(); raw['scope']='named'
    assert host_message(raw,instance='i',namespace='ns',bot_account='99999',route_scope='named').stream_id=='s1'
    raw['scope']=None
    with pytest.raises(Denied,match='SCOPE_MISMATCH'):
        host_message(raw,instance='i',namespace='ns',bot_account='99999',route_scope='named')
