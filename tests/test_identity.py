from dataclasses import replace
import pytest
from maiidentity.identity.messages import MessageEvidence, MessageResolver, host_message
from maiidentity.shared.core import AccountKey, Denied, qq
from .conftest import FakeClock


@pytest.mark.parametrize("value", ["abc123", " 123", "123 ", "１２３", "0", "00123", "-123", "1.0", 123, True, None, "1\n"])
def test_strict_qq(value):
    with pytest.raises(Denied):
        qq(value)


def evidence(mid="long-original-message-id", account="10001", stream="s"):
    return MessageEvidence("i", AccountKey("qq", "ns", account), stream, mid, None, "ordinary")


async def resolve(resolver, value=None, original=None, **kw):
    async def query(mid, stream):
        if isinstance(value, Exception):
            raise value
        return value
    return await resolver.resolve(instance="i", platform="qq", namespace="ns", stream="s", message_id=original or "long-original-message-id",
                                  query=query, parse=lambda raw: raw, **kw)


@pytest.mark.asyncio
async def test_exact_api_cache_conflicts_missing_ids_and_ttl():
    clock = FakeClock()
    resolver = MessageResolver(clock, ttl=300, capacity=2)
    a = evidence()
    resolver.observe(a)
    assert (await resolve(resolver, RuntimeError()))[0] == a
    assert (await resolve(resolver, evidence(account="10002")))[0] is None
    assert (await resolve(resolver, a))[0] is None
    clock.value += 301
    assert (await resolve(resolver))[0] is None
    assert (await resolve(resolver, a))[0] == a
    assert (await resolve(resolver, replace(a, message_id="")))[0] is None
    assert (await resolve(resolver, replace(a, stream_id="other")))[0] is None
    resolver.observe(evidence("1")); resolver.observe(evidence("2")); resolver.observe(evidence("3"))
    assert len(resolver.cache) == 2
    resolver.close()
    assert not resolver.cache


def test_host_message_missing_fields_bot_system():
    raw = {"platform": "qq", "account_id": "99999", "scope": "route", "session_id": "s", "message_id": "m", "message_info": {"user_info": {"user_id": "10001"}, "group_info": None}}
    parse = lambda value, bot="99999": host_message(value, instance="i", namespace="ns", bot_account=bot, route_scope="route")
    assert parse(raw).account.account_id == "10001"
    for name in ("platform", "session_id", "message_id", "message_info", "account_id", "scope"):
        with pytest.raises(Denied):
            parse({k: v for k, v in raw.items() if k != name})
    for name in ("is_bot", "is_system", "is_mai_message"):
        with pytest.raises(Denied):
            parse(raw | {name: True})
    for bot in ("", "10001"):
        with pytest.raises(Denied):
            parse(raw, bot)
