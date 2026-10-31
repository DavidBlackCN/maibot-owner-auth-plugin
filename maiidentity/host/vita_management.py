"""Read-only config policy. The executing plugin must verify its actual sender."""
from ..shared.core import opaque, require, qq

ACTIONS = frozenset(('wake', 'enqueue_replan', 'start_sleep', 'start_activity',
                     'end_activity', 'apply_plan_patch', 'manage_goal'))


def administrator(plugin, *, account_id, bot_account_id, route_scope, stream_id):
    require(plugin.ready and plugin.active is not None, 'NOT_READY')
    qq(account_id)
    qq(bot_account_id)
    opaque(stream_id)
    require(route_scope == (plugin.active.identity.route_scope or None), 'SCOPE_MISMATCH')
    return account_id != bot_account_id and account_id in plugin.active.management.admin_accounts


def evaluate(plugin, *, action, **kwargs):
    require(type(action) is str and action in ACTIONS, 'UNSUPPORTED_COMMAND')
    return {'policy_version': 1, 'allowed': administrator(plugin, **kwargs)}
