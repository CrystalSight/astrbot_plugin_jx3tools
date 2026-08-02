"""Build and validate project-owned adventure badges without network access."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
ASSET_DIRECTORY = ROOT / "assets" / "adventure_badges"
MANIFEST_PATH = ASSET_DIRECTORY / "manifest.json"
MASTER_PATH = ASSET_DIRECTORY / "ink_ring.png"
WORDMARK_DIRECTORY = ASSET_DIRECTORY / "wordmark_overrides"
BADGE_SIZE = 256
MASTER_MAX_SIDE = 512
WORDMARK_SIZE = (244, 112)
MAX_BADGE_BYTES = 1024 * 1024
STROKE_WIDTH = 3
TEXT_FILL = "#202b29"
TEXT_STROKE = "#f6f0e5"
HASHED_PNG = re.compile(r"^[0-9a-f]{16}\.png$")
SHA256_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def asset_path(name: str, directory: Path = ASSET_DIRECTORY) -> Path:
    """Return the stable output path for one adventure name."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return directory / f"{digest}.png"


def load_manifest(
    path: Path = MANIFEST_PATH,
) -> tuple[tuple[str, ...], dict[str, Path], str]:
    """Load and validate adventure names and explicit wordmark overrides."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Adventure manifest cannot be read: {path}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("names"), list):
        raise ValueError("Adventure manifest must contain a names list")
    names: list[str] = []
    for value in document["names"]:
        if not isinstance(value, str) or not value or value != value.strip():
            raise ValueError("Adventure names must be non-empty trimmed strings")
        if len(value) > 32:
            raise ValueError(f"Adventure name is too long: {value}")
        names.append(value)
    if len(names) != len(set(names)):
        raise ValueError("Adventure manifest contains duplicate names")
    if not names:
        raise ValueError("Adventure manifest must not be empty")
    raw_overrides = document.get("wordmark_overrides", {})
    if not isinstance(raw_overrides, dict):
        raise ValueError("Adventure wordmark overrides must be an object")
    overrides: dict[str, Path] = {}
    for name, raw_path in raw_overrides.items():
        if not isinstance(name, str) or name not in names:
            raise ValueError("Adventure wordmark override names must exist in names")
        if not isinstance(raw_path, str) or "\\" in raw_path:
            raise ValueError("Adventure wordmark override must use a safe hashed PNG")
        relative = PurePosixPath(raw_path)
        expected_name = asset_path(name, path.parent).name
        if relative.parts != ("wordmark_overrides", expected_name):
            raise ValueError("Adventure wordmark override must use a safe hashed PNG")
        overrides[name] = path.parent / Path(*relative.parts)
    font = document.get("font")
    font_sha256 = font.get("file_sha256") if isinstance(font, dict) else None
    if not isinstance(font_sha256, str) or not SHA256_DIGEST.fullmatch(font_sha256):
        raise ValueError("Adventure manifest must contain a lowercase font SHA-256")
    return tuple(names), overrides, font_sha256


def load_names(path: Path = MANIFEST_PATH) -> tuple[str, ...]:
    """Load the names from the versioned adventure manifest."""
    names, _overrides, _font_sha256 = load_manifest(path)
    return names


def validate_font_file(font_path: Path, expected_sha256: str) -> None:
    """Reject a font that does not match the versioned build input."""
    if not SHA256_DIGEST.fullmatch(expected_sha256):
        raise ValueError("Expected font SHA-256 must be a lowercase digest")
    try:
        with font_path.open("rb") as source:
            actual_sha256 = hashlib.file_digest(source, "sha256").hexdigest()
    except OSError as exc:
        raise ValueError(f"Badge font cannot be read: {font_path}") from exc
    if actual_sha256 != expected_sha256:
        raise ValueError(
            "Badge font SHA-256 mismatch: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )


def load_master(path: Path = MASTER_PATH) -> Image.Image:
    """Load the bounded transparent ink-ring master."""
    try:
        with Image.open(path) as source:
            if source.format != "PNG" or source.mode != "P":
                raise ValueError("Adventure master must be a palette PNG")
            source.load()
            image = source.convert("RGBA")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Adventure master cannot be decoded: {path}") from exc
    if max(image.size) > MASTER_MAX_SIDE:
        raise ValueError("Adventure master exceeds the 512 px limit")
    alpha_min, alpha_max = image.getchannel("A").getextrema()
    if alpha_min != 0 or alpha_max == 0:
        raise ValueError("Adventure master must contain visible and transparent pixels")
    return image


def load_wordmark(path: Path) -> Image.Image:
    """Load one bounded transparent RGBA wordmark override."""
    try:
        with Image.open(path) as source:
            if source.format != "PNG" or source.mode != "RGBA":
                raise ValueError("Adventure wordmark must be an RGBA PNG")
            if source.size != WORDMARK_SIZE:
                raise ValueError("Adventure wordmark must be exactly 244x112")
            source.load()
            image = source.copy()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Adventure wordmark cannot be decoded: {path}") from exc
    alpha_min, alpha_max = image.getchannel("A").getextrema()
    if alpha_min != 0 or alpha_max == 0:
        raise ValueError(
            "Adventure wordmark must contain visible and transparent pixels"
        )
    return image


def _base_badge(master: Image.Image) -> Image.Image:
    ring = master.convert("RGBA")
    ring.thumbnail((246, 246), Image.Resampling.LANCZOS)
    badge = Image.new("RGBA", (BADGE_SIZE, BADGE_SIZE), (0, 0, 0, 0))
    badge.alpha_composite(
        ring,
        ((BADGE_SIZE - ring.width) // 2, (BADGE_SIZE - ring.height) // 2),
    )
    return badge


def _quantize_badge(badge: Image.Image) -> Image.Image:
    return badge.quantize(
        colors=256,
        method=Image.Quantize.FASTOCTREE,
        dither=Image.Dither.NONE,
    )


def _fit_name(
    draw: ImageDraw.ImageDraw,
    name: str,
    font_path: Path,
) -> tuple[str, ImageFont.FreeTypeFont, int]:
    for size in range(64, 37, -1):
        font = ImageFont.truetype(str(font_path), size)
        bounds = draw.textbbox((0, 0), name, font=font, stroke_width=STROKE_WIDTH)
        if bounds[2] - bounds[0] <= 244:
            return name, font, 0
    split = (len(name) + 1) // 2
    text = f"{name[:split]}\n{name[split:]}"
    for size in range(48, 29, -1):
        font = ImageFont.truetype(str(font_path), size)
        bounds = draw.multiline_textbbox(
            (0, 0),
            text,
            font=font,
            spacing=-4,
            align="center",
            stroke_width=STROKE_WIDTH,
        )
        if bounds[2] - bounds[0] <= 220 and bounds[3] - bounds[1] <= 112:
            return text, font, -4
    raise ValueError(f"Adventure name cannot fit in a badge: {name}")


def build_badge(name: str, master: Image.Image, font_path: Path) -> Image.Image:
    """Compose one transparent adventure badge from the shared ink master."""
    if not font_path.is_file():
        raise ValueError(f"Badge font does not exist: {font_path}")
    badge = _base_badge(master)
    draw = ImageDraw.Draw(badge)
    text, font, spacing = _fit_name(draw, name, font_path)
    bounds = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing,
        align="center",
        stroke_width=STROKE_WIDTH,
    )
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    draw.multiline_text(
        (
            (BADGE_SIZE - width) / 2 - bounds[0],
            (BADGE_SIZE - height) / 2 - bounds[1],
        ),
        text,
        font=font,
        fill=TEXT_FILL,
        spacing=spacing,
        align="center",
        stroke_width=STROKE_WIDTH,
        stroke_fill=TEXT_STROKE,
    )
    return badge


def build_badge_from_wordmark(
    master: Image.Image,
    wordmark: Image.Image,
) -> Image.Image:
    """Compose one badge from the shared ring and an approved wordmark."""
    if wordmark.mode != "RGBA" or wordmark.size != WORDMARK_SIZE:
        raise ValueError("Adventure wordmark must be a 244x112 RGBA image")
    badge = _base_badge(master)
    badge.alpha_composite(
        wordmark,
        (
            (BADGE_SIZE - wordmark.width) // 2,
            (BADGE_SIZE - wordmark.height) // 2,
        ),
    )
    return badge


def _glyph_signature(
    font: ImageFont.FreeTypeFont,
    character: str,
) -> tuple[tuple[int, int, int, int], bytes]:
    raw_left, raw_top, raw_right, raw_bottom = font.getbbox(character)
    left = round(raw_left)
    top = round(raw_top)
    right = round(raw_right)
    bottom = round(raw_bottom)
    bounds = (left, top, right, bottom)
    glyph = Image.new("L", (max(1, right - left), max(1, bottom - top)), 0)
    ImageDraw.Draw(glyph).text((-left, -top), character, font=font, fill=255)
    return bounds, glyph.tobytes()


def validate_font_coverage(
    names: tuple[str, ...],
    overrides: Mapping[str, Path],
    font_path: Path,
) -> None:
    """Reject uncovered names that would render FreeType's .notdef glyph."""
    if not font_path.is_file():
        raise ValueError(f"Badge font does not exist: {font_path}")
    font = ImageFont.truetype(str(font_path), 64)
    missing_signature = _glyph_signature(font, "\U0010ffff")
    missing: dict[str, list[str]] = {}
    for name in names:
        if name in overrides:
            continue
        for character in dict.fromkeys(name):
            if _glyph_signature(font, character) == missing_signature:
                missing.setdefault(character, []).append(name)
    if missing:
        details = "; ".join(
            f"U+{ord(character):04X} {character!r} in {', '.join(found_names)}"
            for character, found_names in sorted(missing.items())
        )
        raise ValueError(f"Badge font lacks glyphs: {details}")


