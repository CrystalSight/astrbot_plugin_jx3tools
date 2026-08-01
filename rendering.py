"""Normalize JX3API payloads into safe Chinese text and render documents."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from html.parser import HTMLParser
from statistics import median
from typing import Any

from .endpoints import EndpointSpec
from .game_data import (
    KUNGFU_COLORS,
    KUNGFU_SCHOOLS,
    SALE_LABELS,
    SCHOOL_COLORS,
    SCHOOL_KUNGFU_ORDER,
    fixed_asset_name,
)

BEIJING = timezone(timedelta(hours=8))
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)
OMITTED_FIELDS = {
    "avatarUrl",
    "forceIcon",
    "icon",
    "id",
    "logoUrl",
    "showAvatar",
    "showHash",
    "token",
    "url",
    "view",
}
FIELD_LABELS = {
    "activity": "活动",
    "alias": "别名",
    "answer": "答案",
    "battle": "战场",
    "bodyName": "体型",
    "boss": "首领",
    "campName": "阵营",
    "camp_name": "阵营",
    "card": "小周常",
    "castle": "据点",
    "cdtn": "条件",
    "class": "分类",
    "color": "品质",
    "content": "内容",
    "context": "内容",
    "date": "日期",
    "day": "日期",
    "desc": "说明",
    "description": "说明",
    "draw": "美人图",
    "end": "结束",
    "end_time": "结束时间",
    "equip_score": "装备分数",
    "event": "奇遇",
    "force": "门派",
    "forceName": "门派",
    "horse": "马匹",
    "item_amount": "数量",
    "item_name": "物品",
    "kungfu": "心法",
    "leader": "首领",
    "level": "等级",
    "luck": "福缘宠物",
    "map": "地图",
    "map_name": "地图",
    "max_level": "最高层数",
    "name": "名称",
    "node": "方位",
    "note": "备注",
    "orecar": "阵营日常",
    "question": "题目",
    "ranking": "排名",
    "roleName": "角色名",
    "role_name": "角色名",
    "school": "门派事件",
    "site": "位置",
    "score": "分数",
    "server": "服务器",
    "serverName": "服务器",
    "skill_count": "技能数量",
    "skill_energy": "精力",
    "skill_name": "技能",
    "skill_stamina": "耐力",
    "stage": "阶段",
    "start": "开始",
    "start_time": "开始时间",
    "status": "状态",
    "subclass": "子分类",
    "text": "内容",
    "time": "时间",
    "title": "标题",
    "tongName": "帮会",
    "total_score": "总分",
    "type": "类型",
    "update_time": "更新时间",
    "value": "数值",
    "war": "大战",
    "week": "星期",
    "wblalias": "万宝楼别名",
    "zone": "大区",
    "zoneName": "大区",
}


@dataclass(frozen=True, slots=True)
class RenderRow:
    """One label/value row."""

    label: str
    value: str
    label_color: str = ""
    value_color: str = ""
    inline: bool = False


@dataclass(frozen=True, slots=True)
class RenderCard:
    """One mobile single-column information card."""

    title: str
    rows: tuple[RenderRow, ...]


@dataclass(frozen=True, slots=True)
class RenderSection:
    """A titled group of cards."""

    title: str
    cards: tuple[RenderCard, ...]
    columns: int = 1
    profile_layout: bool = False


@dataclass(frozen=True, slots=True)
class ChartEntry:
    """One bar or comparison row."""

    label: str
    value: float
    comparison: float | None = None
    suffix: str = ""


@dataclass(frozen=True, slots=True)
class CalendarDay:
    """One day in the Sunday-first activity calendar."""

    value: date
    war: str
    battle: str
    month_label: str = ""
    is_today: bool = False


@dataclass(frozen=True, slots=True)
class TableCell:
    """One compact table cell."""

    text: str
    color: str = ""
    accent_text: str = ""
    accent_color: str = ""


@dataclass(frozen=True, slots=True)
class TableRow:
    """One compact table row with an optional fixed local icon."""

    cells: tuple[TableCell, ...]
    icon_asset: str = ""


@dataclass(frozen=True, slots=True)
class RenderTable:
    """One bounded table block."""

    title: str
    headers: tuple[str, ...]
    rows: tuple[TableRow, ...]
    column_widths: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class LinePoint:
    """One dated value in a line series."""

    label: str
    value: float


@dataclass(frozen=True, slots=True)
class LineSeries:
    """One named line with a fixed presentation color."""

    label: str
    color: str
    points: tuple[LinePoint, ...]


@dataclass(frozen=True, slots=True)
class MapNode:
    """One node in the ten-column Baizhan snake map."""

    index: int
    name: str
    icon_asset: str


@dataclass(frozen=True, slots=True)
class FoodRow:
    """One borderless school/kungfu row followed by four item columns."""

    school: str
    kungfu: str
    items: tuple[str, ...]
    school_color: str
    kungfu_color: str


@dataclass(frozen=True, slots=True)
class AdventureItem:
    """One vertically stacked adventure icon, trigger time, and name."""

    name: str
    trigger_time: str
    icon_asset: str


@dataclass(frozen=True, slots=True)
class AdventureGroup:
    """One titled borderless grid of adventure items."""

    title: str
    items: tuple[AdventureItem, ...]


@dataclass(frozen=True, slots=True)
class RenderDocument:
    """Stable local Pillow rendering contract."""

    title: str
    subtitle: str
    sections: tuple[RenderSection, ...] = ()
    paragraphs: tuple[str, ...] = ()
    chart_kind: str = ""
    chart_entries: tuple[ChartEntry, ...] = ()
    calendar_days: tuple[CalendarDay, ...] = ()
    tables: tuple[RenderTable, ...] = ()
    line_series: tuple[LineSeries, ...] = ()
    map_nodes: tuple[MapNode, ...] = ()
    food_rows: tuple[FoodRow, ...] = ()
    adventure_groups: tuple[AdventureGroup, ...] = ()
    footer: str = "数据来源 JX3API · 结果仅供游戏辅助参考"
    icon_url: str = ""
    hero_image_width: int = 320


def format_text(
    endpoint: EndpointSpec,
    data: Any,
    *,
    max_items: int,
    max_characters: int = 1_500,
    document: RenderDocument | None = None,
) -> str:
    """Create a bounded, URL-free text result."""
    if endpoint.key in {"saohua.random", "saohua.content"}:
        value = data.get("text", "") if isinstance(data, Mapping) else data
        return _scalar(value)
    if endpoint.key == "mech.calculator":
        return _mech_text(data)
    if endpoint.key in {"chitu.records", "chitu.week_records"} and not data:
        period = "今日" if endpoint.key == "chitu.records" else "本周"
        return f"{period}暂无赤兔记录。"
    if endpoint.key == "status.check":
        return _status_text(data)
    if endpoint.output == "card":
        return _card_text(data)

    render_document = document or build_document(endpoint, data, max_items=max_items)
    lines = [f"【{render_document.title}】"]
    for section in render_document.sections:
        if section.title:
            lines.append(f"〔{section.title}〕")
        for card in section.cards[:max_items]:
            if card.title:
                lines.append(card.title)
            lines.extend(f"{row.label}：{row.value}" for row in card.rows)
    if render_document.calendar_days:
        lines.extend(
            f"{day.value.isoformat()} 大战：{day.war}；战场：{day.battle}"
            for day in render_document.calendar_days
        )
    for entry in render_document.chart_entries:
        lines.append(f"{entry.label}：{entry.value:g}{entry.suffix}")
    for series in render_document.line_series:
        values = "、".join(f"{point.label} {point.value:g}" for point in series.points)
        lines.append(f"{series.label}：{values}")
    for table in render_document.tables:
        if table.title:
            lines.append(f"〔{table.title}〕")
        lines.append(" | ".join(table.headers))
        lines.extend(" | ".join(cell.text for cell in row.cells) for row in table.rows)
    if render_document.map_nodes:
        lines.extend(
            f"{node.index}. {node.name}" for node in render_document.map_nodes
        )
    lines.extend(render_document.paragraphs)
    text = "\n".join(lines)
    if len(text) > max_characters:
        return f"{text[: max_characters - 18].rstrip()}\n……内容已截断"
    return text


def build_document(
    endpoint: EndpointSpec,
    data: Any,
    *,
    max_items: int,
) -> RenderDocument:
    """Build the endpoint-specific local rendering contract."""
    builders = {
        "active.calendar": _daily_document,
        "active.list_calendar": _monthly_document,
        "active.celebs": _celebs_document,
        "exam.search": _exam_document,
        "active.monster": _monster_document,
        "school.foods": _foods_document,
        "role.detail": _role_document,
        "school.matrix": _matrix_document,
        "event.records": _event_records_document,
        "arena.recent": _arena_recent_document,
        "trade.demon": _gold_document,
        "smite.records": _smite_document,
        "ranch.records": _ranch_document,
        "trade.item_search": _item_search_document,
        "trade.item_records": _item_records_document,
        "role.monster": _role_monster_document,
        "mech.calculator": _mech_document,
    }
    builder = builders.get(endpoint.key)
    if builder is not None:
        return builder(endpoint, data, max_items)
    return _generic_document(endpoint, data, max_items)


def build_article_document(article: Mapping[str, str]) -> RenderDocument:
    """Extract safe text blocks from an official article response."""
    parser = _ArticleTextParser()
    parser.feed(article.get("content", ""))
    parser.close()
    paragraphs = tuple(parser.paragraphs)
    if not paragraphs:
        paragraphs = ("正文暂不可用。",)
    return RenderDocument(
        title=article.get("title", "剑网 3 资讯")[:120],
        subtitle=article.get("date", ""),
        paragraphs=paragraphs,
        footer="内容来源剑网 3 官网",
    )


def card_identity(data: Any) -> tuple[str, str, str]:
    """Return display server, role name, and source image URL for a card."""
    if not isinstance(data, Mapping):
        return "-", "-", ""
    server = _server_label(data)
    role = _scalar(data.get("roleName", data.get("name", "-")))
    url = data.get("showAvatar", "")
    return server, role, url if isinstance(url, str) else ""


def _daily_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    rows: list[RenderRow] = []
    if data.get("date") or data.get("week"):
        rows.append(
            RenderRow(
                "日期",
                " ".join(
                    part
                    for part in (_scalar(data.get("date")), _scalar(data.get("week")))
                    if part != "-"
                ),
            )
        )
    for key, label in (
        ("war", "大战"),
        ("battle", "战场"),
        ("orecar", "阵营日常"),
        ("school", "门派事件"),
        ("draw", "美人图"),
        ("luck", "福缘宠物"),
        ("card", "小周常"),
    ):
        if key in data:
            rows.append(RenderRow(label, _multiline(data[key])))
    team = data.get("team")
    if isinstance(team, Sequence) and not isinstance(team, (str, bytes, bytearray)):
        if len(team) > 0:
            rows.append(RenderRow("武林通鉴·公共任务", _multiline(team[0])))
        if len(team) > 1:
            rows.append(RenderRow("大周常", _multiline(team[1])))
    return RenderDocument(
        title=endpoint.name,
        subtitle=endpoint.description,
        sections=(RenderSection("今日安排", (RenderCard("", tuple(rows)),)),),
    )


def _monthly_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 31)
    items = data.get("data", [])
    parsed: list[tuple[date, Mapping[Any, Any]]] = []
    if isinstance(items, Sequence) and not isinstance(items, (str, bytes, bytearray)):
        for item in items[:31]:
            if not isinstance(item, Mapping):
                continue
            value = _calendar_date(item)
            if value is not None:
                parsed.append((value, item))
    parsed.sort(key=lambda pair: pair[0])
    today_value = _calendar_date(data.get("today"))
    days: list[CalendarDay] = []
    for index, (value, item) in enumerate(parsed):
        before = parsed[index - 1][0] if index else None
        after = parsed[index + 1][0] if index + 1 < len(parsed) else None
        boundary = (
            before is None
            or after is None
            or before.month != value.month
            or after.month != value.month
        )
        days.append(
            CalendarDay(
                value=value,
                war=_scalar(item.get("war")),
                battle=_scalar(item.get("battle")),
                month_label=f"{value.month}月" if boundary else "",
                is_today=value == today_value,
            )
        )
    years = sorted({day.value.year for day in days})
    year_label = " / ".join(str(year) for year in years) if years else "活动月历"
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"{year_label} · 前后各 15 天",
        calendar_days=tuple(days),
    )


def _celebs_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    records = data if isinstance(data, Sequence) else ()
    cards: list[RenderCard] = []
    for item in records[:3]:
        if not isinstance(item, Mapping):
            continue
        cards.append(
            RenderCard(
                _scalar(item.get("map", item.get("name", "行侠事件"))),
                tuple(
                    row
                    for row in (
                        RenderRow("阶段", _scalar(item.get("stage"))),
                        RenderRow("位置", _scalar(item.get("site"))),
                        RenderRow("说明", _scalar(item.get("desc"))),
                        RenderRow("时间", _beijing_time(item.get("time"))),
                    )
                    if row.value != "-"
                ),
            )
        )
    return RenderDocument(
        title=endpoint.name,
        subtitle="匹配度最高的 3 条行侠事件",
        sections=(RenderSection("查询结果", tuple(cards)),),
    )


def _exam_document(
    endpoint: EndpointSpec,
    data: Any,
    max_items: int,
) -> RenderDocument:
    if isinstance(data, Mapping):
        records: Sequence[Any] = (data,)
    elif isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        records = data
    else:
        records = ()
    cards: list[RenderCard] = []
    for item in records[:max_items]:
        if not isinstance(item, Mapping):
            continue
        cards.append(
            RenderCard(
                _scalar(item.get("question", item.get("subject", "科举题目"))),
                tuple(
                    row
                    for row in (
                        RenderRow("答案", _scalar(item.get("answer"))),
                        RenderRow("类型", _scalar(item.get("type"))),
                    )
                    if row.value != "-"
                ),
            )
        )
    return RenderDocument(
        title=endpoint.name,
        subtitle="支持题目原文、模糊词和拼音首字母",
        sections=(RenderSection("题库匹配", tuple(cards)),),
    )


def _monster_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 100)
    nodes: list[MapNode] = []
    bosses = data.get("list", [])
    if isinstance(bosses, Sequence) and not isinstance(
        bosses,
        (str, bytes, bytearray),
    ):
        for fallback_index, item in enumerate(bosses[:100], start=1):
            if not isinstance(item, Mapping):
                continue
            name = _scalar(item.get("name", "首领"))
            raw_index = item.get("index", fallback_index)
            try:
                index = int(raw_index)
            except (TypeError, ValueError):
                index = fallback_index
            nodes.append(
                MapNode(
                    index=index,
                    name=name,
                    icon_asset=fixed_asset_name("bosses", name),
                )
            )
    start = _beijing_time(data.get("start"))
    end = _beijing_time(data.get("end"))
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"{start} – {end}",
        map_nodes=tuple(nodes),
    )


def _foods_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes, bytearray)):
        return _generic_document(endpoint, data, 100)
    grouped: dict[tuple[str, str], list[str]] = defaultdict(list)
    grouped_seen: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in data:
        if not isinstance(item, Mapping):
            continue
        kungfu = _scalar(item.get("kungfu", "其他"))
        school = _scalar(item.get("school", KUNGFU_SCHOOLS.get(kungfu, "其他")))
        name = _scalar(item.get("name", "小药"))
        detail = _scalar(item.get("boost", item.get("desc", "-")))
        value = name if detail == "-" else f"{name}（{detail}）"
        key = (school, kungfu)
        if value not in grouped_seen[key]:
            grouped_seen[key].add(value)
            grouped[key].append(value)

    food_rows: list[FoodRow] = []
    known = {(school, kungfu) for school, kungfus in SCHOOL_KUNGFU_ORDER for kungfu in kungfus}
    for school, kungfus in SCHOOL_KUNGFU_ORDER:
        for kungfu in kungfus:
            values = grouped.get((school, kungfu))
            if not values:
                continue
            food_rows.append(
                FoodRow(
                    school=school,
                    kungfu=kungfu,
                    items=tuple(values),
                    school_color=SCHOOL_COLORS.get(school, ""),
                    kungfu_color=KUNGFU_COLORS.get(
                        kungfu,
                        SCHOOL_COLORS.get(school, ""),
                    ),
                )
            )
    for (school, kungfu), values in grouped.items():
        if (school, kungfu) in known:
            continue
        color = SCHOOL_COLORS.get(school, "")
        food_rows.append(
            FoodRow(
                school=school,
                kungfu=kungfu,
                items=tuple(values),
                school_color=color,
                kungfu_color=KUNGFU_COLORS.get(kungfu, color),
            )
        )
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"共 {len(data)} 条门派与心法小药数据",
        food_rows=tuple(food_rows),
    )


def _role_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    rows = (
        RenderRow("区服", _server_label(data)),
        RenderRow("角色名", _scalar(data.get("roleName"))),
        RenderRow("角色 ID", _scalar(data.get("roleId"))),
        RenderRow("全局 ID", _scalar(data.get("globalId"))),
        RenderRow("门派", _scalar(data.get("forceName"))),
        RenderRow("体型", _scalar(data.get("bodyName"))),
        RenderRow("帮会", _scalar(data.get("tongName"))),
        RenderRow("阵营", _scalar(data.get("campName"))),
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle="角色基础资料",
        sections=(RenderSection("角色信息", (RenderCard("", rows),)),),
    )


def _matrix_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    effects = data.get("data", [])
    effect_rows: list[RenderRow] = []
    if isinstance(effects, Sequence) and not isinstance(effects, (str, bytes, bytearray)):
        valid = [
            item
            for item in effects
            if isinstance(item, Mapping)
            and isinstance(item.get("level"), int)
            and 1 <= item["level"] <= 6
        ]
        for item in sorted(valid, key=lambda value: int(value["level"])):
            desc = _scalar(item.get("desc"))
            effect_rows.append(RenderRow(str(item["level"]), desc))
    rows = (
        RenderRow("心法", _scalar(data.get("name"))),
        RenderRow("阵眼名称", _scalar(data.get("skillName"))),
        *effect_rows,
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle=endpoint.description,
        sections=(RenderSection("阵眼详情", (RenderCard("", rows),)),),
    )


def _event_records_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    records = (
        data
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray))
        else ()
    )
    grouped: dict[int, list[AdventureItem]] = {1: [], 2: []}
    for item in records[:100]:
        if not isinstance(item, Mapping):
            continue
        try:
            level = int(item.get("level", 1))
        except (TypeError, ValueError):
            level = 1
        if level not in grouped:
            continue
        name = _scalar(item.get("event", item.get("name", "奇遇")))
        trigger_time = _beijing_time(item.get("time"))
        grouped[level].append(
            AdventureItem(
                name=name,
                trigger_time=trigger_time.replace(" ", "\n", 1),
                icon_asset=fixed_asset_name("adventures", name),
            )
        )
    groups = tuple(
        AdventureGroup(
            title="普通奇遇" if level == 1 else "绝世奇遇",
            items=tuple(grouped[level]),
        )
        for level in (1, 2)
        if grouped[level]
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"共 {sum(len(rows) for rows in grouped.values())} 条记录 · 北京时间",
        adventure_groups=groups,
    )


def _arena_recent_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    performance = data.get("performance")
    cards: list[RenderCard] = []
    win_rates: list[ChartEntry] = []
    if isinstance(performance, Mapping):
        for mode in ("2v2", "3v3", "5v5"):
            stats = performance.get(mode)
            if not isinstance(stats, Mapping):
                continue
            total = _integer(stats.get("totalCount"))
            wins = _integer(stats.get("winCount"))
            rate = _number(stats.get("winRate"))
            if rate is None and total > 0:
                rate = wins / total * 100
            if rate is not None and rate <= 1:
                rate *= 100
            if rate is not None:
                win_rates.append(
                    ChartEntry(
                        mode.upper(),
                        round(max(0.0, min(100.0, rate)), 1),
                        suffix="%",
                    )
                )
            cards.append(
                RenderCard(
                    mode.upper(),
                    (
                        RenderRow("当前积分", _scalar(stats.get("mmr"))),
                        RenderRow("段位", _scalar(stats.get("grade"))),
                        RenderRow("排名", _scalar(stats.get("ranking"))),
                        RenderRow("战绩", f"{wins}胜 / {total}场"),
                        RenderRow("MVP", _scalar(stats.get("mvpCount"))),
                    ),
                )
            )
    history = data.get("history")
    history_rows: list[TableRow] = []
    if isinstance(history, Sequence) and not isinstance(history, (str, bytes, bytearray)):
        for item in history[:12]:
            if not isinstance(item, Mapping):
                continue
            won = item.get("won") in {1, "1", True, "胜", "win"}
            change = _number(item.get("mmr"))
            change_text = "-" if change is None else f"{change:+g}"
            if change is not None and change > 0:
                change_color = "#d52b1e"
            elif change is not None and change < 0:
                change_color = "#0a8f4d"
            else:
                change_color = "#66736f"
            total_mmr = _scalar(item.get("totalMmr"))
            history_rows.append(
                TableRow(
                    cells=(
                        TableCell(_compact_time(item.get("startTime"))),
                        TableCell(
                            f"{_arena_mode(item.get('pvpType'))} · {_scalar(item.get('kungfu'))}"
                        ),
                        TableCell(
                            "胜" if won else "负",
                            "#d52b1e" if won else "#0a8f4d",
                        ),
                        TableCell(
                            f" · 赛后 {total_mmr}",
                            accent_text=change_text,
                            accent_color=change_color,
                        ),
                    )
                )
            )
    tables = (
        RenderTable(
            title="最近战绩",
            headers=("时间", "模式 / 心法", "结果", "积分"),
            rows=tuple(history_rows),
            column_widths=(156, 190, 78, 200),
        ),
    ) if history_rows else ()
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"{_server_label(data)} · {_scalar(data.get('roleName'))} · {_scalar(data.get('forceName'))}",
        sections=(
            RenderSection(
                "赛季表现",
                tuple(cards),
                columns=3,
                profile_layout=True,
            ),
        )
        if cards
        else (),
        chart_kind="bars",
        chart_entries=tuple(win_rates),
        tables=tables,
    )


def _gold_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    labels = {
        "tieba": "贴吧",
        "wanbaolou": "万宝楼",
        "dd373": "DD373",
        "uu898": "UU898",
        "5173": "5173",
        "7881": "7881",
    }
    colors = {
        "tieba": "#a94c43",
        "wanbaolou": "#3f766a",
        "dd373": "#d08c2d",
        "uu898": "#597fb5",
        "5173": "#8866a8",
        "7881": "#8a7657",
    }
    records = (
        data
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray))
        else ()
    )
    dated_records: list[tuple[str, Mapping[Any, Any]]] = []
    for item in records[:15]:
        if not isinstance(item, Mapping):
            continue
        label = _scalar(item.get("date", item.get("time")))
        dated_records.append((label, item))
    dated_records.sort(key=lambda pair: pair[0])
    series: list[LineSeries] = []
    for key, label in labels.items():
        points: list[LinePoint] = []
        for date_label, item in dated_records:
            value = _number(item.get(key))
            if value is not None and value > 0:
                points.append(LinePoint(date_label, value))
        if points:
            series.append(LineSeries(label, colors[key], tuple(points)))
    server = _server_label(dated_records[-1][1]) if dated_records else "-"
    subtitle = "最近 15 期交易平台金币比例"
    if server != "-":
        subtitle = f"{server} · {subtitle}"
    return RenderDocument(
        title=endpoint.name,
        subtitle=subtitle,
        line_series=tuple(series),
    )


def _smite_document(
    endpoint: EndpointSpec,
    data: Any,
    max_items: int,
) -> RenderDocument:
    cards: list[RenderCard] = []
    records = data if isinstance(data, Sequence) else ()
    for item in records[:max_items]:
        if not isinstance(item, Mapping):
            continue
        cards.append(
            RenderCard(
                _server_label(item),
                (
                    RenderRow("地图", _scalar(item.get("map_name"))),
                    RenderRow("时间", _beijing_time(item.get("time"))),
                ),
            )
        )
    return RenderDocument(
        title=endpoint.name,
        subtitle="近期诛恶事件（北京时间）",
        sections=(RenderSection("事件记录", tuple(cards)),),
    )


def _ranch_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 100)
    cards: list[RenderCard] = []
    records = data.get("data", {})
    if isinstance(records, Mapping):
        for map_name, values in records.items():
            cards.append(
                RenderCard(
                    _scalar(map_name),
                    (RenderRow("马匹与刷新信息", _multiline(values)),),
                )
            )
    overview = RenderCard(
        "",
        (
            RenderRow("区服", _server_label(data)),
            RenderRow("备注", _multiline(data.get("note"))),
        ),
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle="全部马场刷新信息",
        sections=(
            RenderSection("查询信息", (overview,)),
            RenderSection("地图与马匹", tuple(cards)),
        ),
    )


def _item_search_document(
    endpoint: EndpointSpec,
    data: Any,
    max_items: int,
) -> RenderDocument:
    records: Sequence[Any]
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        records = data
    elif isinstance(data, Mapping):
        records = (data,)
    else:
        records = ()
    cards: list[RenderCard] = []
    icon_url = _view_url(data)
    for item in records[:max_items]:
        if not isinstance(item, Mapping):
            continue
        if not icon_url:
            icon_url = _view_url(item)
        rows = tuple(
            RenderRow(label, _scalar(item.get(key)))
            for key, label in (
                ("class", "分类"),
                ("subclass", "子分类"),
                ("alias", "别名"),
                ("wblalias", "万宝楼别名"),
                ("value", "数值"),
                ("desc", "说明"),
                ("date", "更新时间"),
            )
            if item.get(key) not in {None, ""}
        )
        cards.append(RenderCard(_scalar(item.get("name", "商品")), rows))
    return RenderDocument(
        title=endpoint.name,
        subtitle="游戏商品信息",
        sections=(RenderSection("搜索结果", tuple(cards)),),
        icon_url=icon_url,
        hero_image_width=600,
    )


def _item_records_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    metadata = data.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = data
    records = _trade_record_mappings(data.get("list"))
    by_sale: dict[int, list[float]] = defaultdict(list)
    for item in records:
        try:
            sale = int(item.get("sale", 0))
        except (TypeError, ValueError):
            sale = 0
        value = _number(item.get("value"))
        if sale in SALE_LABELS and value is not None and value > 0:
            by_sale[sale].append(value)
    summary_rows = tuple(
        RenderRow(
            SALE_LABELS[sale],
            f"{len(values)} 条 · 最低 {min(values):g} · 中位 {median(values):g} · 最高 {max(values):g}",
        )
        for sale, values in sorted(by_sale.items())
    )

    def record_sort_key(item: Mapping[Any, Any]) -> str:
        return _scalar(item.get("date", item.get("time", "")))

    table_rows: list[TableRow] = []
    for item in sorted(records, key=record_sort_key, reverse=True)[:30]:
        try:
            sale = int(item.get("sale", 0))
        except (TypeError, ValueError):
            sale = 0
        zone = _scalar(item.get("zone"))
        server = _scalar(item.get("server"))
        server_label = "-".join(part for part in (zone, server) if part != "-") or "-"
        table_rows.append(
            TableRow(
                cells=(
                    TableCell(server_label),
                    TableCell(SALE_LABELS.get(sale, "其他")),
                    TableCell(_scalar(item.get("value"))),
                    TableCell(_compact_time(item.get("date", item.get("time")))),
                )
            )
        )
    sections: list[RenderSection] = []
    if summary_rows:
        sections.append(RenderSection("价格统计", (RenderCard("", summary_rows),)))
    tables = (
        RenderTable(
            title="近期记录",
            headers=("区服", "状态", "价格", "时间"),
            rows=tuple(table_rows),
            column_widths=(210, 78, 116, 220),
        ),
    ) if table_rows else ()
    return RenderDocument(
        title=endpoint.name,
        subtitle=f"已整理 {len(records)} 条实际交易记录",
        sections=tuple(sections),
        tables=tables,
        icon_url=_view_url(metadata) or _view_url(data),
    )


def _role_monster_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 10)
    rows = (
        RenderRow("区服", _server_label(data)),
        RenderRow("角色", _scalar(data.get("roleName", data.get("role_name")))),
        RenderRow("体力", _first_scalar(data, "skill_stamina", "skillStamina", "stamina")),
        RenderRow("精力", _first_scalar(data, "skill_energy", "skillEnergy", "energy")),
        RenderRow("技能数量", _first_scalar(data, "skill_count", "skillCount", "count")),
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle="角色百战资源概览",
        sections=(RenderSection("角色信息", (RenderCard("", rows),)),),
    )


def _mech_document(
    endpoint: EndpointSpec,
    data: Any,
    _max_items: int,
) -> RenderDocument:
    if not isinstance(data, Mapping):
        return _generic_document(endpoint, data, 30)
    rows = tuple(
        RenderRow(label, value)
        for label, value in (
            ("当前", _mech_current(data)),
            ("下一时段", _mech_next(data)),
        )
        if value != "-"
    )
    return RenderDocument(
        title=endpoint.name,
        subtitle="副本·一之窟解密玩法",
        sections=(RenderSection("解密结果", (RenderCard("", rows),)),),
    )


def _generic_document(
    endpoint: EndpointSpec,
    data: Any,
    max_items: int,
) -> RenderDocument:
    sections: list[RenderSection] = []
    if isinstance(data, Mapping):
        rows = _mapping_rows(data)
        if rows:
            sections.append(RenderSection("查询结果", (RenderCard("", rows),)))
        for key, value in data.items():
            if key in OMITTED_FIELDS or _is_scalar(value):
                continue
            cards = _cards_from_value(value, max_items=max_items)
            if cards:
                sections.append(RenderSection(_field_label(str(key)), cards))
    else:
        cards = _cards_from_value(data, max_items=max_items)
        if cards:
            sections.append(RenderSection("查询结果", cards))
    if not sections:
        sections.append(
            RenderSection(
                "查询结果",
                (RenderCard("暂无数据", (RenderRow("状态", "接口未返回可展示内容"),)),),
            )
        )
    return RenderDocument(
        title=endpoint.name,
        subtitle=endpoint.description,
        sections=tuple(sections),
    )


def _cards_from_value(value: Any, *, max_items: int) -> tuple[RenderCard, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        items = value[:max_items]
    else:
        items = (value,)
    cards: list[RenderCard] = []
    for item in items:
        if isinstance(item, Mapping):
            title = next(
                (
                    _scalar(item[key])
                    for key in ("title", "name", "event", "roleName", "role_name")
                    if item.get(key) not in {None, ""}
                ),
                "",
            )
            cards.append(RenderCard(title, _mapping_rows(item)))
        else:
            cards.append(RenderCard("", (RenderRow("内容", _multiline(item)),)))
    return tuple(cards)


def _mapping_rows(value: Mapping[Any, Any]) -> tuple[RenderRow, ...]:
    rows: list[RenderRow] = []
    for key, raw in value.items():
        key_text = str(key)
        if key_text in OMITTED_FIELDS or key_text in {"title", "name"}:
            continue
        if key_text.endswith("time") or key_text == "time":
            rendered = _beijing_time(raw)
        elif _is_scalar(raw):
            rendered = _scalar(raw)
        else:
            rendered = _limit_lines(_multiline(raw), 20)
        rendered = rendered[:1_200]
        if URL_PATTERN.match(rendered):
            continue
        rows.append(RenderRow(_field_label(key_text), rendered))
    return tuple(rows)


def _status_text(data: Any) -> str:
    if not isinstance(data, Mapping):
        return "区服：-\n开服状态：未开服"
    status = data.get("status")
    opened = status in {1, "1", True, "开服", "正常", "已开服"}
    return f"区服：{_server_label(data)}\n开服状态：{'开服' if opened else '未开服'}"


def _card_text(data: Any) -> str:
    server, role, _url = card_identity(data)
    return f"区服：{server}\n角色名：{role}"


def _server_label(data: Mapping[Any, Any]) -> str:
    zone = _scalar(data.get("zoneName", data.get("zone")))
    server = _scalar(data.get("serverName", data.get("server")))
    return "-".join(part for part in (zone, server) if part != "-") or "-"


def _mech_node(value: Any) -> str:
    if not isinstance(value, Mapping):
        return _multiline(value)
    return "\n".join(
        part
        for part in (_scalar(value.get("node")), _scalar(value.get("data")))
        if part != "-"
    )


def _mech_current(data: Mapping[Any, Any]) -> str:
    if "now_node" in data or "now_result" in data:
        return _joined_mech_value(data.get("now_node"), data.get("now_result"))
    return _mech_node(data.get("curr"))


def _mech_next(data: Mapping[Any, Any]) -> str:
    if "next_node" in data or "next_result" in data:
        return _joined_mech_value(data.get("next_node"), data.get("next_result"))
    return _mech_node(data.get("next"))


def _joined_mech_value(node: Any, result: Any) -> str:
    parts = [part for part in (_scalar(node), _multiline(result)) if part != "-"]
    return "：".join(parts) or "-"


def _mech_text(data: Any) -> str:
    if not isinstance(data, Mapping):
        return "【解密】\n当前：暂无结果\n下一时段：暂无结果"
    return "\n".join(
        (
            "【解密】",
            f"当前：{_mech_current(data)}",
            f"下一时段：{_mech_next(data)}",
        )
    )


def _calendar_date(value: Any) -> date | None:
    if not isinstance(value, Mapping):
        return None
    raw = value.get("date")
    if isinstance(raw, str):
        match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", raw)
        if match is not None:
            try:
                return date(*(int(part) for part in match.groups()))
            except ValueError:
                return None
    year = value.get("year")
    month = value.get("month")
    day = value.get("day")
    if year is None or month is None or day is None:
        return None
    try:
        return date(int(str(year)), int(str(month)), int(str(day)))
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _arena_mode(value: Any) -> str:
    mapping = {
        2: "2V2",
        3: "3V3",
        5: "5V5",
        22: "2V2",
        33: "3V3",
        55: "5V5",
        "2": "2V2",
        "3": "3V3",
        "5": "5V5",
        "22": "2V2",
        "33": "3V3",
        "55": "5V5",
    }
    return mapping.get(value, _scalar(value))


def _compact_time(value: Any) -> str:
    rendered = _beijing_time(value)
    if rendered == "-":
        return rendered
    return rendered[5:16] if len(rendered) >= 16 and rendered[4] == "-" else rendered[:16]


def item_search_names(data: Any, *, max_characters: int = 1_500) -> str:
    """Return bounded, URL-free item names as copyable newline-delimited text."""
    if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)):
        records: Sequence[Any] = data
    elif isinstance(data, Mapping):
        nested = data.get("list")
        if isinstance(nested, Sequence) and not isinstance(
            nested,
            (str, bytes, bytearray),
        ):
            records = nested
        else:
            records = (data,)
    else:
        records = ()
    names: list[str] = []
    for item in records:
        if not isinstance(item, Mapping) or item.get("name") in {None, ""}:
            continue
        name = _scalar(item.get("name"))
        if name != "-" and not URL_PATTERN.match(name):
            names.append(name)
    text = "\n".join(names)
    limit = max(32, max_characters)
    notice = "\n……名称列表已截断"
    if len(text) > limit:
        return f"{text[: limit - len(notice)].rstrip()}{notice}"
    return text


def _view_url(value: Any) -> str:
    if isinstance(value, Mapping):
        direct = value.get("view")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        metadata = value.get("metadata")
        if isinstance(metadata, Mapping):
            nested = _view_url(metadata)
            if nested:
                return nested
        items = value.get("list")
        if isinstance(items, Sequence) and not isinstance(
            items,
            (str, bytes, bytearray),
        ):
            return _view_url(items)
    elif isinstance(value, Sequence) and not isinstance(
        value,
        (str, bytes, bytearray),
    ):
        for item in value:
            nested = _view_url(item)
            if nested:
                return nested
    return ""


def _trade_record_mappings(value: Any) -> list[Mapping[Any, Any]]:
    records: list[Mapping[Any, Any]] = []

    def visit(node: Any) -> None:
        if len(records) >= 1_000:
            return
        if isinstance(node, Mapping):
            if "sale" in node and "value" in node and (
                "server" in node or "date" in node or "time" in node
            ):
                records.append(node)
                return
            for nested in node.values():
                visit(nested)
        elif isinstance(node, Sequence) and not isinstance(
            node,
            (str, bytes, bytearray),
        ):
            for nested in node:
                visit(nested)

    visit(value)
    return records


def _first_scalar(data: Mapping[Any, Any], *keys: str) -> str:
    for key in keys:
        if data.get(key) not in {None, ""}:
            return _scalar(data[key])
    return "-"


def _beijing_time(value: Any) -> str:
    if isinstance(value, bool):
        return _scalar(value)
    if isinstance(value, (int, float)):
        timestamp = float(value)
    elif isinstance(value, str) and value.strip().isdigit():
        timestamp = float(value.strip())
    else:
        return _scalar(value)
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC).astimezone(BEIJING).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (OverflowError, OSError, ValueError):
        return _scalar(value)


def _multiline(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Mapping):
        return "\n".join(
            f"{_field_label(str(key))}：{_multiline(raw)}"
            for key, raw in value.items()
            if str(key) not in OMITTED_FIELDS
        ) or "-"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return "\n".join(_multiline(item) for item in value) or "-"
    return _scalar(value)


def _field_label(key: str) -> str:
    return FIELD_LABELS.get(key, key.replace("_", " "))


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _scalar(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "是" if value else "否"
    text = str(value).replace("\r", " ").strip()
    return "\n".join(part.strip() for part in text.split("\n") if part.strip()) or "-"


def _number(value: Any) -> float | None:
    try:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _limit_lines(value: str, maximum: int) -> str:
    lines = value.splitlines()
    if len(lines) <= maximum:
        return value
    return "\n".join((*lines[:maximum], f"……另有 {len(lines) - maximum} 行"))


class _ArticleTextParser(HTMLParser):
    """Extract readable blocks while dropping active and navigational content."""

    BLOCKS = {
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
    }
    SKIPPED = {"head", "nav", "script", "style", "svg", "video"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._buffer: list[str] = []
        self.paragraphs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in self.SKIPPED:
            self._depth += 1
        elif tag in self.BLOCKS and self._depth == 0:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIPPED and self._depth:
            self._depth -= 1
        elif tag in self.BLOCKS and self._depth == 0:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._depth == 0:
            text = " ".join(data.split())
            if text:
                self._buffer.append(text)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        text = " ".join(self._buffer).strip()
        self._buffer.clear()
        if text and (not self.paragraphs or self.paragraphs[-1] != text):
            self.paragraphs.append(text[:4_000])
