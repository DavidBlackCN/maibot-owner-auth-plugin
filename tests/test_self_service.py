"""Removed registration/relation commands cannot change identity or policy."""
import uuid
import pytest
from maiidentity.host.plugin import MaiIdentityPlugin
from .test_migration_lifecycle import context


def command(user, text, stream='s1', scope=None):
    return {'text': text, 'user_id': user, 'stream_id': stream, 'platform': 'qq', 'group_id': '20001', 'message': {
        'processed_plain_text': text, 'platform': 'qq', 'account_id': '99999', 'scope': scope,
        'message_id': uuid.uuid4().hex, 'session_id': stream,
        'message_info': {'user_info': {'user_id': user}, 'group_info': {'group_id': '20001'}}}}


@pytest.mark.asyncio
async def test_removed_commands_have_no_writes(tmp_path):
    p = MaiIdentityPlugin()
    p._set_context(context(tmp_path)[0])
    p.set_plugin_config({})
    await p.on_load()
    try:
        before = p.db.conn.total_changes
        for text in ('register', '登记我', 'relation propose 10002 friend', '建立关系 10002 朋友',
                     'relation confirm fake', '确认关系 fake', '撤销关系 fake', 'relations', '查看关系'):
            result = await p.self_command(**command('10001', '/maiidentity ' + text))
            assert '此命令不可用' in result[1]
        assert p.db.conn.total_changes == before
        assert p.db.conn.execute('SELECT count(*) FROM bindings').fetchone()[0] == 0
    finally:
        await p.on_unload()
