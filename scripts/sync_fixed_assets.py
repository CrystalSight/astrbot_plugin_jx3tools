"""Refresh small fixed JX3BOX thumbnails used by local result rendering."""

from __future__ import annotations

import hashlib
import json
import warnings
from io import BytesIO
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = ROOT / "assets"
USER_AGENT = "astrbot-plugin-jx3tools-asset-sync/1.0"
ALLOWED_ASSET_HOSTS = {"node.jx3box.com", "img.jx3box.com"}
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_IMAGE_EDGE = 4_096
MAX_IMAGE_PIXELS = 16_777_216


class NoRedirectHandler(HTTPRedirectHandler):
    """Reject every redirect so fixed asset requests cannot change origin."""

    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


OPENER = build_opener(NoRedirectHandler())


def validate_asset_url(url: str) -> None:
    """Require one credential-free HTTPS URL on an exact JX3BOX host."""
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Asset URL has an invalid port") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_ASSET_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or parsed.fragment
    ):
        raise ValueError("Asset URL is outside the approved JX3BOX origins")


def request_bytes(url: str) -> bytes:
    """Read one bounded public asset or JSON document."""
    validate_asset_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with OPENER.open(request, timeout=30) as response:  # noqa: S310 - validated above
        validate_asset_url(response.geturl())
        data = response.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise ValueError(f"Remote asset is too large: {url}")
    return data


def asset_path(category: str, name: str) -> Path:
    """Build the same stable filename used by the runtime renderer."""
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
    return ASSET_ROOT / category / f"{digest}.png"


def save_thumbnail(data: bytes, path: Path) -> None:
    """Normalize one image to a compact square PNG."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in ALLOWED_IMAGE_FORMATS:
                    raise ValueError("Asset image format is not approved")
                width, height = source.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_IMAGE_EDGE
                    or height > MAX_IMAGE_EDGE
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise ValueError("Asset image dimensions exceed safety limits")
                source.load()
                image = ImageOps.fit(
                    source.convert("RGBA"),
                    (72, 72),
                    method=Image.Resampling.LANCZOS,
                )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Asset image dimensions exceed Pillow safety limits") from exc
    except UnidentifiedImageError as exc:
        raise ValueError("Asset payload is not a supported image") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)


def adventure_image_url(item: dict[str, object]) -> str:
    """Return the JX3BOX catalogue artwork URL for one adventure."""
    raw = str(item.get("szFirstPagePath") or "").replace("\\", "/").lower()
    relative = raw.replace("ui/image/adventure/", "").removesuffix(".tga")
    return (
        "https://img.jx3box.com/adventure/adventure/std/"
        f"{quote(relative, safe='/')}.png"
    )


def sync_adventures() -> tuple[int, int]:
    """Download current normal and perfect adventure thumbnails."""
    saved = failed = 0
    for adventure_type in ("normal", "perfect"):
        query = urlencode(
            {"type": adventure_type, "client": "std", "page": 1, "per": 200}
        )
        document = json.loads(
            request_bytes(f"https://node.jx3box.com/serendipities?{query}")
        )
        for item in document.get("list", []):
            name = str(item.get("szName") or "").strip()
            if not name:
                continue
            try:
                save_thumbnail(
                    request_bytes(adventure_image_url(item)),
                    asset_path("adventures", name),
                )
                saved += 1
            except Exception as exc:  # noqa: BLE001 - report individual remote gaps
                failed += 1
                print(f"adventure skipped: {name}: {type(exc).__name__}")
    return saved, failed


def boss_image_url(item: dict[str, object]) -> str:
    """Return the avatar URL used by the JX3BOX Baizhan map."""
    image_path = str(item.get("ImagePath") or "").replace("\\", "/")
    stem = Path(image_path).stem.lower() if image_path else "fbcdpanel02"
    raw_frame = item.get("ImageFrame")
    try:
        frame = int(raw_frame) if isinstance(raw_frame, (int, str)) else 51
    except ValueError:
        frame = 51
    return f"https://img.jx3box.com/pve/baizhan/{stem}_{frame}.png"


def sync_bosses() -> tuple[int, int]:
    """Download one fixed thumbnail for every named JX3BOX Baizhan boss."""
    document = json.loads(request_bytes("https://node.jx3box.com/monster/boss"))
    unique: dict[str, dict[str, object]] = {}
    for item in document.get("data", []):
        name = str(item.get("szName") or "").strip()
        if name and name not in unique:
            unique[name] = item
    saved = failed = 0
    for name, item in unique.items():
        try:
            save_thumbnail(
                request_bytes(boss_image_url(item)),
                asset_path("bosses", name),
            )
            saved += 1
        except Exception as exc:  # noqa: BLE001 - report individual remote gaps
            failed += 1
            print(f"boss skipped: {name}: {type(exc).__name__}")
    return saved, failed


if __name__ == "__main__":
    adventure_result = sync_adventures()
    boss_result = sync_bosses()
    print(
        "fixed assets refreshed: "
        f"adventures={adventure_result[0]} failed={adventure_result[1]}, "
        f"bosses={boss_result[0]} failed={boss_result[1]}"
    )
