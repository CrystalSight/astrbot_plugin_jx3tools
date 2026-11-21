"""Fixed game presentation data researched from JX3BOX public datasets."""

from __future__ import annotations

import hashlib

SCHOOL_COLORS: dict[str, str] = {
    "江湖": "#7d817c",
    "天策": "#ec4b2c",
    "万花": "#9b70ca",
    "纯阳": "#249dbd",
    "七秀": "#e95b91",
    "少林": "#b88c18",
    "藏剑": "#c99c00",
    "丐帮": "#b47a3f",
    "明教": "#d64627",
    "五毒": "#327ed1",
    "唐门": "#62a42e",
    "苍云": "#6568ad",
    "长歌": "#31999f",
    "霸刀": "#7476b8",
    "蓬莱": "#5f9fbd",
    "凌雪": "#872f37",
    "衍天": "#767fc2",
    "药宗": "#16708a",
    "刀宗": "#3d91c7",
    "万灵": "#b28b16",
    "段氏": "#6688a5",
    "无相": "#806bb8",
    "无相楼": "#806bb8",
}

SCHOOL_KUNGFU_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("天策", ("傲血战意", "铁牢律")),
    ("万花", ("花间游", "离经易道")),
    ("纯阳", ("紫霞功", "太虚剑意")),
    ("七秀", ("冰心诀", "云裳心经")),
    ("少林", ("易筋经", "洗髓经")),
    ("藏剑", ("问水诀", "山居剑意")),
    ("丐帮", ("笑尘诀",)),
    ("明教", ("焚影圣诀", "明尊琉璃体")),
    ("五毒", ("毒经", "补天诀")),
    ("唐门", ("惊羽诀", "天罗诡道")),
    ("苍云", ("铁骨衣", "分山劲")),
    ("长歌", ("莫问", "相知")),
    ("霸刀", ("北傲诀",)),
    ("蓬莱", ("凌海诀",)),
    ("凌雪", ("隐龙诀",)),
    ("衍天", ("太玄经",)),
    ("药宗", ("无方", "灵素")),
    ("刀宗", ("孤锋诀",)),
    ("万灵", ("山海心诀",)),
    ("段氏", ("周天功",)),
    ("无相", ("幽罗引",)),
)

KUNGFU_COLORS: dict[str, str] = {
    kungfu: SCHOOL_COLORS[school]
    for school, kungfu_names in SCHOOL_KUNGFU_ORDER
    for kungfu in kungfu_names
}

KUNGFU_SCHOOLS: dict[str, str] = {
    kungfu: school
    for school, kungfu_names in SCHOOL_KUNGFU_ORDER
    for kungfu in kungfu_names
}

SALE_LABELS: dict[int, str] = {
    1: "出售",
    2: "收购",
    3: "想出",
    4: "想收",
    5: "成交",
    6: "正出",
}


def fixed_asset_name(category: str, display_name: str) -> str:
    """Return a stable, path-safe filename for one fixed local game image."""
    digest = hashlib.sha256(display_name.encode("utf-8")).hexdigest()[:16]
    return f"{category}/{digest}.png"
