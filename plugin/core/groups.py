"""Resolve immutable per-group overrides without changing shared settings."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from .endpoints import ServiceTier
from .settings import PluginSettings

PUSH_FIELDS = {2001: "server_enabled", 2002: "news_enabled", 2003: "version_enabled"}
MAX_GROUPS = 200


def group_umo(value: Any) -> str:
    """Accept only a canonical group origin, never a per-member session."""
    if not isinstance(value, str) or len(value) > 512:
        return ""
    parts = value.strip().split(":")
    if len(parts) != 3 or parts[1] != "GroupMessage":
        return ""
    if any(
        not part
        or any(c.isspace() or ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in part)
        for part in parts
    ):
        return ""
    return ":".join(parts)


def event_group_umo(event: Any) -> str:
    """Use the actual group ID even when AstrBot isolates member sessions."""
    get_group = getattr(event, "get_group_id", None)
    get_platform = getattr(event, "get_platform_id", None)
    if callable(get_group) and callable(get_platform):
        group_id = get_group()
        if group_id:
            return group_umo(f"{get_platform()}:GroupMessage:{group_id}")
        return ""
    return group_umo(getattr(event, "unified_msg_origin", ""))


def _override(value: Any, default: bool) -> bool:
    if value == "开启":
        return True
    if value == "关闭":
        return False
    return default


@dataclass(frozen=True, slots=True)
class GroupPolicy:
    """Effective query settings and explicitly authorized push types."""

    umo: str
    settings: PluginSettings
    actions: frozenset[int]


class GroupPolicies:
    """Build one bounded group index at initialization."""

    def __init__(self, config: Mapping[str, Any], defaults: PluginSettings) -> None:
        self.defaults = defaults
        self.groups: dict[str, GroupPolicy] = {}
        self.errors: list[str] = []
        push = config.get("push", {})
        push = push if isinstance(push, Mapping) else {}
        entries = config.get("groups", [])
        if not isinstance(entries, list):
            self.errors.append("Group configuration must be a list")
            return
        if len(entries) > MAX_GROUPS:
            self.errors.append(
                "Group configuration exceeds 200 entries; group overrides disabled"
            )
            return
        counts = Counter(
            group_umo(entry.get("umo"))
            for entry in entries
            if isinstance(entry, Mapping)
        )
        for index, entry in enumerate(entries):
            if not isinstance(entry, Mapping):
                self.errors.append(f"Invalid group configuration at entry {index + 1}")
                continue
            umo = group_umo(entry.get("umo"))
            if not umo or counts[umo] > 1:
                self.errors.append(
                    f"Invalid or duplicate group target at entry {index + 1}"
                )
                continue
            server = entry.get("default_server", "")
            server = server.strip() if isinstance(server, str) else ""
            settings = replace(
                defaults,
                enabled=_override(entry.get("query_enabled"), defaults.enabled),
                default_server=server or defaults.default_server,
                tier_enabled={
                    tier: _override(entry.get(field), defaults.tier_enabled[tier])
                    for tier, field in (
                        (ServiceTier.FREE, "free_enabled"),
                        (ServiceTier.MEMBER, "member_enabled"),
                        (ServiceTier.OTHER, "other_enabled"),
                    )
                },
            )
            overrides = entry.get("push", {})
            overrides = overrides if isinstance(overrides, Mapping) else {}
            actions = frozenset(
                action
                for action, field in PUSH_FIELDS.items()
                if _override(overrides.get(field), push.get(field) is True)
            )
            self.groups[umo] = GroupPolicy(umo, settings, actions)

    def for_event(self, event: Any) -> PluginSettings:
        policy = self.groups.get(event_group_umo(event))
        return policy.settings if policy else self.defaults

    @property
    def targets(self) -> tuple[GroupPolicy, ...]:
        return tuple(policy for policy in self.groups.values() if policy.actions)
