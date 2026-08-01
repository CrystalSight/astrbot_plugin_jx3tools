"""Verify security boundaries in developer-only network scripts."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from astrbot_plugin_jx3tools.scripts.docker_webchat_smoke import validate_base_url
from astrbot_plugin_jx3tools.scripts.sync_fixed_assets import (
    NoRedirectHandler,
    save_thumbnail,
    validate_asset_url,
)
from PIL import Image


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        ("http://127.0.0.1:6185/", "http://127.0.0.1:6185"),
        ("http://localhost:6185", "http://localhost:6185"),
        ("http://[::1]:6185", "http://[::1]:6185"),
    ),
)
def test_webchat_smoke_accepts_only_local_http_origins(
    value: str,
    expected: str,
) -> None:
    assert validate_base_url(value) == expected


@pytest.mark.parametrize(
    "value",
    (
        "https://127.0.0.1:6185",
        "http://attacker.example:6185",
        "http://127.0.0.1:6185@attacker.example:80",
        "http://127.0.0.1:6185/api",
        "http://127.0.0.1",
    ),
)
def test_webchat_smoke_rejects_nonlocal_or_ambiguous_origins(value: str) -> None:
    with pytest.raises(RuntimeError, match="local HTTP origin"):
        validate_base_url(value)


def test_asset_sync_allows_exact_https_hosts_and_disables_redirects() -> None:
    validate_asset_url("https://node.jx3box.com/monster/boss")
    validate_asset_url("https://img.jx3box.com/pve/baizhan/avatar.png")

    for value in (
        "http://node.jx3box.com/monster/boss",
        "https://node.jx3box.com.attacker.example/monster/boss",
        "https://user@node.jx3box.com/monster/boss",
        "https://node.jx3box.com:444/monster/boss",
    ):
        with pytest.raises(ValueError, match="approved JX3BOX origins"):
            validate_asset_url(value)
    assert NoRedirectHandler().redirect_request() is None


def test_asset_sync_rejects_unapproved_formats_and_dimensions() -> None:
    output = Path("__jx3tools_rejected_thumbnail.png")
    assert not output.exists()
    gif = BytesIO()
    Image.new("RGB", (16, 16), "red").save(gif, format="GIF")
    with pytest.raises(ValueError, match="format"):
        save_thumbnail(gif.getvalue(), output)

    oversized = BytesIO()
    Image.new("RGB", (4_097, 1), "blue").save(oversized, format="PNG")
    with pytest.raises(ValueError, match="dimensions"):
        save_thumbnail(oversized.getvalue(), output)

    assert not output.exists()