def validate_wordmark_overrides(
    overrides: Mapping[str, Path],
    directory: Path = WORDMARK_DIRECTORY,
) -> dict[str, Image.Image]:
    """Validate the declared wordmark set before loading its images."""
    expected = set(overrides.values())
    actual = (
        {path for path in directory.iterdir() if path.is_file()}
        if directory.is_dir()
        else set()
    )
    if actual != expected:
        raise ValueError(
            "Adventure wordmark set does not match the manifest: "
            f"missing={len(expected - actual)}, "
            f"unexpected={len(actual - expected)}"
        )
    return {name: load_wordmark(path) for name, path in overrides.items()}


def write_badges(font_path: Path) -> int:
    """Regenerate every expected badge without deleting unrelated files."""
    names, overrides, font_sha256 = load_manifest()
    validate_font_file(font_path, font_sha256)
    validate_font_coverage(names, overrides, font_path)
    master = load_master()
    wordmarks = validate_wordmark_overrides(overrides)
    ASSET_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name in names:
        badge = (
            build_badge_from_wordmark(master, wordmarks[name])
            if name in wordmarks
            else build_badge(name, master, font_path)
        )
        palette = _quantize_badge(badge)
        output = asset_path(name)
        temporary = output.with_suffix(".png.tmp")
        palette.save(temporary, format="PNG", optimize=True)
        temporary.replace(output)
    return len(names)


