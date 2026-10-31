from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from ..shared.core import AccountKey, Clock, Denied, opaque, require


@dataclass(frozen=True)
class MessageEvidence:
    instance_id: str
    account: AccountKey
    stream_id: str
    message_id: str
    group_id: str | None
    display_name: str

    @property
    def key(self):
        return (self.instance_id, self.account.platform, self.account.adapter_namespace, self.stream_id, self.message_id)

    def same_author(self, other):
        return self.key == other.key and self.account == other.account and self.group_id == other.group_id


def host_message(raw: dict, *, instance: str, namespace: str, bot_account: str, route_scope: str) -> MessageEvidence:
    """Only for the audited Host receive/query serializer, never API payloads."""
    require(type(raw) is dict and bool(bot_account), "IDENTITY_UNRESOLVED")
    info = raw.get("message_info")
    require(type(info) is dict and type(info.get("user_info")) is dict, "IDENTITY_UNRESOLVED")
    user = info["user_info"]
    require(raw.get("platform") == "qq", "UNSUPPORTED")
    require(raw.get("account_id") == bot_account and raw.get("scope") == (opaque(route_scope) if route_scope else None), "SCOPE_MISMATCH")
    require(raw.get("is_bot", False) is False and raw.get("is_system", False) is False
            and raw.get("is_mai_message", False) is False and raw.get("is_notify", False) is False, "IDENTITY_UNRESOLVED")
    account = AccountKey("qq", namespace, user.get("user_id"))
    require(account.account_id != bot_account, "IDENTITY_UNRESOLVED")
    group = info.get("group_info")
    require(group is None or type(group) is dict, "IDENTITY_UNRESOLVED")
    group_id = None
    if group is not None:
        from ..shared.core import qq
        group_id = qq(group.get("group_id"))
    return MessageEvidence(opaque(instance), account, opaque(raw.get("session_id")),
                           opaque(raw.get("message_id")), group_id,
                           user.get("user_cardname") or user.get("user_nickname") or "")



class MessageResolver:
    def __init__(self, clock=None, ttl=300, capacity=2048):
        self.clock, self.ttl, self.capacity = clock or Clock(), ttl, capacity
        self.cache = OrderedDict()

    def purge(self):
        now = self.clock.monotonic()
        for key, (at, _) in list(self.cache.items()):
            if now-at >= self.ttl:
                self.cache.pop(key)
        while len(self.cache) > self.capacity:
            self.cache.popitem(last=False)

    def observe(self, evidence: MessageEvidence):
        self.purge()
        old = self.cache.get(evidence.key)
        value = evidence
        if old and (old[1] is None or not old[1].same_author(evidence)):
            value = None  # Sticky conflict sentinel for the full TTL.
        self.cache[evidence.key] = (self.clock.monotonic(), value)
        self.cache.move_to_end(evidence.key)
        self.purge()

    async def resolve(self, *, instance, platform, namespace, stream, message_id, query, parse):
        try:
            opaque(message_id)
            opaque(stream)
            key = (instance, platform, namespace, stream, message_id)
            self.purge()
            cached = self.cache.get(key)
            if cached and cached[1] is None:
                return None, "MESSAGE_ID_CONFLICT"
            try:
                raw = await query(message_id, stream)
            except Exception:
                raw = None
            if raw is not None:
                try:
                    result = parse(raw)
                    require(result.key == key, "MESSAGE_ID_CONFLICT")
                    require(not cached or result.same_author(cached[1]), "MESSAGE_ID_CONFLICT")
                except (Denied, TypeError, KeyError):
                    self.cache[key] = (self.clock.monotonic(), None)
                    self.purge()
                    return None, "MESSAGE_ID_CONFLICT"
                return result, "message_api"
            return (cached[1], "trusted_cache") if cached else (None, "IDENTITY_UNRESOLVED")
        except (Denied, TypeError):
            return None, "IDENTITY_UNRESOLVED"

    def close(self):
        self.cache.clear()
