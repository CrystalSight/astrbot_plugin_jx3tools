"""Verify safe defaults and bounds for nested AstrBot configuration."""

from __future__ import annotations

from astrbot_plugin_jx3tools.endpoints import ServiceTier
from astrbot_plugin_jx3tools.settings import PluginSettings


def test_defaults_are_safe() -> None:
    settings = PluginSettings.from_config({})

    assert settings.enabled
    assert settings.api_base_url == "https://api.jx3api.com"
    assert settings.token == ""
    assert settings.ticket == ""
    assert settings.max_response_bytes == 4_096 * 1_024
    assert settings.tier_enabled[ServiceTier.MEMBER]


def test_legacy_member_switches_remain_backward_compatible() -> None:
    settings = PluginSettings.from_config(
        {"features": {"vip1_enabled": False, "vip2_enabled": False}}
    )

    assert not settings.tier_enabled[ServiceTier.MEMBER]


def test_numeric_values_are_bounded() -> None:
    settings = PluginSettings.from_config(
        {
            "network": {
                "timeout_seconds": 999,
                "max_concurrency": 0,
                "requests_per_minute": -1,
                "max_response_kib": 99_999,
            },
            "presentation": {"max_items": 999},
        }
    )

    assert settings.timeout_seconds == 60
    assert settings.max_concurrency == 1
    assert settings.requests_per_minute == 1
    assert settings.max_response_bytes == 8_192 * 1_024
    assert settings.max_items == 100
