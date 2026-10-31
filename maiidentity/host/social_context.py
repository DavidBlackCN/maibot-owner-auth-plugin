"""Neutral group context for Coordinate; fixed profiles are never public inventory."""
from ..shared.core import opaque, require, digest, qq


def public_context(plugin, stream_id, bot_account_id, route_scope):
    require(plugin.ready and plugin.active is not None, 'NOT_READY')
    opaque(stream_id)
    qq(bot_account_id)
    require(route_scope == (plugin.active.identity.route_scope or None), 'SCOPE_MISMATCH')
    facts = {
        'stream_id': stream_id,
        'counts': {'friend': 0, 'family': 0, 'partner': 0},
        'relation_state': 'none_confirmed',
        'completeness': 'public_group_scope_only',
        'style': 'neutral',
        'rule': 'No user relationship registry is provided. Fixed identity profiles are private operator configuration; do not infer relationships or authority from this neutral group context.',
    }
    return {**facts, 'revision': digest(facts)}
