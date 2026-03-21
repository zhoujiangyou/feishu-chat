# AI GC START
from __future__ import annotations

from fnmatch import fnmatch

from app.agent.types import PermissionRule


class PermissionEngine:
    def evaluate(
        self,
        *,
        permission: str,
        pattern: str,
        rulesets: list[list[PermissionRule]],
    ) -> PermissionRule:
        flattened = [rule for ruleset in rulesets for rule in ruleset]
        for rule in reversed(flattened):
            if fnmatch(permission, rule.permission) and fnmatch(pattern, rule.pattern):
                return rule
        return PermissionRule(permission=permission, pattern="*", action="ask")
# AI GC END
