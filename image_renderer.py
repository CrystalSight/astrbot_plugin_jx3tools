"""Render mobile-first result cards locally with Pillow."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from io import BytesIO
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .rendering import (
    AdventureGroup,
    ChartEntry,
    FoodRow,
    LineSeries,
    MapNode,
    RenderCard,
    RenderDocument,
    RenderTable,
    TableRow,
)

CANVAS_WIDTH = 720
MAX_CANVAS_HEIGHT = 12_000
MAX_WRAP_CHARACTERS = 256
MARGIN = 48
CONTENT_WIDTH = CANVAS_WIDTH - MARGIN * 2
REGULAR_FONT_NAME = "AlibabaPuHuiTi-3-55-Regular.ttf"
BOLD_FONT_NAME = "AlibabaPuHuiTi-3-75-SemiBold.ttf"
MAX_SOURCE_PIXELS = 40_000_000
ARENA_PROFILE_RIGHT_COLUMN_SHIFT = 38

BACKGROUND = "#f5f0e6"
CARD_BACKGROUND = "#fffdf8"
TEXT = "#243331"
MUTED = "#66736f"
JADE = "#3f766a"
CINNABAR = "#a94c43"
BORDER = "#d8d0c1"
TRACK = "#e7e0d4"


class LocalRenderError(RuntimeError):
    """Represent a safe local rendering failure."""


@dataclass(frozen=True, slots=True)
class FontPaths:
    """Resolved private font files."""

    regular: Path
    semibold: Path

    @classmethod
    def from_directory(cls, directory: Path) -> FontPaths:
        """Resolve the two approved Alibaba PuHuiTi font files."""
        return cls(
            regular=directory / REGULAR_FONT_NAME,
            semibold=directory / BOLD_FONT_NAME,
        )

    @property
    def available(self) -> bool:
        """Return whether both original TTF files are readable files."""
        return self.regular.is_file() and self.semibold.is_file()


class LocalImageRenderer:
    """Generate one 720 px single-column raster image without remote services."""

    def __init__(self, font_paths: FontPaths) -> None:
        if not font_paths.available:
            raise LocalRenderError("阿里巴巴普惠体文件缺失。")
        try:
            self.title_font = ImageFont.truetype(str(font_paths.semibold), 48)
            self.subtitle_font = ImageFont.truetype(str(font_paths.regular), 29)
            self.section_font = ImageFont.truetype(str(font_paths.semibold), 34)
            self.card_title_font = ImageFont.truetype(str(font_paths.semibold), 31)
            self.label_font = ImageFont.truetype(str(font_paths.semibold), 25)
            self.body_font = ImageFont.truetype(str(font_paths.regular), 30)
            self.article_font = ImageFont.truetype(str(font_paths.regular), 28)
            self.small_font = ImageFont.truetype(str(font_paths.regular), 24)
            self.chart_font = ImageFont.truetype(str(font_paths.regular), 26)
            self.chart_bold_font = ImageFont.truetype(str(font_paths.semibold), 26)
            self.table_font = ImageFont.truetype(str(font_paths.regular), 21)
            self.table_bold_font = ImageFont.truetype(str(font_paths.semibold), 21)
            self.compact_font = ImageFont.truetype(str(font_paths.regular), 18)
            self.compact_bold_font = ImageFont.truetype(str(font_paths.semibold), 18)
            self.calendar_day_font = ImageFont.truetype(str(font_paths.semibold), 23)
            self.calendar_label_font = ImageFont.truetype(str(font_paths.semibold), 15)
            self.calendar_value_font = ImageFont.truetype(str(font_paths.regular), 16)
            self.map_name_font = ImageFont.truetype(str(font_paths.regular), 15)
            self.map_index_font = ImageFont.truetype(str(font_paths.semibold), 15)
            self.axis_font = ImageFont.truetype(str(font_paths.regular), 19)
            self.food_school_font = ImageFont.truetype(str(font_paths.semibold), 21)
            self.food_item_font = ImageFont.truetype(str(font_paths.regular), 20)
            self.food_item_small_font = ImageFont.truetype(str(font_paths.regular), 18)
            self.food_item_compact_font = ImageFont.truetype(str(font_paths.regular), 16)
            self.adventure_name_font = ImageFont.truetype(str(font_paths.regular), 18)
            self.adventure_time_font = ImageFont.truetype(str(font_paths.semibold), 20)
        except OSError as exc:
            raise LocalRenderError("阿里巴巴普惠体无法读取。") from exc
        self.asset_directory = Path(__file__).resolve().parent / "assets"
        self._asset_cache: dict[tuple[str, int], Image.Image | None] = {}

    def render(
        self,
        document: RenderDocument,
        *,
        icon_bytes: bytes | None = None,
        profile_image_bytes: bytes | None = None,
        output_path: str | Path | None = None,
    ) -> str:
        """Render a document to a tracked temporary PNG path."""
        measure_image = Image.new("RGB", (1, 1))
        measure = ImageDraw.Draw(measure_image)
        target_icon_width = max(1, min(CONTENT_WIDTH, document.hero_image_width))
        icon = (
            decode_source_image(
                icon_bytes,
                max_side=max(320, target_icon_width),
            )
            if icon_bytes
            else None
        )
        if (
            icon is not None
            and document.hero_image_width > 320
            and icon.width < target_icon_width
        ):
            scale = min(target_icon_width / icon.width, 1_200 / icon.height)
            icon = icon.resize(
                (
                    max(1, round(icon.width * scale)),
                    max(1, round(icon.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        profile_image: Image.Image | None = None
        if profile_image_bytes:
            try:
                profile_image = decode_source_image(
                    profile_image_bytes,
                    max_side=1_600,
                ).convert("RGB")
            except LocalRenderError:
                profile_image = None
        height = self._measure_document(measure, document, icon, profile_image)
        canvas_height = min(MAX_CANVAS_HEIGHT, max(520, height))
        image = Image.new("RGB", (CANVAS_WIDTH, canvas_height), BACKGROUND)
        draw = ImageDraw.Draw(image)
        y, _truncated = self._draw_document(
            draw,
            image,
            document,
            icon,
            profile_image,
        )
        final_height = min(canvas_height, max(520, y + 34))
        if final_height < canvas_height:
            image = image.crop((0, 0, CANVAS_WIDTH, final_height))
        path = Path(output_path) if output_path is not None else temporary_image_path()
        try:
            image.save(path, format="PNG", optimize=True)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise LocalRenderError("本地结果图片保存失败。") from exc
        return str(path)

    def save_source_image(
        self,
        data: bytes,
        *,
        output_path: str | Path | None = None,
    ) -> str:
        """Validate and normalize a downloaded card image to a local PNG."""
        image = decode_source_image(data, max_side=8_192)
        path = Path(output_path) if output_path is not None else temporary_image_path()
        try:
            image.convert("RGB").save(path, format="PNG", optimize=True)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise LocalRenderError("名片图片保存失败。") from exc
        return str(path)

    def _measure_document(
        self,
        draw: ImageDraw.ImageDraw,
        document: RenderDocument,
        icon: Image.Image | None,
        profile_image: Image.Image | None = None,
    ) -> int:
        title_lines = _wrap(draw, document.title, self.title_font, CONTENT_WIDTH)
        subtitle_lines = _wrap(draw, document.subtitle, self.subtitle_font, CONTENT_WIDTH)
        height = 54 + len(title_lines) * 63 + len(subtitle_lines) * 42 + 42
        if icon is not None:
            height += icon.height + 30
        if document.calendar_days:
            height += self._measure_calendar(draw, document.calendar_days)
        if document.line_series:
            height += 492
        if document.map_nodes:
            height += 66 + ceil(len(document.map_nodes) / 10) * 108 + 34
        if document.chart_entries:
            height += 70
            row_height = 92 if document.chart_kind == "comparison" else 78
            height += len(document.chart_entries) * row_height + 42
        for section in document.sections:
            height += 62 if section.title else 18
            if (
                section.profile_layout
                and profile_image is not None
                and len(section.cards) == 1
            ):
                card_width = round(CONTENT_WIDTH * 0.6)
                height += self._measure_compact_card(
                    draw,
                    section.cards[0],
                    card_width,
                    right_column_shift=ARENA_PROFILE_RIGHT_COLUMN_SHIFT,
                ) + 14
            elif section.columns > 1:
                height += self._measure_card_grid(draw, section.cards, section.columns)
            else:
                for card in section.cards:
                    height += self._measure_card(draw, card) + 18
            height += 16
        if document.food_rows:
            height += 62 + 14
            previous_school = ""
            for row in document.food_rows:
                if previous_school and previous_school != row.school:
                    height += 10
                previous_school = row.school
                height += self._measure_food_row(draw, row) + 6
        for group in document.adventure_groups:
            height += self._measure_adventure_group(draw, group)
        for table in document.tables:
            height += 54 if table.title else 14
            height += 48
            height += sum(self._measure_table_row(draw, table, row) for row in table.rows)
            height += 30
        if document.paragraphs:
            height += 20
            for paragraph in document.paragraphs:
                lines = _wrap(draw, paragraph, self.article_font, CONTENT_WIDTH - 40)
                height += max(1, len(lines)) * 41 + 12
        height += 160
        return min(height, MAX_CANVAS_HEIGHT)

    def _measure_table_row(
        self,
        draw: ImageDraw.ImageDraw,
        table: RenderTable,
        row: TableRow,
    ) -> int:
        line_count = 1
        for index, cell in enumerate(row.cells):
            if index >= len(table.column_widths):
                break
            icon_space = 46 if index == 0 and row.icon_asset else 0
            width = max(20, table.column_widths[index] - 18 - icon_space)
            text = f"{cell.accent_text}{cell.text}" if cell.accent_text else cell.text
            line_count = max(line_count, len(_wrap(draw, text, self.table_font, width)))
        return max(54 if row.icon_asset else 44, line_count * 30 + 14)

    def _measure_card(self, draw: ImageDraw.ImageDraw, card: RenderCard) -> int:
        height = 30
        if card.title:
            height += len(
                _wrap(draw, card.title, self.card_title_font, CONTENT_WIDTH - 52)
            ) * 43 + 14
        for row in card.rows:
            if row.inline:
                label_width = draw.textlength(row.label, font=self.label_font)
                value_width = draw.textlength(row.value, font=self.body_font)
                if label_width + value_width + 16 <= CONTENT_WIDTH - 52:
                    height += 43 + 18
                    continue
            label_lines = _wrap(draw, row.label, self.label_font, CONTENT_WIDTH - 52)
            value_lines = _wrap(draw, row.value, self.body_font, CONTENT_WIDTH - 52)
            height += len(label_lines) * 35 + max(1, len(value_lines)) * 43 + 18
        return max(94, height + 10)

    def _measure_calendar(
        self,
        draw: ImageDraw.ImageDraw,
        days: tuple,
    ) -> int:
        row_heights = self._calendar_row_heights(draw, days)
        return 42 + sum(height + 6 for height in row_heights) + 28

    def _calendar_row_heights(
        self,
        draw: ImageDraw.ImageDraw,
        days: tuple,
    ) -> tuple[int, ...]:
        if not days:
            return ()
        leading = (days[0].value.weekday() + 1) % 7
        row_count = ceil((leading + len(days)) / 7)
        heights: list[int] = []
        for row_index in range(row_count):
            required = 148
            for column in range(7):
                item_index = row_index * 7 + column - leading
                if not 0 <= item_index < len(days):
                    continue
                left = MARGIN + round(column * CONTENT_WIDTH / 7)
                right = MARGIN + round((column + 1) * CONTENT_WIDTH / 7)
                width = right - left - 16
                day = days[item_index]
                war_lines = _wrap(draw, day.war, self.calendar_value_font, width)
                battle_lines = _wrap(
                    draw,
                    day.battle,
                    self.calendar_value_font,
                    width,
                )
                cell_height = 42 + 20 + len(war_lines) * 21
                cell_height += 4 + 20 + len(battle_lines) * 21 + 12
                required = max(required, cell_height)
            heights.append(required)
        return tuple(heights)

    def _measure_card_grid(
        self,
        draw: ImageDraw.ImageDraw,
        cards: tuple[RenderCard, ...],
        requested_columns: int,
    ) -> int:
        if not cards:
            return 0
        columns = max(1, min(requested_columns, len(cards)))
        card_width = (CONTENT_WIDTH - (columns - 1) * 14) / columns
        heights = [
            self._measure_compact_card(draw, card, card_width)
            for card in cards
        ]
        total = 0
        for start in range(0, len(heights), columns):
            total += max(heights[start : start + columns]) + 14
        return total

    def _measure_compact_card(
        self,
        draw: ImageDraw.ImageDraw,
        card: RenderCard,
        width: float,
        *,
        right_column_shift: int = 0,
    ) -> int:
        inner_width = max(40, width - 28)
        height = 18
        if card.title or card.rows:
            height += 32
        if len(card.rows) > 1:
            height += 38
        column_width = (inner_width - 10) / 2
        for start in range(1, len(card.rows), 2):
            pair = card.rows[start : start + 2]
            line_count = max(
                len(
                    _wrap(
                        draw,
                        f"{row.label} {row.value}",
                        self.compact_font,
                        column_width
                        if column == 0
                        else max(40, column_width - right_column_shift),
                    )
                )
                for column, row in enumerate(pair)
            )
            height += max(27, line_count * 24 + 3)
        return max(110, height + 18)

    def _measure_food_row(
        self,
        draw: ImageDraw.ImageDraw,
        row: FoodRow,
    ) -> int:
        label_width, item_width = self._food_column_widths()
        label_text_width = label_width - 10
        chunks = max(1, ceil(len(row.items) / 4))
        total = 0
        for chunk_index in range(chunks):
            values = row.items[chunk_index * 4 : chunk_index * 4 + 4]
            total += self._measure_food_chunk(
                draw,
                row,
                values,
                label_text_width,
                item_width,
                show_label=chunk_index == 0,
            )
            if chunk_index + 1 < chunks:
                total += 6
        return total

    def _measure_food_chunk(
        self,
        draw: ImageDraw.ImageDraw,
        row: FoodRow,
        values: tuple[str, ...],
        label_text_width: int,
        item_width: int,
        *,
        show_label: bool,
    ) -> int:
        """Measure one four-item food chunk exactly as it will be drawn."""
        content_height = 0
        if show_label:
            school_lines = _wrap(
                draw,
                row.school,
                self.food_school_font,
                label_text_width,
            )
            kungfu_lines = _wrap(
                draw,
                row.kungfu,
                self.food_item_font,
                label_text_width,
            )
            content_height = len(school_lines) * 28 + len(kungfu_lines) * 27 + 4
        for value in values:
            font, lines = self._layout_food_item(draw, value, item_width)
            content_height = max(
                content_height,
                len(lines) * (getattr(font, "size", 20) + 8),
            )
        return max(68, content_height + 24)

    @staticmethod
    def _food_column_widths() -> tuple[int, int]:
        label_width = 112
        item_width = (CONTENT_WIDTH - label_width - 32) // 4
        return label_width, item_width

    def _layout_food_item(
        self,
        draw: ImageDraw.ImageDraw,
        value: str,
        item_width: int,
    ) -> tuple[ImageFont.FreeTypeFont, list[str]]:
        """Fit a real food label into at most two readable lines when possible."""
        fonts = (
            self.food_item_font,
            self.food_item_small_font,
            self.food_item_compact_font,
        )
        for font in fonts:
            lines = _wrap_food_item(draw, value, font, item_width)
            if len(lines) <= 2:
                return font, lines
        font = fonts[-1]
        return font, _wrap_food_item(draw, value, font, item_width)

    def _measure_adventure_group(
        self,
        draw: ImageDraw.ImageDraw,
        group: AdventureGroup,
    ) -> int:
        if not group.items:
            return 0
        columns = 3
        gap = 18
        width = (CONTENT_WIDTH - gap * (columns - 1)) / columns
        heights = [
            self._measure_adventure_item(draw, item.name, item.trigger_time, width)
            for item in group.items
        ]
        total = 58
        for start in range(0, len(heights), columns):
            total += max(heights[start : start + columns]) + 24
        return total + 14

    def _measure_adventure_item(
        self,
        draw: ImageDraw.ImageDraw,
        name: str,
        trigger_time: str,
        width: float,
    ) -> int:
        text_width = max(30, width - 16)
        time_lines = _wrap(draw, trigger_time, self.adventure_time_font, text_width)
        name_lines = _wrap(draw, name, self.adventure_name_font, text_width)
        return 18 + 132 + 12 + len(time_lines) * 27 + 7 + len(name_lines) * 24 + 14

    def _draw_document(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        document: RenderDocument,
        icon: Image.Image | None,
        profile_image: Image.Image | None = None,
    ) -> tuple[int, bool]:
        y = 48
        bottom_limit = image.height - 145
        title_lines = _wrap(draw, document.title, self.title_font, CONTENT_WIDTH)
        subtitle_lines = _wrap(draw, document.subtitle, self.subtitle_font, CONTENT_WIDTH)
        for line in title_lines:
            draw.text((MARGIN, y), line, font=self.title_font, fill=TEXT)
            y += 63
        for line in subtitle_lines:
            draw.text((MARGIN, y), line, font=self.subtitle_font, fill=MUTED)
            y += 42
        y += 14
        accent_width = max(
            12,
            min(
                CONTENT_WIDTH,
                max(
                    (draw.textlength(line, font=self.subtitle_font) for line in subtitle_lines),
                    default=12,
                ),
            ),
        )
        draw.rounded_rectangle(
            (MARGIN, y, MARGIN + accent_width, y + 7),
            radius=4,
            fill=CINNABAR,
        )
        y += 24
        if icon is not None:
            icon_x = round((CANVAS_WIDTH - icon.width) / 2)
            image.paste(icon, (icon_x, y), icon if icon.mode == "RGBA" else None)
            y += icon.height + 30
        else:
            y += 14

        if document.calendar_days:
            y, truncated = self._draw_calendar(
                draw,
                document.calendar_days,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        if document.line_series:
            y, truncated = self._draw_line_chart(
                draw,
                image,
                document.line_series,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        if document.map_nodes:
            y, truncated = self._draw_snake_map(
                draw,
                image,
                document.map_nodes,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        if document.chart_entries:
            if y >= bottom_limit:
                return self._draw_footer(draw, document, y, True), True
            y, truncated = self._draw_chart(
                draw,
                document.chart_kind,
                document.chart_entries,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        for section in document.sections:
            if section.title:
                if y + 55 >= bottom_limit:
                    return self._draw_footer(draw, document, y, True), True
                draw.text((MARGIN, y), section.title, font=self.section_font, fill=JADE)
                y += 54
            if (
                section.profile_layout
                and profile_image is not None
                and len(section.cards) == 1
            ):
                y, truncated = self._draw_profile_card(
                    draw,
                    image,
                    section.cards[0],
                    profile_image,
                    y,
                    bottom_limit,
                )
                if truncated:
                    return self._draw_footer(draw, document, y, True), True
            elif section.columns > 1:
                y, truncated = self._draw_card_grid(
                    draw,
                    section.cards,
                    section.columns,
                    y,
                    bottom_limit,
                )
                if truncated:
                    return self._draw_footer(draw, document, y, True), True
            else:
                for card in section.cards:
                    card_height = self._measure_card(draw, card)
                    if y + card_height >= bottom_limit:
                        return self._draw_footer(draw, document, y, True), True
                    self._draw_card(draw, card, y, card_height)
                    y += card_height + 18
            y += 16

        if document.food_rows:
            y, truncated = self._draw_food_rows(
                draw,
                document.food_rows,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        for group in document.adventure_groups:
            y, truncated = self._draw_adventure_group(
                draw,
                image,
                group,
                y,
                bottom_limit,
            )
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        for table in document.tables:
            y, truncated = self._draw_table(draw, image, table, y, bottom_limit)
            if truncated:
                return self._draw_footer(draw, document, y, True), True

        if document.paragraphs:
            card_y = y
            y += 26
            positioned_lines: list[tuple[tuple[float, float], str]] = []
            paragraphs = document.paragraphs
            truncated = False
            for paragraph_index, paragraph in enumerate(paragraphs):
                lines = _wrap(draw, paragraph, self.article_font, CONTENT_WIDTH - 40)
                for line in lines:
                    if y + 41 > bottom_limit:
                        truncated = True
                        break
                    positioned_lines.append(((MARGIN + 20, y), line))
                    y += 41
                if truncated:
                    break
                if paragraph_index + 1 < len(paragraphs):
                    if y + 12 > bottom_limit:
                        truncated = True
                        break
                    y += 12
                elif y + 12 <= bottom_limit:
                    y += 12
            draw.rounded_rectangle(
                (MARGIN, card_y, CANVAS_WIDTH - MARGIN, min(y + 8, bottom_limit)),
                radius=20,
                fill=CARD_BACKGROUND,
                outline=BORDER,
                width=2,
            )
            for position, line in positioned_lines:
                draw.text(position, line, font=self.article_font, fill=TEXT)
            if truncated:
                return self._draw_footer(draw, document, y, True), True
            y += 26
        return self._draw_footer(draw, document, y, False), False

    def _draw_card(
        self,
        draw: ImageDraw.ImageDraw,
        card: RenderCard,
        y: int,
        height: int,
    ) -> None:
        left = MARGIN
        right = CANVAS_WIDTH - MARGIN
        draw.rounded_rectangle(
            (left, y, right, y + height),
            radius=20,
            fill=CARD_BACKGROUND,
            outline=BORDER,
            width=2,
        )
        cursor = y + 24
        if card.title:
            for line in _wrap(draw, card.title, self.card_title_font, CONTENT_WIDTH - 52):
                draw.text((left + 26, cursor), line, font=self.card_title_font, fill=TEXT)
                cursor += 43
            cursor += 8
        for row in card.rows:
            if row.inline:
                label_width = draw.textlength(row.label, font=self.label_font)
                value_width = draw.textlength(row.value, font=self.body_font)
                available = CONTENT_WIDTH - 52
                if label_width + value_width + 16 <= available:
                    draw.text(
                        (left + 26, cursor),
                        row.label,
                        font=self.label_font,
                        fill=_safe_color(row.label_color, JADE),
                    )
                    draw.text(
                        (left + 26 + label_width + 16, cursor - 2),
                        row.value,
                        font=self.body_font,
                        fill=_safe_color(row.value_color, TEXT),
                    )
                    cursor += 61
                    continue
            for line in _wrap(draw, row.label, self.label_font, CONTENT_WIDTH - 52):
                draw.text(
                    (left + 26, cursor),
                    line,
                    font=self.label_font,
                    fill=_safe_color(row.label_color, JADE),
                )
                cursor += 35
            for line in _wrap(draw, row.value, self.body_font, CONTENT_WIDTH - 52):
                draw.text(
                    (left + 26, cursor),
                    line,
                    font=self.body_font,
                    fill=_safe_color(row.value_color, TEXT),
                )
                cursor += 43
            cursor += 18

    def _draw_card_grid(
        self,
        draw: ImageDraw.ImageDraw,
        cards: tuple[RenderCard, ...],
        requested_columns: int,
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not cards:
            return y, False
        columns = max(1, min(requested_columns, len(cards)))
        gap = 14
        card_width = (CONTENT_WIDTH - (columns - 1) * gap) / columns
        heights = [
            self._measure_compact_card(draw, card, card_width)
            for card in cards
        ]
        for start in range(0, len(cards), columns):
            row_cards = cards[start : start + columns]
            row_height = max(heights[start : start + columns])
            if y + row_height >= bottom_limit:
                return y, True
            for column, card in enumerate(row_cards):
                left = MARGIN + column * (card_width + gap)
                self._draw_compact_card(
                    draw,
                    card,
                    left,
                    y,
                    card_width,
                    row_height,
                )
            y += row_height + gap
        return y, False

    def _draw_profile_card(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        card: RenderCard,
        profile_image: Image.Image,
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        card_width = round(CONTENT_WIDTH * 0.6)
        gap = 16
        image_width = CONTENT_WIDTH - card_width - gap
        height = self._measure_compact_card(
            draw,
            card,
            card_width,
            right_column_shift=ARENA_PROFILE_RIGHT_COLUMN_SHIFT,
        )
        if y + height >= bottom_limit:
            return y, True
        self._draw_compact_card(
            draw,
            card,
            MARGIN,
            y,
            card_width,
            height,
            right_column_shift=ARENA_PROFILE_RIGHT_COLUMN_SHIFT,
        )
        fitted = ImageOps.fit(
            profile_image,
            (image_width, height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.38),
        )
        mask = Image.new("L", (image_width, height), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            (0, 0, image_width - 1, height - 1),
            radius=18,
            fill=255,
        )
        image_left = MARGIN + card_width + gap
        image.paste(fitted, (image_left, y), mask)
        draw.rounded_rectangle(
            (image_left, y, image_left + image_width, y + height),
            radius=18,
            outline=BORDER,
            width=2,
        )
        return y + height + 14, False

    def _draw_compact_card(
        self,
        draw: ImageDraw.ImageDraw,
        card: RenderCard,
        left: float,
        top: int,
        width: float,
        height: int,
        *,
        right_column_shift: int = 0,
    ) -> None:
        right = left + width
        draw.rounded_rectangle(
            (left, top, right, top + height),
            radius=18,
            fill=CARD_BACKGROUND,
            outline=BORDER,
            width=2,
        )
        cursor = top + 18
        inner_left = left + 14
        inner_right = right - 14
        inner_width = inner_right - inner_left
        column_gap = 10
        column_width = (inner_width - column_gap) / 2
        right_column_left = (
            inner_left + column_width + column_gap + right_column_shift
        )
        right_column_width = max(40, inner_right - right_column_left)
        if card.title:
            draw.text(
                (inner_left, cursor),
                card.title,
                font=self.label_font,
                fill=JADE,
            )
        if card.rows:
            score = card.rows[0]
            draw.text(
                (right_column_left, cursor + 2),
                score.label,
                font=self.compact_font,
                fill=MUTED,
            )
            draw.text(
                (right_column_left, cursor + 26),
                score.value,
                font=self.compact_bold_font,
                fill=TEXT,
            )
            cursor += 70
        elif card.title:
            cursor += 32
        for start in range(1, len(card.rows), 2):
            pair = card.rows[start : start + 2]
            pair_line_count = 1
            for column, row in enumerate(pair):
                cell_left = inner_left if column == 0 else right_column_left
                available_width = (
                    column_width if column == 0 else right_column_width
                )
                lines = _wrap(
                    draw,
                    f"{row.label} {row.value}",
                    self.compact_font,
                    available_width,
                )
                pair_line_count = max(pair_line_count, len(lines))
                line_y = cursor
                for line in lines:
                    draw.text(
                        (cell_left, line_y),
                        line,
                        font=self.compact_font,
                        fill=TEXT,
                    )
                    line_y += 24
            cursor += max(27, pair_line_count * 24 + 3)

    def _draw_food_rows(
        self,
        draw: ImageDraw.ImageDraw,
        rows: tuple[FoodRow, ...],
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not rows:
            return y, False
        if y + 54 >= bottom_limit:
            return y, True
        draw.text((MARGIN, y), "小药一览", font=self.section_font, fill=JADE)
        y += 54
        label_width, item_width = self._food_column_widths()
        gap = 8
        previous_school = ""
        band_index = 0
        for row in rows:
            if previous_school and previous_school != row.school:
                y += 10
                band_index += 1
            previous_school = row.school
            chunks = max(1, ceil(len(row.items) / 4))
            for chunk_index in range(chunks):
                values = row.items[chunk_index * 4 : chunk_index * 4 + 4]
                row_height = self._measure_food_chunk(
                    draw,
                    row,
                    values,
                    label_width - 10,
                    item_width,
                    show_label=chunk_index == 0,
                )
                if y + row_height >= bottom_limit:
                    return y, True
                fill = CARD_BACKGROUND if band_index % 2 == 0 else "#fbf7ef"
                draw.rounded_rectangle(
                    (MARGIN, y, CANVAS_WIDTH - MARGIN, y + row_height),
                    radius=14,
                    fill=fill,
                )
                text_y = y + 12
                if chunk_index == 0:
                    for line in _wrap(
                        draw,
                        row.school,
                        self.food_school_font,
                        label_width - 10,
                    ):
                        draw.text(
                            (MARGIN + 10, text_y),
                            line,
                            font=self.food_school_font,
                            fill=_safe_color(row.school_color, TEXT),
                        )
                        text_y += 28
                    text_y += 4
                    for line in _wrap(
                        draw,
                        row.kungfu,
                        self.food_item_font,
                        label_width - 10,
                    ):
                        draw.text(
                            (MARGIN + 10, text_y),
                            line,
                            font=self.food_item_font,
                            fill=_safe_color(row.kungfu_color, JADE),
                        )
                        text_y += 27
                for column, value in enumerate(values):
                    left = MARGIN + label_width + gap + column * (item_width + gap)
                    item_y = y + 12
                    font, lines = self._layout_food_item(draw, value, item_width)
                    line_height = getattr(font, "size", 20) + 8
                    for line in lines:
                        draw.text(
                            (left, item_y),
                            line,
                            font=font,
                            fill=_safe_color(row.kungfu_color, TEXT),
                        )
                        item_y += line_height
                y += row_height + 6
        return y + 14, False

    def _draw_adventure_group(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        group: AdventureGroup,
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not group.items:
            return y, False
        if y + 54 >= bottom_limit:
            return y, True
        draw.text((MARGIN, y), group.title, font=self.section_font, fill=JADE)
        y += 58
        columns = 3
        gap = 18
        width = (CONTENT_WIDTH - gap * (columns - 1)) / columns
        heights = [
            self._measure_adventure_item(draw, item.name, item.trigger_time, width)
            for item in group.items
        ]
        for start in range(0, len(group.items), columns):
            row_items = group.items[start : start + columns]
            row_height = max(heights[start : start + columns])
            if y + row_height >= bottom_limit:
                return y, True
            for column, item in enumerate(row_items):
                left = MARGIN + column * (width + gap)
                center_x = left + width / 2
                cursor = y + 18
                asset = self._load_asset(item.icon_asset, 132)
                if asset is not None:
                    if max(asset.size) < 132:
                        scale = 132 / max(asset.size)
                        asset = asset.resize(
                            (
                                max(1, round(asset.width * scale)),
                                max(1, round(asset.height * scale)),
                            ),
                            Image.Resampling.LANCZOS,
                        )
                    image.paste(
                        asset,
                        (round(center_x - asset.width / 2), cursor),
                        asset if asset.mode == "RGBA" else None,
                    )
                else:
                    draw.rounded_rectangle(
                        (center_x - 64, cursor, center_x + 64, cursor + 128),
                        radius=14,
                        fill=TRACK,
                    )
                cursor += 144
                for line in _wrap(
                    draw,
                    item.trigger_time,
                    self.adventure_time_font,
                    width - 16,
                ):
                    line_width = draw.textlength(line, font=self.adventure_time_font)
                    draw.text(
                        (center_x - line_width / 2, cursor),
                        line,
                        font=self.adventure_time_font,
                        fill=TEXT,
                    )
                    cursor += 27
                cursor += 7
                for line in _wrap(
                    draw,
                    item.name,
                    self.adventure_name_font,
                    width - 16,
                ):
                    line_width = draw.textlength(line, font=self.adventure_name_font)
                    draw.text(
                        (center_x - line_width / 2, cursor),
                        line,
                        font=self.adventure_name_font,
                        fill=MUTED,
                    )
                    cursor += 24
            y += row_height + 24
        return y + 14, False

    def _draw_calendar(
        self,
        draw: ImageDraw.ImageDraw,
        days: tuple,
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not days:
            return y, False
        leading = (days[0].value.weekday() + 1) % 7
        row_heights = self._calendar_row_heights(draw, days)
        rows = len(row_heights)
        required = 42 + sum(height + 6 for height in row_heights) + 28
        if y + required >= bottom_limit:
            return y, True
        weekdays = ("周日", "周一", "周二", "周三", "周四", "周五", "周六")
        for column, label in enumerate(weekdays):
            left = MARGIN + round(column * CONTENT_WIDTH / 7)
            right = MARGIN + round((column + 1) * CONTENT_WIDTH / 7)
            width = draw.textlength(label, font=self.table_bold_font)
            draw.text(
                (left + (right - left - width) / 2, y),
                label,
                font=self.table_bold_font,
                fill=JADE,
            )
        y += 42
        row_tops: list[int] = []
        row_top = y
        for row_height in row_heights:
            row_tops.append(row_top)
            row_top += row_height + 6
        for position in range(rows * 7):
            row_index, column = divmod(position, 7)
            left = MARGIN + round(column * CONTENT_WIDTH / 7)
            right = MARGIN + round((column + 1) * CONTENT_WIDTH / 7)
            top = row_tops[row_index]
            bottom = top + row_heights[row_index]
            item_index = position - leading
            fill = CARD_BACKGROUND if 0 <= item_index < len(days) else BACKGROUND
            outline = BORDER
            width = 1
            if 0 <= item_index < len(days) and days[item_index].is_today:
                outline = CINNABAR
                width = 3
            draw.rounded_rectangle(
                (left + 2, top, right - 2, bottom),
                radius=10,
                fill=fill,
                outline=outline if 0 <= item_index < len(days) else None,
                width=width,
            )
            if not 0 <= item_index < len(days):
                continue
            day = days[item_index]
            draw.text(
                (left + 9, top + 7),
                str(day.value.day),
                font=self.calendar_day_font,
                fill=TEXT,
            )
            if day.month_label:
                label_width = draw.textlength(day.month_label, font=self.calendar_label_font)
                draw.text(
                    (right - 8 - label_width, top + 10),
                    day.month_label,
                    font=self.calendar_label_font,
                    fill=CINNABAR,
                )
            cursor = top + 42
            cursor = self._draw_calendar_value(
                draw,
                left + 8,
                cursor,
                right - left - 16,
                "大战",
                day.war,
                CINNABAR,
            )
            self._draw_calendar_value(
                draw,
                left + 8,
                cursor + 2,
                right - left - 16,
                "战场",
                day.battle,
                JADE,
            )
        return row_top + 22, False

    def _draw_calendar_value(
        self,
        draw: ImageDraw.ImageDraw,
        x: int,
        y: int,
        width: int,
        label: str,
        value: str,
        color: str,
    ) -> int:
        draw.text((x, y), label, font=self.calendar_label_font, fill=color)
        y += 20
        for line in _wrap(draw, value, self.calendar_value_font, width):
            draw.text((x, y), line, font=self.calendar_value_font, fill=TEXT)
            y += 21
        return y

    def _draw_line_chart(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        series: tuple[LineSeries, ...],
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not series:
            return y, False
        required = 470
        if y + required >= bottom_limit:
            return y, True
        draw.text((MARGIN, y), "平台走势", font=self.section_font, fill=JADE)
        y += 52
        legend_column_width = CONTENT_WIDTH / 3
        for index, item in enumerate(series):
            row, column = divmod(index, 3)
            x = MARGIN + column * legend_column_width
            legend_y = y + row * 28
            draw.line((x, legend_y + 10, x + 25, legend_y + 10), fill=item.color, width=4)
            draw.text((x + 33, legend_y), item.label, font=self.axis_font, fill=TEXT)
        legend_rows = ceil(len(series) / 3)
        chart_top = y + legend_rows * 28 + 30
        chart_bottom = chart_top + 286
        chart_left = MARGIN + 58
        chart_right = CANVAS_WIDTH - MARGIN - 86
        labels = sorted({point.label for item in series for point in item.points})
        values = [point.value for item in series for point in item.points]
        if not labels or not values:
            return chart_bottom + 42, False
        minimum = min(values)
        maximum = max(values)
        padding = max((maximum - minimum) * 0.08, maximum * 0.015, 1.0)
        lower = max(0.0, minimum - padding)
        upper = maximum + padding
        span = max(1.0, upper - lower)
        for tick in range(5):
            ratio = tick / 4
            tick_y = chart_bottom - ratio * (chart_bottom - chart_top)
            value = lower + ratio * span
            draw.line((chart_left, tick_y, chart_right, tick_y), fill=TRACK, width=1)
            label = f"{value:.2f}".rstrip("0").rstrip(".")
            label_width = draw.textlength(label, font=self.axis_font)
            draw.text(
                (chart_left - label_width - 8, tick_y - 10),
                label,
                font=self.axis_font,
                fill=MUTED,
            )
        label_positions = {label: index for index, label in enumerate(labels)}
        x_span = max(1, len(labels) - 1)
        scale = 4
        layer_height = chart_bottom - chart_top + 12
        line_layer = Image.new(
            "RGBA",
            (CANVAS_WIDTH * scale, layer_height * scale),
            (0, 0, 0, 0),
        )
        line_draw = ImageDraw.Draw(line_layer)
        latest: list[tuple[float, float, float, LineSeries]] = []
        for item in series:
            coordinates: list[tuple[float, float]] = []
            for point in item.points:
                x = chart_left + label_positions[point.label] / x_span * (chart_right - chart_left)
                point_y = chart_bottom - (point.value - lower) / span * (chart_bottom - chart_top)
                coordinates.append((x, point_y))
            scaled = [
                (round(x * scale), round((point_y - chart_top) * scale))
                for x, point_y in coordinates
            ]
            if len(coordinates) > 1:
                line_draw.line(scaled, fill=item.color, width=4 * scale, joint="curve")
            for x, point_y in scaled:
                line_draw.ellipse(
                    (
                        x - 4 * scale,
                        point_y - 4 * scale,
                        x + 4 * scale,
                        point_y + 4 * scale,
                    ),
                    fill=item.color,
                )
            if coordinates:
                latest_x, latest_y = coordinates[-1]
                latest.append((latest_y, latest_x, item.points[-1].value, item))
        smoothed = line_layer.resize(
            (CANVAS_WIDTH, layer_height),
            Image.Resampling.LANCZOS,
        )
        image.paste(smoothed, (0, chart_top), smoothed)

        latest.sort(key=lambda entry: entry[0])
        label_gap = 24
        assigned: list[float] = []
        previous = chart_top - label_gap
        for desired_y, _x, _value, _item in latest:
            value_y = max(desired_y, previous + label_gap)
            assigned.append(value_y)
            previous = value_y
        if assigned:
            overflow = max(0.0, assigned[-1] - (chart_bottom - 10))
            assigned = [value - overflow for value in assigned]
            underflow = max(0.0, chart_top + 10 - assigned[0])
            assigned = [value + underflow for value in assigned]
        label_x = chart_right + 12
        for (desired_y, latest_x, value, item), label_y in zip(
            latest,
            assigned,
            strict=True,
        ):
            draw.line(
                (latest_x + 5, desired_y, label_x - 5, label_y),
                fill=item.color,
                width=2,
            )
            value_text = f"{value:.2f}".rstrip("0").rstrip(".")
            draw.text(
                (label_x, label_y - 10),
                value_text,
                font=self.axis_font,
                fill=item.color,
            )
        label_indices = sorted({0, len(labels) - 1, *(round(i * (len(labels) - 1) / 4) for i in range(5))})
        for index in label_indices:
            label = labels[index]
            compact = label[5:] if len(label) >= 10 and label[4] in "-/" else label
            x = chart_left + index / x_span * (chart_right - chart_left)
            label_width = draw.textlength(compact, font=self.axis_font)
            draw.text(
                (x - label_width / 2, chart_bottom + 12),
                compact,
                font=self.axis_font,
                fill=MUTED,
            )
        return chart_bottom + 58, False

    def _draw_snake_map(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        nodes: tuple[MapNode, ...],
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not nodes:
            return y, False
        rows = ceil(len(nodes) / 10)
        required = 58 + rows * 108 + 28
        if y + required >= bottom_limit:
            return y, True
        draw.text((MARGIN, y), "百战路线", font=self.section_font, fill=JADE)
        y += 54
        ordered = sorted(nodes, key=lambda node: node.index)
        centers: list[tuple[float, float]] = []
        placements: list[tuple[MapNode, int, int]] = []
        cell_width = CONTENT_WIDTH / 10
        for position, node in enumerate(ordered):
            row, logical_column = divmod(position, 10)
            column = logical_column if row % 2 == 0 else 9 - logical_column
            left = MARGIN + round(column * cell_width)
            top = y + row * 108
            centers.append((left + cell_width / 2, top + 41))
            placements.append((node, left, top))
        if len(centers) > 1:
            draw.line(centers, fill="#cbbda7", width=5, joint="curve")
        for node, left, top in placements:
            right = MARGIN + round((round((left - MARGIN) / cell_width) + 1) * cell_width)
            draw.rounded_rectangle(
                (left + 3, top + 2, right - 3, top + 98),
                radius=12,
                fill=CARD_BACKGROUND,
                outline=BORDER,
                width=1,
            )
            avatar = self._load_asset(node.icon_asset, 42)
            center_x = left + (right - left) / 2
            if avatar is not None:
                image.paste(
                    avatar,
                    (round(center_x - avatar.width / 2), top + 15),
                    avatar if avatar.mode == "RGBA" else None,
                )
            else:
                draw.ellipse(
                    (center_x - 20, top + 15, center_x + 20, top + 55),
                    fill=TRACK,
                    outline=JADE,
                    width=2,
                )
            draw.text((left + 7, top + 6), str(node.index), font=self.map_index_font, fill=CINNABAR)
            lines = _wrap(draw, node.name, self.map_name_font, right - left - 8)[:2]
            name_y = top + 60
            for line in lines:
                line_width = draw.textlength(line, font=self.map_name_font)
                draw.text(
                    (center_x - line_width / 2, name_y),
                    line,
                    font=self.map_name_font,
                    fill=TEXT,
                )
                name_y += 19
        return y + rows * 108 + 24, False

    def _draw_table(
        self,
        draw: ImageDraw.ImageDraw,
        image: Image.Image,
        table: RenderTable,
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if table.title:
            if y + 52 >= bottom_limit:
                return y, True
            draw.text((MARGIN, y), table.title, font=self.section_font, fill=JADE)
            y += 52
        if len(table.headers) != len(table.column_widths):
            return y, False
        if y + 48 >= bottom_limit:
            return y, True
        x = MARGIN
        for header, width in zip(table.headers, table.column_widths, strict=True):
            draw.rectangle((x, y, x + width, y + 44), fill="#e8e0d2", outline=BORDER)
            draw.text((x + 9, y + 9), header, font=self.table_bold_font, fill=TEXT)
            x += width
        y += 44
        for row in table.rows:
            row_height = self._measure_table_row(draw, table, row)
            if y + row_height >= bottom_limit:
                return y, True
            x = MARGIN
            for index, (cell, width) in enumerate(
                zip(row.cells, table.column_widths, strict=False)
            ):
                draw.rectangle((x, y, x + width, y + row_height), fill=CARD_BACKGROUND, outline=BORDER)
                text_x = x + 9
                if index == 0 and row.icon_asset:
                    asset = self._load_asset(row.icon_asset, 38)
                    if asset is not None:
                        image.paste(
                            asset,
                            (x + 7, y + (row_height - asset.height) // 2),
                            asset if asset.mode == "RGBA" else None,
                        )
                    else:
                        draw.rounded_rectangle(
                            (x + 7, y + (row_height - 36) // 2, x + 43, y + (row_height + 36) // 2),
                            radius=8,
                            fill=TRACK,
                        )
                    text_x += 46
                text_width = max(20, width - (text_x - x) - 8)
                if cell.accent_text:
                    accent_width = draw.textlength(
                        cell.accent_text,
                        font=self.table_bold_font,
                    )
                    remainder_width = draw.textlength(
                        cell.text,
                        font=self.table_font,
                    )
                    if accent_width + remainder_width <= text_width:
                        text_y = y + max(7, (row_height - 30) // 2)
                        draw.text(
                            (text_x, text_y),
                            cell.accent_text,
                            font=self.table_bold_font,
                            fill=_safe_color(cell.accent_color, TEXT),
                        )
                        draw.text(
                            (text_x + accent_width, text_y),
                            cell.text,
                            font=self.table_font,
                            fill=_safe_color(cell.color, TEXT),
                        )
                        x += width
                        continue
                lines = _wrap(draw, cell.text, self.table_font, text_width)
                text_y = y + max(7, (row_height - len(lines) * 30) // 2)
                for line in lines:
                    draw.text(
                        (text_x, text_y),
                        line,
                        font=self.table_font,
                        fill=_safe_color(cell.color, TEXT),
                    )
                    text_y += 30
                x += width
            y += row_height
        return y + 28, False

    def _load_asset(self, relative_name: str, max_side: int) -> Image.Image | None:
        cache_key = (relative_name, max_side)
        if cache_key in self._asset_cache:
            cached = self._asset_cache[cache_key]
            return cached.copy() if cached is not None else None
        candidate = (self.asset_directory / relative_name).resolve()
        try:
            candidate.relative_to(self.asset_directory.resolve())
            with Image.open(candidate) as source:
                source.load()
                asset = source.convert("RGBA")
                asset.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        except (OSError, ValueError):
            self._asset_cache[cache_key] = None
            return None
        self._asset_cache[cache_key] = asset
        return asset.copy()

    def _draw_chart(
        self,
        draw: ImageDraw.ImageDraw,
        kind: str,
        entries: tuple[ChartEntry, ...],
        y: int,
        bottom_limit: int,
    ) -> tuple[int, bool]:
        if not entries:
            return y, False
        values = [entry.value for entry in entries]
        values.extend(
            entry.comparison for entry in entries if entry.comparison is not None
        )
        maximum = max(values) if values else 1
        minimum = min(values) if values else 0
        if kind == "comparison":
            draw.text((MARGIN, y), "● 当前赛季", font=self.small_font, fill=JADE)
            draw.text((MARGIN + 190, y), "● 上赛季", font=self.small_font, fill=CINNABAR)
            y += 52
            span = max(1.0, maximum - minimum)
            for entry in entries:
                if y + 88 >= bottom_limit:
                    return y, True
                draw.text((MARGIN, y), entry.label, font=self.chart_bold_font, fill=TEXT)
                previous = entry.comparison if entry.comparison is not None else entry.value
                delta = previous - entry.value
                change = "持平" if delta == 0 else (f"上升 {delta:g}" if delta > 0 else f"下降 {abs(delta):g}")
                value_text = f"本季 {entry.value:g}{entry.suffix} · 上季 {previous:g}{entry.suffix} · {change}"
                draw.text(
                    (MARGIN + 160, y + 2),
                    value_text,
                    font=self.small_font,
                    fill=MUTED,
                )
                line_y = y + 54
                start = MARGIN + 8
                end = CANVAS_WIDTH - MARGIN - 8
                draw.line((start, line_y, end, line_y), fill=TRACK, width=7)
                current_x = start + int((entry.value - minimum) / span * (end - start))
                previous_x = start + int((previous - minimum) / span * (end - start))
                draw.ellipse((previous_x - 8, line_y - 8, previous_x + 8, line_y + 8), fill=CINNABAR)
                draw.ellipse((current_x - 9, line_y - 9, current_x + 9, line_y + 9), fill=JADE)
                y += 92
        else:
            for entry in entries:
                if y + 74 >= bottom_limit:
                    return y, True
                draw.text((MARGIN, y), entry.label, font=self.chart_font, fill=TEXT)
                value_text = f"胜率 {entry.value:g}{entry.suffix}"
                value_width = draw.textlength(value_text, font=self.chart_bold_font)
                draw.text(
                    (CANVAS_WIDTH - MARGIN - value_width, y),
                    value_text,
                    font=self.chart_bold_font,
                    fill=JADE,
                )
                bar_y = y + 42
                bar_width = CONTENT_WIDTH * (entry.value / maximum if maximum else 0)
                draw.rounded_rectangle(
                    (MARGIN, bar_y, CANVAS_WIDTH - MARGIN, bar_y + 13),
                    radius=7,
                    fill=TRACK,
                )
                draw.rounded_rectangle(
                    (MARGIN, bar_y, MARGIN + max(8, bar_width), bar_y + 13),
                    radius=7,
                    fill=JADE,
                )
                y += 78
        return y + 28, False

    def _draw_footer(
        self,
        draw: ImageDraw.ImageDraw,
        document: RenderDocument,
        y: int,
        truncated: bool,
    ) -> int:
        if truncated:
            notice_y = min(y + 10, MAX_CANVAS_HEIGHT - 135)
            draw.rounded_rectangle(
                (MARGIN, notice_y, CANVAS_WIDTH - MARGIN, notice_y + 54),
                radius=14,
                fill="#f5dfd8",
            )
            draw.text(
                (MARGIN + 18, notice_y + 10),
                "内容过长，已在单图高度上限处截断",
                font=self.small_font,
                fill=CINNABAR,
            )
            footer_y = notice_y + 66
        else:
            footer_y = min(y + 22, MAX_CANVAS_HEIGHT - 55)
        footer = document.footer
        if truncated:
            footer = f"{footer} · 单图已截断"
        draw.text((MARGIN, footer_y), footer, font=self.small_font, fill=MUTED)
        return footer_y + 42


def decode_source_image(data: bytes, *, max_side: int) -> Image.Image:
    """Decode one bounded raster payload and reject decompression bombs."""
    if not data:
        raise LocalRenderError("图片内容为空。")
    try:
        with Image.open(BytesIO(data)) as source:
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise LocalRenderError("图片格式不受支持。")
            width, height = source.size
            source_side_limit = 4_096
            if (
                width <= 0
                or height <= 0
                or width > source_side_limit
                or height > source_side_limit
                or width * height > MAX_SOURCE_PIXELS
            ):
                raise LocalRenderError("图片尺寸超出安全限制。")
            source.seek(0)
            source.load()
            image = source.convert("RGBA")
    except Image.DecompressionBombError as exc:
        raise LocalRenderError("图片尺寸超出安全限制。") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise LocalRenderError("图片内容无法识别。") from exc
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image


def _safe_color(value: str, fallback: str) -> str:
    if (
        isinstance(value, str)
        and len(value) == 7
        and value.startswith("#")
        and all(character in "0123456789abcdefABCDEF" for character in value[1:])
    ):
        return value
    return fallback


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    """Wrap mixed Chinese/Latin text by rendered pixel width."""
    normalized = str(text).replace("\r", "")
    output: list[str] = []
    for paragraph in normalized.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            output.append("")
            continue
        line = ""
        for character in paragraph:
            candidate = f"{line}{character}"
            if line and (
                len(line) >= MAX_WRAP_CHARACTERS
                or draw.textlength(candidate, font=font) > max_width
            ):
                output.append(line.rstrip())
                line = character.lstrip()
            else:
                line = candidate
        if line:
            output.append(line.rstrip())
    return output or [""]


def _wrap_food_item(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
) -> list[str]:
    """Wrap one food item without orphaning closing punctuation."""
    lines = _wrap(draw, text, font, max_width)
    for index in range(1, len(lines)):
        while lines[index].startswith(("）", ")", "】", "]")):
            previous = lines[index - 1]
            if len(previous) <= 1:
                lines[index - 1] = f"{previous}{lines[index][0]}"
                lines[index] = lines[index][1:]
                break
            lines[index - 1] = previous[:-1]
            lines[index] = f"{previous[-1]}{lines[index]}"
    return [line for line in lines if line]


def temporary_image_path() -> Path:
    """Reserve one private-system temporary PNG path for caller-owned work."""
    handle = tempfile.NamedTemporaryFile(prefix="jx3tools_", suffix=".png", delete=False)
    path = Path(handle.name)
    handle.close()
    return path
