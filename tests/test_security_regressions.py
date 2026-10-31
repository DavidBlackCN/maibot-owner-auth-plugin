from dataclasses import replace
import asyncio
import json
import sqlite3

import pytest

from maiidentity.identity.messages import AliasHistory, MessageResolver, short_alias
from maiidentity.shared.core import AccountKey, Denied
from maiidentity.storage.database import Database
from .conftest import scope
from .test_identity import evidence, resolve


@pytest.mark.asyncio
async def test_real_alias_hash_collision_and_cross_instance_stream_namespace():
    originals = ["synthetic-original-message-11096", "synthetic-original-message-14287"]
    assert short_alias(originals[0]) == short_alias(originals[1]) == "muglcue"
    history = AliasHistory(instance="i", platform="qq", namespace="ns", stream="s", revision="r", originals=originals, complete=True)
    result = await resolve(MessageResolver(), evidence(originals[0]), original="muglcue", id_kind="alias", history=history, history_revision="r")
    assert result[0] is None
    resolver = MessageResolver()
    resolver.observe(evidence())
    for conflicting in (replace(evidence(), instance_id="another"), replace(evidence(), stream_id="other"),
                        replace(evidence(), account=AccountKey("qq", "different", "10001"))):
        assert (await resolve(resolver, conflicting))[0] is None


def test_R04_R05_R06_R08_R09_R10_R15_current_relations_and_projection(domain):
    from maiidentity.context.projection import snapshot
    _, identity, policy, relations, accounts, subjects, _ = domain
    a = policy.actor(accounts[0]); b = policy.actor(accounts[1])
    row = relations.propose(a, subjects[1], "partner", scope(), visibility="public", domain="user_declared", key="partner")
    row = relations.confirm(row["id"], b, expected=1, evidence_ref="trusted-bilateral", key="confirm")
    visible = relations.visible(subjects[0], scope())
    data = snapshot(evidence())
    assert visible['relations'] and data['state'] == 'unlisted'
    # Copying a display name, claims, high closeness and memory summary does not
    # copy the binding or a confirmed relation onto another account.
    other = snapshot(evidence(account="10003"))
    assert other['state'] == 'unlisted'
    assert not policy.authorize(a, "maivita.wake", scope(), request_id="r", external_policy=True)["allowed"]
    relations.revoke(row["id"], a, expected=2, key="revocation")
    assert relations.visible(subjects[0], scope())["relation_state"] == "none_confirmed"
    assert data['state'] == 'unlisted'  # User relationships never enter fixed identity context.
    assert not relations.db.records("social_score")


def test_authorization_evidence_expired_scope_subject_host_denied(domain):
    _, _, policy, _, accounts, subjects, clock = domain
    policy.grant_operator(subjects[0], "identity.self.read", scope(), key="read")
    actor = policy.actor(accounts[0])
    assert policy.authorize(actor, "identity.self.read", scope(), request_id="r", host_allowed=False)["reason_code"] == "HOST_DENIED"
    assert not policy.authorize(actor, "identity.self.read", scope(kind="self", subject=subjects[1]), request_id="r")["allowed"]
    clock.value += 31
    assert policy.authorize(actor, "identity.self.read", scope(), request_id="r")["reason_code"] == "EVIDENCE_EXPIRED"


def test_scope_intersection_combines_independent_subject_and_stream_restrictions():
    from dataclasses import replace
    instance_subject = replace(scope(kind="instance"), subject_id="subject-A")
    combined = instance_subject.intersection(scope())
    assert combined.kind == "self" and combined.subject_id == "subject-A" and combined.stream_id == "stream-A"
    assert instance_subject.contains(combined) and scope().contains(combined)


@pytest.mark.asyncio
async def test_same_sdk_data_root_refuses_even_with_different_deployment_locks(tmp_path):
    from maiidentity.host.plugin import MaiIdentityPlugin
    from .test_migration_lifecycle import context, enabled_config
    from maiidentity.storage.database import WriterLease
    first = MaiIdentityPlugin(); first._set_context(context(tmp_path)[0]); first.set_plugin_config(enabled_config(tmp_path).model_dump())
    second_config = enabled_config(tmp_path).model_dump()
    second_config["plugin"]["writer_lock"] = str(tmp_path/"different.lock")
    second = MaiIdentityPlugin(); second._set_context(context(tmp_path)[0]); second.set_plugin_config(second_config)
    await first.on_load()
    try:
        with pytest.raises(Denied, match="WRITER_LOCKED"):
            await second.on_load()
        assert second.db is None and second.data_lease is None
    finally:
        await first.on_unload()
    lease = WriterLease(tmp_path/"data/writer.lock"); lease.acquire(); lease.release()


def test_migration_source_and_target_modified_blocked(tmp_path):
    from maiidentity.compatibility.migration import apply, preview
    source = tmp_path/"old.toml"; source.write_text('[user1]\nqq="10001"', encoding="utf-8")
    plan = preview(source, namespace="adapter", instance="instance")
    source.write_text('[user1]\nqq="10002"', encoding="utf-8")
    with pytest.raises(Denied, match="SOURCE_CHANGED"):
        apply(plan, tmp_path/"target")
    plan = preview(source, namespace="adapter", instance="instance")
    apply(plan, tmp_path/"target")
    (tmp_path/"target/config.toml").write_text("changed", encoding="utf-8")
    with pytest.raises(Denied, match="TARGET_CHANGED"):
        apply(plan, tmp_path/"target")


@pytest.mark.asyncio
async def test_empty_disabled_no_io_storage_failure_load_cleanup(tmp_path):
    from maiidentity.host.plugin import MaiIdentityPlugin
    from .test_migration_lifecycle import context, enabled_config
    plugin = MaiIdentityPlugin()
    plugin._set_context(context(tmp_path)[0]); plugin.set_plugin_config({'plugin': {'enabled': False, 'config_version': '3'}})
    await plugin.on_load()
    assert not (tmp_path/"data").exists() and not plugin.ready
    assert await plugin.replyer(extra_prompt="x") is None
    data = tmp_path/"data"; data.mkdir()
    (data/"identity.db").write_bytes(b"invalid sqlite")
    plugin.set_plugin_config(enabled_config(tmp_path).model_dump())
    with pytest.raises(sqlite3.DatabaseError):
        await plugin.on_load()
    assert plugin.db is None and plugin.lease is None
    from maiidentity.storage.database import WriterLease
    lease = WriterLease(tmp_path/"writer.lock"); lease.acquire(); lease.release()


def test_strict_boolean_false_not_truthy_and_default_no_privilege():
    from pydantic import ValidationError
    from maiidentity.host.config import MaiIdentityConfig
    with pytest.raises(ValidationError):
        MaiIdentityConfig.model_validate({"plugin": {"enabled": "false"}})
    with pytest.raises(ValidationError):
        MaiIdentityConfig.model_validate({"integrations": {"cross_plugin_privileged_enabled": True}})
    assert not MaiIdentityConfig().identity.accounts and not MaiIdentityConfig().roles.entries
