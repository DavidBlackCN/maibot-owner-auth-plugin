"""Official Command admission and public API separation."""
from copy import deepcopy
import pytest
from maiidentity.host.local_command import validate
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.shared.core import Denied,AccountKey
from .test_self_service import command
from .test_migration_lifecycle import context

@pytest.mark.asyncio
async def test_official_entry_without_extension_and_no_api_write(tmp_path):
    p=MaiIdentityPlugin();ctx,calls=context(tmp_path);p._set_context(ctx);p.set_plugin_config({});await p.on_load()
    try:
        c=command('10001','/maiidentity register')
        result=await p.self_command(**c)
        assert p.identity.lookup(AccountKey('qq','host-qq','10001')) is None
        assert '此命令不可用' in result[1]
        assert 'security.resolve_command' not in calls
        assert not p.db.records('grant') and not p.db.records('role')
        before=p.db.conn.total_changes
        assert not (await p.authorize_vita_command(**c,__maibot_command_ref__='fake'))['allowed']
        assert not (await p.authorize(**c,owner=True))['ok']
        assert p.db.conn.total_changes==before
    finally: await p.on_unload()

@pytest.mark.asyncio
async def test_inconsistent_envelope_rejected_before_write(tmp_path):
    p=MaiIdentityPlugin();p._set_context(context(tmp_path)[0]);p.set_plugin_config({});await p.on_load()
    try:
        c=command('10001','/maiidentity register')
        for key,value in [('user_id','10002'),('stream_id','other'),('platform','webui'),
                          ('group_id','20002'),('text','/maiidentity relation revoke fake')]:
            bad={**c,key:value}
            with pytest.raises(Denied): validate(p,bad)
            await p.self_command(**bad)
        for key,value in [('is_bot',True),('is_system',True),('is_mai_message',True),
                          ('is_notify',True),('account_id','88888'),('scope','wrong'),('message_id','')]:
            bad=deepcopy(c);bad['message'][key]=value
            # Route account mismatches are rejected by the async Host lookup.
            if key != 'account_id':
                with pytest.raises(Denied): validate(p,bad)
            await p.self_command(**bad)
        assert p.db.conn.execute('SELECT count(*) FROM bindings').fetchone()[0]==0
        p.ready=False
        with pytest.raises(Denied): validate(p,c)
    finally: await p.on_unload()
