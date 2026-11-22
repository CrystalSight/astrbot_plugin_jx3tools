"""Draw the approved single-column equipment sheet using local fonts."""

from __future__ import annotations

import re
from functools import lru_cache
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .equipment import Equipment, IconLabel
from .image_renderer import (
    BACKGROUND,
    BORDER,
    CARD_BACKGROUND,
    JADE,
    MUTED,
    TEXT,
    FontPaths,
    LocalRenderError,
    decode_source_image,
)


def render_equipment(
    sheet: Equipment, icons: dict[str, bytes], fonts: FontPaths, *, output_path: Path
) -> str:
    @lru_cache(maxsize=64)
    def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(str(fonts.semibold if bold else fonts.regular), size)

    def wrap(text: str, size: int, width: int, bold: bool = False) -> list[str]:
        lines = [""]
        face = font(size, bold)
        for character in text:
            if lines[-1] and face.getlength(lines[-1] + character) > width:
                lines.append("")
            lines[-1] += character
        return lines

    stats_y = 220
    stats_end = stats_y + max(1, ceil(len(sheet.stats) / 4)) * 55 + 2
    talents_y = stats_end + 52
    gear_y = talents_y + 116
    layouts = []
    for row in sheet.gear:
        titles = wrap(row.item.name, 21, 291, True)
        details = wrap(row.details, 16, 291)
        effects = [wrap(effect.name, 17, 236) for effect in row.effects]
        height = max(
            92,
            28 * len(titles) + 21 * len(details) + 40,
            14 + sum(max(31, len(lines) * 23 + 6) for lines in effects),
        )
        layouts.append((titles, details, effects, height))
    bottom = gear_y + sum(layout[-1] for layout in layouts) + 8
    image = Image.new("RGB", (720, bottom + 16), BACKGROUND)
    draw = ImageDraw.Draw(image)

    def label(
        x: float,
        y: float,
        value: str,
        size: int,
        color: str = TEXT,
        *,
        bold: bool = False,
        center: bool = False,
        width: int = 672,
    ) -> None:
        face = font(size, bold)
        while size > 12 and face.getlength(value) > width:
            size -= 1
            face = font(size, bold)
        if face.getlength(value) > width:
            while value and face.getlength(value + "…") > width:
                value = value[:-1]
            value += "…"
        draw.text((x, y), value, fill=color, font=face, anchor="mm" if center else "lm")

    def icon(asset: IconLabel, x: int, y: int, side: int, fallback: str) -> None:
        raw = icons.get(asset.icon)
        if raw:
            try:
                tile = ImageOps.fit(
                    decode_source_image(raw, max_side=side), (side, side)
                )
                image.paste(tile, (x, y), tile)
                return
            except LocalRenderError:
                pass
        draw.rounded_rectangle(
            (x, y, x + side - 1, y + side - 1), 4, fill=BACKGROUND, outline=BORDER
        )
        label(
            x + side / 2,
            y + side / 2,
            fallback,
            min(18, side - 3),
            JADE,
            center=True,
            width=side - 2,
        )

    def section(y: int, name: str) -> None:
        label(31, y, name, 21, JADE, bold=True)
        draw.line((128, y, 689, y), fill=BORDER)

    icon(sheet.kungfu, 328, 14, 64, sheet.kungfu.name)
    label(360, 113, sheet.score, 34, JADE, bold=True, center=True)
    label(360, 157, sheet.title, 25, bold=True, center=True)
    section(198, "属性")
    draw.rounded_rectangle(
        (21, stats_y, 699, stats_end), 12, fill=CARD_BACKGROUND, outline=BORDER
    )
    for i, (name, value) in enumerate(sheet.stats):
        x = 108 + i % 4 * 168
        y = stats_y + 18 + i // 4 * 55
        label(x, y, value, 21, bold=True, center=True, width=156)
        label(x, y + 23, name, 15, MUTED, center=True, width=156)
    if not sheet.stats:
        label(360, stats_y + 27, "暂无已收录属性", 17, MUTED, center=True)
    section(talents_y - 23, "奇穴")
    for i, talent in enumerate(sheet.talents):
        cell = 672 / len(sheet.talents)
        x = round(24 + (i + 0.5) * cell)
        icon(talent, x - 20, talents_y, 40, talent.name[:1])
        label(x, talents_y + 56, talent.name, 16, center=True, width=int(cell) - 3)
    if not sheet.talents:
        label(360, talents_y + 25, "暂无已收录奇穴", 17, MUTED, center=True)
    section(gear_y - 21, "装备")
    draw.rounded_rectangle(
        (21, gear_y, 699, bottom), 12, fill=CARD_BACKGROUND, outline=BORDER
    )
    y = gear_y + 5
    for i, (row, (titles, details, effects, height)) in enumerate(
        zip(sheet.gear, layouts, strict=True)
    ):
        if i:
            draw.line((35, y - 2, 685, y - 2), fill=BORDER)
        icon(row.item, 36, y + 11, 62, "装")
        middle = y + 18
        for title in titles:
            label(113, middle, title, 21, bold=True)
            middle += 28
        for detail in details:
            label(113, middle, detail, 16, MUTED)
            middle += 21
        for j, stone in enumerate(row.stones):
            match = re.search(r"[（(]([^）)]+)[）)]", stone.name)
            fallback = match[1].removesuffix("级") if match else "石"
            icon(stone, 114 + j * 25, middle - 5, 20, fallback)
        right = y + 20
        for effect, lines in zip(row.effects, effects, strict=True):
            icon(effect, 418, right, 22, "彩" if effect.name.startswith("彩") else "附")
            for n, part in enumerate(lines):
                label(449, right + 11 + n * 23, part, 17)
            right += max(31, len(lines) * 23 + 6)
        y += height
    image.save(output_path, format="PNG")
    return str(output_path)
