"""Verify developer-only script boundaries and generated assets."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from astrbot_plugin_jx3tools.scripts.build_adventure_badges import (
    ASSET_DIRECTORY,
    MAX_BADGE_BYTES,
    WORDMARK_DIRECTORY,
    asset_path,
    build_badge,
    load_manifest,
    load_master,
    load_names,
    load_wordmark,
    validate_badges,
    validate_font_coverage,
    validate_font_file,
    validate_wordmark_overrides,
)
from astrbot_plugin_jx3tools.scripts.docker_webchat_smoke import validate_base_url
from PIL import Image, ImageFont


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


def test_adventure_badges_match_the_offline_manifest() -> None:
    names, overrides, font_sha256 = load_manifest()
    count, total_bytes = validate_badges()

    assert len(names) == len(set(names)) == 57
    assert overrides == {
        "侠行囧途": WORDMARK_DIRECTORY / "22873a526ca61e02.png",
    }
    assert font_sha256 == "6d2546bb189c732a8ca29af9e22457b152387d158aa459e4ac2ce1e51788b7fb"
    assert count == 57
    assert total_bytes <= MAX_BADGE_BYTES
    assert asset_path("../../future adventure").parent == ASSET_DIRECTORY


def test_adventure_badge_builder_is_deterministic_for_long_names() -> None:
    font_path: Path | None = None
    for font_name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(font_name, 12)
        except OSError:
            continue
        resolved = font.path
        if isinstance(resolved, str):
            font_path = Path(resolved)
            break
    if font_path is None:
        pytest.skip("No system TrueType font is available for deterministic output")
    master = load_master()

    first = build_badge("未来全新奇遇名称", master, font_path)
    second = build_badge("未来全新奇遇名称", master, font_path)

    assert first.size == (256, 256)
    assert first.mode == "RGBA"
    assert first.tobytes() == second.tobytes()
    assert first.getchannel("A").getextrema()[0] == 0


def test_adventure_manifest_rejects_duplicate_names(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"names": ["重复", "重复"]}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        load_names(manifest)


def test_adventure_builder_rejects_font_hash_mismatch(tmp_path: Path) -> None:
    font_path = tmp_path / "font.ttf"
    font_path.write_bytes(b"expected font bytes")
    expected = hashlib.sha256(font_path.read_bytes()).hexdigest()

    validate_font_file(font_path, expected)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        validate_font_file(font_path, "0" * 64)


def test_adventure_manifest_rejects_invalid_font_digest(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"names": ["未来奇遇"], "font": {"file_sha256": "INVALID"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="lowercase font SHA-256"):
        load_manifest(manifest)


def test_adventure_manifest_rejects_unsafe_wordmark_path(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        '{"names": ["侠行囧途"], "wordmark_overrides": '
        '{"侠行囧途": "wordmark_overrides/../escape.png"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="safe hashed PNG"):
        load_manifest(manifest)


def test_adventure_wordmark_must_be_bounded_and_transparent(tmp_path: Path) -> None:
    wordmark = tmp_path / "wordmark.png"
    Image.new("RGBA", (245, 112), (0, 0, 0, 0)).save(wordmark)

    with pytest.raises(ValueError, match="244x112"):
        load_wordmark(wordmark)


def test_adventure_wordmark_set_rejects_missing_and_unexpected(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "wordmark_overrides"
    expected = directory / "22873a526ca61e02.png"
    overrides = {"侠行囧途": expected}

    with pytest.raises(ValueError, match="missing=1, unexpected=0"):
        validate_wordmark_overrides(overrides, directory)

    directory.mkdir()
    load_wordmark(WORDMARK_DIRECTORY / expected.name).save(expected)
    unexpected = directory / "0000000000000000.png"
    load_wordmark(expected).save(unexpected)
    with pytest.raises(ValueError, match="missing=0, unexpected=1"):
        validate_wordmark_overrides(overrides, directory)


def test_adventure_font_coverage_reports_uncovered_glyphs() -> None:
    font_path: Path | None = None
    for font_name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            font = ImageFont.truetype(font_name, 12)
        except OSError:
            continue
        resolved = font.path
        if isinstance(resolved, str):
            font_path = Path(resolved)
            break
    if font_path is None:
        pytest.skip("No system TrueType font is available for coverage testing")
    name = "Future\U0010ffff"

    with pytest.raises(ValueError, match=r"U\+10FFFF.*Future"):
        validate_font_coverage((name,), {}, font_path)

    validate_font_coverage((name,), {name: Path("declared.png")}, font_path)
