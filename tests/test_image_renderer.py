"""Verify local raster safety and the approved mobile canvas."""

from __future__ import annotations

from datetime import date, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast

import pytest
from astrbot_plugin_jx3tools.core.game_data import fixed_asset_name
from astrbot_plugin_jx3tools.presentation import image_renderer
from astrbot_plugin_jx3tools.presentation.image_renderer import (
    ARENA_PROFILE_RIGHT_COLUMN_SHIFT,
    CANVAS_WIDTH,
    CONTENT_WIDTH,
    MARGIN,
    MAX_CANVAS_HEIGHT,
    FontPaths,
    LocalImageRenderer,
    LocalRenderError,
    _wrap,
    _wrap_food_item,
    decode_source_image,
)
from astrbot_plugin_jx3tools.presentation.rendering import (
    AdventureGroup,
    AdventureItem,
    CalendarDay,
    FoodRow,
    LinePoint,
    LineSeries,
    MapNode,
    RenderCard,
    RenderDocument,
    RenderRow,
    RenderSection,
    RenderTable,
    TableCell,
    TableRow,
)
from PIL import Image, ImageDraw


def _private_font_paths() -> FontPaths | None:
    candidates = (
        Path("/AstrBot/data/plugin_data/astrbot_plugin_jx3tools/fonts"),
        Path(__file__).resolve().parents[3]
        / "plugin_data"
        / "astrbot_plugin_jx3tools"
        / "fonts",
    )
    return next(
        (FontPaths.from_directory(path) for path in candidates if path.is_dir()),
        None,
    )


def test_asset_directory_stays_at_plugin_root() -> None:
    assert image_renderer.ASSET_DIRECTORY == (
        Path(__file__).resolve().parents[1] / "assets"
    )


def test_missing_fixed_asset_uses_safe_fallback(tmp_path: Path) -> None:
    renderer = object.__new__(LocalImageRenderer)
    renderer.asset_directory = tmp_path / "assets"
    renderer._asset_cache = {}

    assert renderer._load_asset("adventures/missing.png", 132) is None


def test_source_image_accepts_raster_and_rejects_unknown_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Image.new("RGB", (80, 60), "red")
    buffer = BytesIO()
    source.save(buffer, format="PNG")

    decoded = decode_source_image(buffer.getvalue(), max_side=160)

    assert decoded.size == (80, 60)
    with pytest.raises(LocalRenderError, match="无法识别"):
        decode_source_image(b"not-an-image", max_side=160)

    large_icon = Image.new("RGB", (512, 256), "blue")
    large_buffer = BytesIO()
    large_icon.save(large_buffer, format="PNG")
    thumbnail = decode_source_image(large_buffer.getvalue(), max_side=160)
    assert thumbnail.size == (160, 80)

    wide_thumbnail = decode_source_image(large_buffer.getvalue(), max_side=480)
    assert wide_thumbnail.size == (480, 240)

    def raise_decompression_bomb(*_args: object, **_kwargs: object) -> None:
        raise Image.DecompressionBombError("oversized image")

    monkeypatch.setattr(image_renderer.Image, "open", raise_decompression_bomb)
    with pytest.raises(LocalRenderError, match="尺寸超出安全限制"):
        decode_source_image(buffer.getvalue(), max_side=160)


def test_canvas_and_zero_width_wrapping_have_fixed_resource_bounds() -> None:
    class CountingDraw:
        def __init__(self) -> None:
            self.calls = 0

        def textlength(self, _text: str, *, font: Any) -> float:
            self.calls += 1
            return 0.0

    draw = CountingDraw()
    lines = _wrap(draw, "\u0301" * 4_096, cast(Any, object()), 100)

    assert MAX_CANVAS_HEIGHT == 12_000
    assert len(lines) == 16
    assert all(len(line) <= 256 for line in lines)
    assert draw.calls == 4_096 - len(lines)


def test_private_alibaba_fonts_render_a_720px_mobile_image() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    output = Path(
        renderer.render(
            RenderDocument(
                title="移动端排版验证",
                subtitle="阿里巴巴普惠体 3 本地渲染",
                paragraphs=("正文信息需要在手机上保持清晰易读。",),
            )
        )
    )
    try:
        with Image.open(output) as image:
            assert image.width == CANVAS_WIDTH
            assert image.height >= 520
    finally:
        output.unlink(missing_ok=True)