def validate_badges() -> tuple[int, int]:
    """Validate the committed master and generated badge set."""
    names, overrides, _font_sha256 = load_manifest()
    master = load_master()
    wordmarks = validate_wordmark_overrides(overrides)
    expected = {asset_path(name) for name in names}
    actual = {
        path
        for path in ASSET_DIRECTORY.glob("*.png")
        if path != MASTER_PATH and HASHED_PNG.fullmatch(path.name)
    }
    unexpected = {
        path
        for path in ASSET_DIRECTORY.glob("*.png")
        if path != MASTER_PATH and not HASHED_PNG.fullmatch(path.name)
    }
    missing = expected - actual
    stale = actual - expected
    if missing or stale or unexpected:
        raise ValueError(
            "Adventure badge set does not match the manifest: "
            f"missing={len(missing)}, stale={len(stale)}, unexpected={len(unexpected)}"
        )
    total_bytes = 0
    for name in names:
        path = asset_path(name)
        try:
            with Image.open(path) as source:
                if (
                    source.format != "PNG"
                    or source.mode != "P"
                    or source.size != (BADGE_SIZE, BADGE_SIZE)
                ):
                    raise ValueError(f"Adventure badge has an invalid format: {path.name}")
                source.load()
                actual_rgba = source.convert("RGBA")
                alpha_min, alpha_max = actual_rgba.getchannel("A").getextrema()
        except (OSError, UnidentifiedImageError) as exc:
            raise ValueError(f"Adventure badge cannot be decoded: {path.name}") from exc
        if alpha_min != 0 or alpha_max == 0:
            raise ValueError(f"Adventure badge lacks transparency: {path.name}")
        if name in wordmarks:
            expected_rgba = _quantize_badge(
                build_badge_from_wordmark(master, wordmarks[name])
            ).convert("RGBA")
            if actual_rgba.tobytes() != expected_rgba.tobytes():
                raise ValueError(
                    f"Adventure badge does not match its wordmark: {path.name}"
                )
        total_bytes += path.stat().st_size
    if total_bytes > MAX_BADGE_BYTES:
        raise ValueError(
            f"Adventure badges exceed the 1 MiB limit: {total_bytes} bytes"
        )
    return len(expected), total_bytes


def parse_args() -> argparse.Namespace:
    """Parse the offline builder command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate existing assets")
    parser.add_argument("--font", type=Path, help="path to MaShanZheng-Regular.ttf")
    return parser.parse_args()


def main() -> None:
    """Build badges or validate the committed set."""
    args = parse_args()
    if args.check:
        count, total_bytes = validate_badges()
        print(f"adventure badges valid: count={count}, bytes={total_bytes}")
        return
    if args.font is None:
        raise SystemExit("--font is required unless --check is used")
    count = write_badges(args.font)
    validated, total_bytes = validate_badges()
    if validated != count:
        raise SystemExit("generated badge count does not match validation")
    print(f"adventure badges built: count={count}, bytes={total_bytes}")


if __name__ == "__main__":
    main()
