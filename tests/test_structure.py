"""Verify configuration grouping and release-facing structure."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ROOT_FILES = {
    "main.py",
    "metadata.yaml",
    "_conf_schema.json",
    "requirements.txt",
    "pyproject.toml",
}
CORE_MODULES = {
    "__init__.py",
    "api.py",
    "endpoints.py",
    "game_data.py",
    "query.py",
    "rate_limit.py",
    "settings.py",
}
PRESENTATION_MODULES = {"__init__.py", "image_renderer.py", "rendering.py"}
FLAT_RUNTIME_MODULES = (CORE_MODULES | PRESENTATION_MODULES) - {"__init__.py"}


def test_runtime_source_is_grouped_by_responsibility() -> None:
    assert all((PLUGIN_ROOT / name).is_file() for name in REQUIRED_ROOT_FILES)
    assert {path.name for path in (PLUGIN_ROOT / "core").glob("*.py")} == CORE_MODULES
    assert {
        path.name for path in (PLUGIN_ROOT / "presentation").glob("*.py")
    } == PRESENTATION_MODULES
    assert not any((PLUGIN_ROOT / name).exists() for name in FLAT_RUNTIME_MODULES)


def test_configuration_is_grouped() -> None:
    schema = json.loads((PLUGIN_ROOT / "_conf_schema.json").read_text(encoding="utf-8"))

    assert set(schema) == {
        "general",
        "credentials",
        "features",
        "network",
        "presentation",
    }
    assert all(group["type"] == "object" for group in schema.values())
    assert schema["credentials"]["items"]["token"]["default"] == ""
    assert "member_enabled" in schema["features"]["items"]


def test_runtime_dependencies_and_fonts_are_declared_safely() -> None:
    requirements = (PLUGIN_ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert "Pillow>=12,<13" in requirements
    assert not list(PLUGIN_ROOT.rglob("*.ttf"))
    assert not (PLUGIN_ROOT / "scripts" / "sync_fixed_assets.py").exists()
    assert (PLUGIN_ROOT / "scripts" / "build_adventure_badges.py").is_file()


def test_public_repository_identity_and_versions_are_consistent() -> None:
    metadata = (PLUGIN_ROOT / "metadata.yaml").read_text(encoding="utf-8")
    project = tomllib.loads((PLUGIN_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    api = (PLUGIN_ROOT / "core" / "api.py").read_text(encoding="utf-8")

    metadata_version = re.search(r"^version: v([^\s]+)$", metadata, re.MULTILINE)
    user_agent_version = re.search(r"astrbot-plugin-jx3tools/([0-9.]+)", api)
    assert metadata_version is not None
    assert user_agent_version is not None
    assert metadata_version.group(1) == project["project"]["version"]
    assert metadata_version.group(1) == user_agent_version.group(1)
    assert 'author: "CrystalSight"' in metadata
    assert (
        'repo: "https://github.com/CrystalSight/astrbot_plugin_jx3tools"'
        in metadata
    )


def test_public_repository_documents_and_exclusions_are_present() -> None:
    license_text = (PLUGIN_ROOT / "LICENSE").read_text(encoding="utf-8")
    notices = (PLUGIN_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    gitignore = (PLUGIN_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert license_text.startswith("MIT License\n")
    assert ("LICENSE " + "NOT SELECTED") not in license_text
    assert "assets/adventures" in notices
    assert "assets/bosses" in notices
    assert "Ma Shan Zheng" in notices
    assert "not covered by the MIT License" in " ".join(notices.split())
    assert "仅供自用" not in readme
    assert "不准备公开发布" not in readme
    assert "*.ttf" in gitignore
    assert "*.otf" in gitignore
    assert "/assets/adventures/*.png" in gitignore
    assert "/assets/bosses/*.png" in gitignore


def test_no_scaffold_placeholders_remain_in_user_facing_files() -> None:
    for name in (
        "README.md",
        "CHANGELOG.md",
        "SECURITY.md",
        "THIRD_PARTY_NOTICES.md",
        "metadata.yaml",
    ):
        content = (PLUGIN_ROOT / name).read_text(encoding="utf-8")
        assert "{{" not in content
        assert "https://github.com/you/" not in content