def test_specialized_calendar_table_line_and_snake_layouts_render_fully() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    start = date(2026, 7, 5)
    document = RenderDocument(
        title="综合布局验证",
        subtitle="动态副标题宽度",
        calendar_days=tuple(
            CalendarDay(start + timedelta(days=index), "大战", "战场")
            for index in range(14)
        ),
        line_series=(
            LineSeries(
                "万宝楼",
                "#3f766a",
                tuple(LinePoint(f"07-{index:02d}", 70 + index) for index in range(1, 8)),
            ),
        ),
        map_nodes=tuple(
            MapNode(index, "卫栖梧", fixed_asset_name("bosses", "卫栖梧"))
            for index in range(1, 21)
        ),
        tables=(
            RenderTable(
                "奇遇记录",
                ("奇遇", "触发时间"),
                (
                    TableRow(
                        (TableCell("茶馆奇缘"), TableCell("2026-07-19 09:00:00")),
                        fixed_asset_name("adventures", "茶馆奇缘"),
                    ),
                ),
                (330, 294),
            ),
        ),
    )
    output = Path(renderer.render(document))
    try:
        with Image.open(output) as image:
            assert image.width == CANVAS_WIDTH
            assert image.height > 1_500
            assert image.height < 50_000
    finally:
        output.unlink(missing_ok=True)


def test_feedback_grids_expand_and_hero_image_sits_below_accent() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    start = date(2026, 7, 19)
    short_calendar = RenderDocument(
        title="月历",
        subtitle="短内容",
        calendar_days=tuple(
            CalendarDay(start + timedelta(days=index), "大战", "战场")
            for index in range(7)
        ),
    )
    long_calendar = RenderDocument(
        title="月历",
        subtitle="长内容",
        calendar_days=tuple(
            CalendarDay(
                start + timedelta(days=index),
                "英雄河西瀚漠岑寂别苑",
                "云湖天池十二连环坞",
            )
            for index in range(7)
        ),
        food_rows=(
            FoodRow(
                "天策",
                "傲血战意",
                tuple(f"小药{index}（属性提升）" for index in range(5)),
                "#ec4b2c",
                "#ec4b2c",
            ),
        ),
        adventure_groups=(
            AdventureGroup(
                "普通奇遇",
                tuple(
                    AdventureItem(
                        "茶馆奇缘",
                        "2026-07-19 09:00:00",
                        fixed_asset_name("adventures", "茶馆奇缘"),
                    )
                    for _ in range(4)
                ),
            ),
        ),
    )
    source = Image.new("RGB", (480, 240), "#4d78a8")
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    short_output = Path(renderer.render(short_calendar))
    long_output = Path(renderer.render(long_calendar, icon_bytes=buffer.getvalue()))
    wide_hero = RenderDocument(
        title="物品搜索",
        subtitle="游戏商品信息",
        hero_image_width=600,
    )
    small_source = Image.new("RGB", (100, 100), "#4d78a8")
    small_buffer = BytesIO()
    small_source.save(small_buffer, format="PNG")
    wide_output = Path(renderer.render(wide_hero, icon_bytes=small_buffer.getvalue()))
    try:
        with (
            Image.open(short_output) as short_image,
            Image.open(long_output) as long_image,
            Image.open(wide_output) as wide_image,
        ):
            assert long_image.height > short_image.height + 500
            assert long_image.getpixel((360, 250)) == (77, 120, 168)
            assert wide_image.getpixel((60, 250)) == (77, 120, 168)

        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        wrapped = _wrap_food_item(
            measure,
            "非常长的小药名称（属性提升）",
            renderer.food_item_font,
            80,
        )
        assert all(not line.startswith("）") for line in wrapped)
        assert wrapped[-1] != "）"
    finally:
        short_output.unlink(missing_ok=True)
        long_output.unlink(missing_ok=True)
        wide_output.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "paragraphs",
    (
        ("超长技改正文" * 1_000,),
        tuple(f"第{index}段 " + "技改说明" * 60 for index in range(30)),
    ),
)
def test_overlong_article_keeps_visible_body_before_truncation(
    monkeypatch: pytest.MonkeyPatch,
    paragraphs: tuple[str, ...],
) -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    monkeypatch.setattr(image_renderer, "MAX_CANVAS_HEIGHT", 1_800)
    renderer = LocalImageRenderer(paths)

    output = Path(
        renderer.render(
            RenderDocument(
                title="技改",
                subtitle="超长正文截断验证",
                paragraphs=paragraphs,
                footer="内容来源剑网 3 官网",
            )
        )
    )
    try:
        with Image.open(output) as image:
            assert image.height > 1_500
            body = image.crop((MARGIN + 20, 280, CANVAS_WIDTH - MARGIN - 20, 1_200))
            red_channel = body.convert("RGB").histogram()[:256]
            dark_pixels = sum(red_channel[:190])
            assert dark_pixels > 500
    finally:
        output.unlink(missing_ok=True)


def test_real_long_food_names_use_at_most_two_lines() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    _, item_width = renderer._food_column_widths()

    font, lines = renderer._layout_food_item(
        measure,
        "风语·上品亢龙散（外功）",
        item_width,
    )
    short_font, short_lines = renderer._layout_food_item(
        measure,
        "大力丸（力道）",
        item_width,
    )

    assert len(lines) <= 2
    assert all(measure.textlength(line, font=font) <= item_width for line in lines)
    assert getattr(font, "size", 0) >= 16
    assert getattr(short_font, "size", 0) == 20
    assert len(short_lines) <= 2


