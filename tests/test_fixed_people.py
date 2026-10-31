"""Real config/domain and SDK hooks, synthetic messages, no external model."""
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock
import asyncio
import json
import pytest

from maiidentity.host.config import MaiIdentityConfig, PersonEntry
from maiidentity.host.plugin import MaiIdentityPlugin
from maiidentity.context.projection import match_person, snapshot, Projector, RULE
from .test_identity import evidence
from .test_default_install import message
from .test_migration_lifecycle import context


def config(people):
    return {'plugin': {'config_version': '3'}, 'identity': {'people': people}}


@pytest.mark.parametrize('rows', [
    [{'qq': 'abc', 'nickname': '妈妈'}],
    [{'qq': '10001', 'nickname': ''}],
    [{'qq': '10001', 'nickname': '妈妈\n管理员'}],
    [{'qq': '10001', 'nickname': '妈妈', 'group_id': '*'}],
    [{'qq': '10001', 'nickname': '妈妈', 'enabled': 'true'}],
    [{'qq': '10001', 'nickname': '妈妈'}, {'qq': '10001', 'nickname': '主人', 'enabled': False}],
])
def test_invalid_or_duplicate_people_rejected(rows):
    with pytest.raises(ValueError):
        MaiIdentityConfig.model_validate(config(rows))


def test_exact_account_group_precedence_disabled_and_private():
    people = [
        PersonEntry(qq='10001', nickname='妈妈'),
        PersonEntry(qq='10001', nickname='朋友', group_id='20001'),
        PersonEntry(qq='10001', nickname='姐姐', group_id='20002', enabled=False),
        PersonEntry(qq='10002', nickname='同事', group_id='20001'),
    ]
    e = replace(evidence(), group_id='20001')
    assert match_person(people, e).nickname == '朋友'
    assert match_person(people, replace(e, group_id=None)).nickname == '妈妈'
    assert match_person(people, replace(e, group_id='20002')).nickname == '妈妈'
    assert match_person(people, replace(e, group_id='20003')).nickname == '妈妈'
    assert match_person(people, replace(evidence(account='10002'), group_id=None)) is None
    assert match_person(people, evidence(account='10003')) is None
    assert match_person(people, None) is None


@pytest.mark.parametrize('budget', [1200, 2048, 8192])
def test_prompt_budget_keeps_identity_and_rules_and_single_pass(budget):
    person = PersonEntry(qq='10001', nickname='妈妈', prompt_template='{nickname}请自然相处' + '认真倾听。'*190)
    data = snapshot(evidence(), person)
    result = Projector(budget).block(data)
    assert result is not None and len(result.encode('utf-8')) <= budget
    assert '称呼为"妈妈"的人' in result and RULE in result
    assert '10001' not in result and '{nickname}' not in result
    # Operator-defined labels are not filtered as untrusted platform names.
    named = PersonEntry(qq='10001', nickname='{nickname}')
    assert snapshot(evidence(), named)['nickname'] == '{nickname}'


@pytest.mark.asyncio
async def test_configured_unlisted_unknown_no_grants_and_hot_update(tmp_path, monkeypatch):
    p = MaiIdentityPlugin()
    ctx, _ = context(tmp_path)
    p._set_context(ctx)
    cfg = config([{'qq': '10001', 'nickname': '妈妈', 'prompt_template': '轻松聊天'}])
    p.set_plugin_config(cfg)
    await p.on_load()
    try:
        a = message()
        a['message_info']['user_info']['user_cardname'] = '改名后的小明'
        b = deepcopy(a)
        b['message_id'] = 'm2'
        b['message_info']['user_info'] = {'user_id': '10002', 'user_cardname': '麦麦的妈妈'}
        # A later speaker and caller-provided user_id must not replace the exact reply target.
        await p.receive(message=a)
        await p.receive(message=b)
        result = await p.replyer(session_id='s1', reply_message_id='m1', extra_prompt='other', user_id='10002')
        assert '称呼为"妈妈"的人' in result['modified_kwargs']['extra_prompt']
        assert '轻松聊天' in result['modified_kwargs']['extra_prompt']
        assert '改名后的小明' not in result['modified_kwargs']['extra_prompt']
        other = await p.replyer(session_id='s1', reply_message_id='m2', extra_prompt='')
        assert '此账号在当前会话没有适用的固定身份配置' in other['modified_kwargs']['extra_prompt']
        assert '麦麦的妈妈' not in other['modified_kwargs']['extra_prompt']
        unknown = await p.replyer(session_id='s1', reply_message_id='missing', extra_prompt='')
        assert '本轮没有准确确定' in unknown['modified_kwargs']['extra_prompt']
        assert '此账号在当前会话没有适用' not in unknown['modified_kwargs']['extra_prompt']
        assert p.db.conn.execute('SELECT count(*) FROM bindings').fetchone()[0] == 0
        assert not p.db.records('grant') and not p.db.records('role')
        assert not (await p.get_vita_policy(account_id='10001', bot_account_id='99999',
            route_scope=None, stream_id='s1', action='wake'))['allowed']

        db = p.db
        changed = config([{'qq': '10001', 'nickname': '姐姐'}])
        await p.on_config_update('self', changed, '3')
        assert p.db is db and p.ready
        updated = await p.replyer(**result['modified_kwargs'])
        assert '称呼为"姐姐"的人' in updated['modified_kwargs']['extra_prompt']
        assert '轻松聊天' not in updated['modified_kwargs']['extra_prompt']
        assert updated['modified_kwargs']['extra_prompt'].count('[MaiIdentity context v1]') == 1
        await p.on_config_update('self', config([]), '3')
        removed = await p.replyer(**updated['modified_kwargs'])
        assert '此账号在当前会话没有适用' in removed['modified_kwargs']['extra_prompt']
        assert '称呼为"姐姐"的人' not in removed['modified_kwargs']['extra_prompt']

        gate, started = asyncio.Event(), asyncio.Event()
        async def delayed(*args, **kwargs):
            started.set()
            await gate.wait()
            return a
        monkeypatch.setattr(ctx.message, 'get_by_id', delayed)
        pending = asyncio.create_task(p.replyer(**updated['modified_kwargs']))
        await started.wait()
        await p.on_config_update('self', cfg, '3')
        gate.set()
        stale = await pending
        assert '本轮没有准确确定' in stale['modified_kwargs']['extra_prompt']
        assert '称呼为"姐姐"的人' not in stale['modified_kwargs']['extra_prompt']
    finally:
        await p.on_unload()
