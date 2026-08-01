"""Declarative registry for the retained JX3API commands."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ServiceTier(StrEnum):
    """User-facing feature groups."""

    FREE = "free"
    MEMBER = "member"
    OTHER = "other"


TIER_LABELS: dict[ServiceTier, str] = {
    ServiceTier.FREE: "免费",
    ServiceTier.MEMBER: "会员",
    ServiceTier.OTHER: "其他",
}


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    """Describe one user-visible endpoint parameter."""

    name: str
    label: str
    required: bool = False
    kind: type[str] | type[int] = str
    default: str | int | None = None
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[int, ...] = ()
    max_length: int = 64

    @property
    def usage(self) -> str:
        """Return a compact required/optional usage fragment."""
        return f"<{self.label}>" if self.required else f"[{self.label}]"


@dataclass(frozen=True, slots=True)
class EndpointSpec:
    """Describe one whitelisted JX3API endpoint."""

    key: str
    name: str
    aliases: tuple[str, ...]
    path: str
    tier: ServiceTier
    description: str
    parameters: tuple[ParameterSpec, ...] = ()
    requires_token: bool = False
    requires_ticket: bool = False
    output: str = "auto"
    fixed_parameters: tuple[tuple[str, str | int], ...] = ()
    article_kind: str = ""

    @property
    def usage(self) -> str:
        """Return command usage without exposing internal endpoint details."""
        suffix = " ".join(parameter.usage for parameter in self.parameters)
        return f"/jx3 {self.name}{f' {suffix}' if suffix else ''}"


def text(
    name: str,
    label: str,
    *,
    required: bool = False,
    default: str | None = None,
    max_length: int = 64,
) -> ParameterSpec:
    """Build a string parameter specification."""
    return ParameterSpec(
        name=name,
        label=label,
        required=required,
        default=default,
        max_length=max_length,
    )


def integer(
    name: str,
    label: str,
    *,
    required: bool = False,
    default: int | None = None,
    minimum: int = 0,
    maximum: int = 100,
    choices: tuple[int, ...] = (),
) -> ParameterSpec:
    """Build an integer parameter specification."""
    return ParameterSpec(
        name=name,
        label=label,
        required=required,
        kind=int,
        default=default,
        minimum=minimum,
        maximum=maximum,
        choices=choices,
    )


SERVER = text("server", "区服", required=True)
OPTIONAL_SERVER = text("server", "区服")
NAME = text("name", "名称", required=True)


ENDPOINTS: tuple[EndpointSpec, ...] = (
    EndpointSpec(
        "active.calendar",
        "日常",
        ("日历", "活动日历"),
        "/data/active/calendar",
        ServiceTier.FREE,
        "查询指定日期的日常活动。",
        (
            OPTIONAL_SERVER,
            integer("num", "偏移天数", default=0, minimum=-30, maximum=30),
        ),
        output="image",
    ),
    EndpointSpec(
        "active.list_calendar",
        "月历",
        ("活动月历",),
        "/data/active/list/calendar",
        ServiceTier.FREE,
        "按周日到周六查询前后各 15 天的活动月历。",
        output="image",
        fixed_parameters=(("num", 15),),
    ),
    EndpointSpec(
        "active.celebs",
        "行侠",
        ("行侠事件",),
        "/data/active/celebs",
        ServiceTier.FREE,
        "查询指定声望社群的行侠事件。",
        (text("name", "声望社群", required=True),),
        output="image",
    ),
    EndpointSpec(
        "exam.search",
        "科举",
        ("科举答题", "答题"),
        "/data/exam/search",
        ServiceTier.FREE,
        "支持原文、模糊词或拼音首字母搜索科举题目和答案。",
        (
            text("subject", "题目", required=True, max_length=100),
            integer("limit", "数量", default=10, minimum=1, maximum=30),
        ),
    ),
    EndpointSpec(
        "news.allnews",
        "新闻",
        ("资讯", "新闻资讯"),
        "/data/news/allnews",
        ServiceTier.FREE,
        "列出近期新闻，并在 10 秒内按序号查看正文。",
        (integer("limit", "数量", default=10, minimum=1, maximum=20),),
        output="article",
        article_kind="news",
    ),
    EndpointSpec(
        "news.announce",
        "公告",
        ("维护公告",),
        "/data/news/announce",
        ServiceTier.FREE,
        "列出近期公告，并在 10 秒内按序号查看正文。",
        (integer("limit", "数量", default=10, minimum=1, maximum=20),),
        output="article",
        article_kind="announce",
    ),
    EndpointSpec(
        "status.check",
        "开服",
        ("开服状态", "服务器状态"),
        "/data/status/check",
        ServiceTier.FREE,
        "检测指定区服是否开服。",
        (SERVER,),
        output="text",
        fixed_parameters=(("type", 1),),
    ),
    EndpointSpec(
        "skill.rework",
        "技改",
        ("技改记录",),
        "/data/skill/rework",
        ServiceTier.FREE,
        "列出最近 5 条技改，并在 10 秒内按序号查看正文。",
        output="article",
        article_kind="rework",
    ),
    EndpointSpec(
        "school.foods",
        "小药",
        ("门派食物", "食物", "门派宴席"),
        "/data/school/foods",
        ServiceTier.FREE,
        "查询全部门派与心法的小药数据。",
        output="image",
    ),
    EndpointSpec(
        "role.detail",
        "角色",
        ("角色信息", "装备"),
        "/data/role/detail",
        ServiceTier.MEMBER,
        "查询角色基础资料。",
        (SERVER, NAME),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "school.matrix",
        "阵眼",
        ("心法阵眼",),
        "/data/school/matrix",
        ServiceTier.MEMBER,
        "查询指定心法的阵眼及 1–6 层效果。",
        (text("name", "心法", required=True),),
        requires_token=True,
        requires_ticket=True,
        output="image",
    ),
    EndpointSpec(
        "event.records",
        "奇遇记录",
        ("角色奇遇",),
        "/data/event/records",
        ServiceTier.MEMBER,
        "查询角色奇遇记录。",
        (SERVER, NAME),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "arena.recent",
        "名剑战绩",
        ("竞技战绩",),
        "/data/arena/recent",
        ServiceTier.MEMBER,
        "查询角色名剑大会战绩。",
        (
            SERVER,
            NAME,
            integer("mode", "模式", default=33, choices=(22, 33, 55)),
        ),
        requires_token=True,
        requires_ticket=True,
        output="image",
    ),
    EndpointSpec(
        "trade.demon",
        "金价",
        ("金币价格",),
        "/data/trade/demon",
        ServiceTier.MEMBER,
        "查询 15 期各交易平台金币比例走势。",
        (OPTIONAL_SERVER,),
        requires_token=True,
        output="image",
        fixed_parameters=(("limit", 15),),
    ),
    EndpointSpec(
        "smite.records",
        "诛恶",
        ("诛恶事件",),
        "/data/smite/records",
        ServiceTier.MEMBER,
        "查询近期诛恶事件。",
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "active.monster",
        "百战",
        ("百战首领",),
        "/data/active/monster",
        ServiceTier.MEMBER,
        "查询本周百战异闻录首领。",
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "ranch.records",
        "马场",
        ("马场刷新", "刷马"),
        "/data/ranch/records",
        ServiceTier.MEMBER,
        "查询指定区服全部马场刷新信息。",
        (SERVER,),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "card.record",
        "名片",
        ("角色名片",),
        "/data/card/record",
        ServiceTier.MEMBER,
        "查询角色最新名片并直接发送图片。",
        (SERVER, NAME),
        requires_token=True,
        output="card",
    ),
    EndpointSpec(
        "role.monster",
        "角色百战",
        ("百战进度",),
        "/data/role/monster",
        ServiceTier.MEMBER,
        "查询角色百战进度。",
        (SERVER, NAME),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "chitu.records",
        "今日赤兔",
        ("本日赤兔", "赤兔"),
        "/data/chitu/records",
        ServiceTier.MEMBER,
        "查询今日赤兔记录。",
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "chitu.week_records",
        "本周赤兔",
        ("赤兔周报",),
        "/data/chitu/week/records",
        ServiceTier.MEMBER,
        "查询本周赤兔记录。",
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "trade.item_search",
        "物品搜索",
        ("搜索物品",),
        "/data/trade/item/search",
        ServiceTier.MEMBER,
        "搜索游戏商品资料并展示图标。",
        (NAME,),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "trade.item_records",
        "物价",
        ("物品价格", "价格"),
        "/data/trade/item/records",
        ServiceTier.MEMBER,
        "查询指定商品的近期价格。",
        (NAME, OPTIONAL_SERVER),
        requires_token=True,
        output="image",
    ),
    EndpointSpec(
        "card.random",
        "随机名片",
        ("随机角色",),
        "/data/card/random",
        ServiceTier.MEMBER,
        "按可选区服、体型或门派随机名片并直接发送图片。",
        (OPTIONAL_SERVER, text("body", "体型"), text("force", "门派")),
        requires_token=True,
        output="card",
    ),
    EndpointSpec(
        "mech.calculator",
        "解密",
        ("副本解密", "九宫格"),
        "/data/mech/calculator",
        ServiceTier.MEMBER,
        "副本·一之窟解密玩法。",
        requires_token=True,
        output="text",
    ),
    EndpointSpec(
        "saohua.random",
        "骚话",
        ("世界骚话",),
        "/data/saohua/random",
        ServiceTier.OTHER,
        "随机获取一句世界骚话。",
        output="text",
    ),
    EndpointSpec(
        "saohua.content",
        "舔狗",
        ("舔狗日记",),
        "/data/saohua/content",
        ServiceTier.OTHER,
        "随机获取一则舔狗日记。",
        output="text",
    ),
)


def build_endpoint_index() -> dict[str, EndpointSpec]:
    """Build a case-insensitive lookup index and reject duplicate aliases."""
    index: dict[str, EndpointSpec] = {}
    for endpoint in ENDPOINTS:
        for alias in (endpoint.key, endpoint.name, *endpoint.aliases):
            normalized = alias.casefold()
            if normalized in index:
                raise ValueError(f"Duplicate endpoint alias: {alias}")
            index[normalized] = endpoint
    return index


ENDPOINT_INDEX = build_endpoint_index()