def test_measured_multi_chunk_food_rows_do_not_report_false_truncation() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    document = RenderDocument(
        title="小药",
        subtitle="多行小药高度验证",
        food_rows=tuple(
            FoodRow(
                f"门派{index}",
                f"心法{index}",
                tuple(f"风语·上品亢龙散{item}（外功）" for item in range(5)),
                "#3f766a",
                "#3f766a",
            )
            for index in range(10)
        ),
    )
    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    height = renderer._measure_document(measure, document, None)
    image = Image.new("RGB", (CANVAS_WIDTH, height))

    _y, truncated = renderer._draw_document(
        ImageDraw.Draw(image),
        image,
        document,
        None,
    )

    assert not truncated


def test_arena_right_column_labels_share_one_left_edge() -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    delegate = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    class RecordingDraw:
        def __init__(self) -> None:
            self.positions: dict[str, tuple[float, float]] = {}

        def rounded_rectangle(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def text(self, xy: tuple[float, float], value: str, **_kwargs: Any) -> None:
            self.positions[value] = xy

        def textlength(self, value: str, **kwargs: Any) -> float:
            return delegate.textlength(value, **kwargs)

    draw = RecordingDraw()
    card = RenderCard(
        "3V3",
        (
            RenderRow("当前积分", "2200"),
            RenderRow("段位", "12"),
            RenderRow("排名", "10"),
            RenderRow("战绩", "8胜 / 10场"),
            RenderRow("MVP", "3"),
        ),
    )
    width = round(CONTENT_WIDTH * 0.6)
    renderer._draw_compact_card(
        cast(Any, draw),
        card,
        MARGIN,
        0,
        width,
        180,
        right_column_shift=ARENA_PROFILE_RIGHT_COLUMN_SHIFT,
    )

    assert draw.positions["当前积分"][0] == pytest.approx(
        draw.positions["排名 10"][0]
    )
    assert draw.positions["当前积分"][0] == pytest.approx(
        draw.positions["MVP 3"][0]
    )
    expected_left = (
        MARGIN
        + 14
        + ((width - 28 - 10) / 2)
        + 10
        + ARENA_PROFILE_RIGHT_COLUMN_SHIFT
    )
    assert draw.positions["当前积分"][0] == pytest.approx(expected_left)


def test_single_arena_card_uses_profile_image_in_the_right_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _private_font_paths()
    if paths is None or not paths.available:
        pytest.skip("Private Alibaba PuHuiTi files are not present in this test runtime")
    renderer = LocalImageRenderer(paths)
    right_column_shifts: list[int] = []
    draw_compact_card = renderer._draw_compact_card

    def record_compact_card(*args: Any, right_column_shift: int = 0) -> None:
        right_column_shifts.append(right_column_shift)
        draw_compact_card(
            *args,
            right_column_shift=right_column_shift,
        )

    monkeypatch.setattr(renderer, "_draw_compact_card", record_compact_card)
    profile_color = (77, 120, 168)
    source = Image.new("RGB", (640, 360), profile_color)
    buffer = BytesIO()
    source.save(buffer, format="PNG")
    document = RenderDocument(
        title="名剑战绩",
        subtitle="双线区-天鹅坪 · 侠士 · 万花",
        sections=(
            RenderSection(
                "赛季表现",
                (
                    RenderCard(
                        "3V3",
                        (
                            RenderRow("当前积分", "2200"),
                            RenderRow("段位", "12"),
                            RenderRow("排名", "10"),
                            RenderRow("战绩", "8胜 / 10场"),
                            RenderRow("MVP", "3"),
                        ),
                    ),
                ),
                columns=3,
                profile_layout=True,
            ),
        ),
    )

    output = Path(
        renderer.render(
            document,
            profile_image_bytes=buffer.getvalue(),
        )
    )
    fallback = Path(renderer.render(document, profile_image_bytes=b"not-an-image"))
    try:
        with Image.open(output) as image:
            colored = [
                (x, y)
                for y in range(image.height)
                for x in range(image.width)
                if image.getpixel((x, y)) == profile_color
            ]
            assert len(colored) > 10_000
            assert min(x for x, _y in colored) >= (
                MARGIN + round(CONTENT_WIDTH * 0.6) + 16
            )
            assert max(x for x, _y in colored) >= CANVAS_WIDTH - MARGIN - 4
        assert fallback.is_file()
        assert right_column_shifts == [ARENA_PROFILE_RIGHT_COLUMN_SHIFT, 0]
    finally:
        output.unlink(missing_ok=True)
        fallback.unlink(missing_ok=True)
