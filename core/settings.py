"""Validated plugin settings derived from AstrBot configuration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .endpoints import ServiceTier


@dataclass(frozen=True, slots=True)
class PluginSettings:
    """Normalized and bounded runtime settings."""

    enabled: bool
    api_base_url: str
    default_server: str
    token: str
    ticket: str
    tier_enabled: Mapping[ServiceTier, bool]
    timeout_seconds: int
    max_concurrency: int
    requests_per_minute: int
    max_response_bytes: int
    render_mode: str
    max_items: int

    @classmethod
    def from_config(cls, config: Mapping[str, Any]) -> PluginSettings:
        """Build settings from nested AstrBot configuration with safe bounds."""
        general = _section(config, "general")
        credentials = _section(config, "credentials")
        features = _section(config, "features")
        network = _section(config, "network")
        presentation = _section(config, "presentation")

        render_mode = _string(presentation, "render_mode", "auto").casefold()
        if render_mode not in {"auto", "text", "image"}:
            render_mode = "auto"

        legacy_member_enabled = _boolean(features, "vip1_enabled", True) or _boolean(
            features,
            "vip2_enabled",
            True,
        )
        return cls(
            enabled=_boolean(general, "enabled", True),
            api_base_url=_string(
                general,
                "api_base_url",
                "https://api.jx3api.com",
            ).rstrip("/"),
            default_server=_string(general, "default_server", ""),
            token=_string(credentials, "token", ""),
            ticket=_string(credentials, "ticket", ""),
            tier_enabled={
                ServiceTier.FREE: _boolean(features, "free_enabled", True),
                ServiceTier.MEMBER: _boolean(
                    features,
                    "member_enabled",
                    legacy_member_enabled,
                ),
                ServiceTier.OTHER: _boolean(features, "other_enabled", True),
            },
            timeout_seconds=_integer(
                network,
                "timeout_seconds",
                20,
                minimum=3,
                maximum=60,
            ),
            max_concurrency=_integer(
                network,
                "max_concurrency",
                4,
                minimum=1,
                maximum=20,
            ),
            requests_per_minute=_integer(
                network,
                "requests_per_minute",
                12,
                minimum=1,
                maximum=60,
            ),
            max_response_bytes=_integer(
                network,
                "max_response_kib",
                4_096,
                minimum=64,
                maximum=8_192,
            )
            * 1_024,
            render_mode=render_mode,
            max_items=_integer(
                presentation,
                "max_items",
                30,
                minimum=1,
                maximum=100,
            ),
        )


def _section(config: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = config.get(name, {})
    return value if isinstance(value, Mapping) else {}


def _string(config: Mapping[str, Any], name: str, default: str) -> str:
    value = config.get(name, default)
    return value.strip() if isinstance(value, str) else default


def _boolean(config: Mapping[str, Any], name: str, default: bool) -> bool:
    value = config.get(name, default)
    return value if isinstance(value, bool) else default


def _integer(
    config: Mapping[str, Any],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = config.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int):
        value = default
    return max(minimum, min(maximum, value))
