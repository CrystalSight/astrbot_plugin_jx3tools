"""Normalize collected role equipment for both text and image output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SLOT_ORDER = (4, 3, 8, 12, 10, 11, 5, 9, 6, 7, 2)
GRADE_NUMERALS = str.maketrans("123456789一二三四五六七八九", "壹贰叁肆伍陆柒捌玖" * 2)


def online_result(data: Any, server: str, name: str) -> str:
    if not data:
        return "未找到该角色，请检查服务器全名和角色名。"
    if isinstance(data, list) and len(data) == 1:
        role = data[0]
        if isinstance(role, dict):
            if (
                role.get("roleName", name) != name
                or role.get("serverName", server) != server
            ):
                return "接口返回的角色与查询不一致。"
            for key in ("online", "isOnline", "onlineStatus"):
                value = str(role.get(key, "")).strip().casefold()
                if value in {"true", "1", "online", "在线"}:
                    return "当前角色在线"
                if value in {"false", "0", "offline", "离线", "不在线"}:
                    return "当前角色不在线"
    return "接口未返回可识别的角色在线状态，请稍后重试。"


def _text(value: Any) -> str:
    if isinstance(value, (str, int, float)) and not isinstance(value, bool):
        return " ".join(str(value).split())[:96]
    return ""


def _rows(data: Any, limit: int) -> list[dict]:
    return (
        [row for row in data[:limit] if isinstance(row, dict)]
        if isinstance(data, list)
        else []
    )


def _icon(row: dict) -> str:
    url = _text(row.get("iconUrl") or row.get("icon"))
    if url.startswith("https://"):
        return url
    icon_id = _text(row.get("iconId") or row.get("iconID") or url)
    if re.fullmatch(r"[1-9][0-9]{0,8}", icon_id):
        return f"https://icon.jx3box.com/icon/{icon_id}.png"
    return ""


@dataclass(frozen=True)
class IconLabel:
    name: str
    icon: str


@dataclass(frozen=True)
class Gear:
    item: IconLabel
    details: str
    stones: tuple[IconLabel, ...]
    effects: tuple[IconLabel, ...]


@dataclass(frozen=True)
class Equipment:
    title: str
    kungfu: IconLabel
    score: str
    stats: tuple[tuple[str, str], ...]
    talents: tuple[IconLabel, ...]
    gear: tuple[Gear, ...]

    def icons(self) -> set[str]:
        labels = [self.kungfu, *self.talents]
        for row in self.gear:
            labels.extend((row.item, *row.stones, *row.effects))
        return {label.icon for label in labels if label.icon}

    def as_text(self) -> str:
        lines = [self.title, f"{self.kungfu.name} · 装分 {self.score}", "属性"]
        lines.append("  ".join(f"{k} {v}" for k, v in self.stats) or "暂无已收录属性")
        lines.extend(
            (
                "奇穴",
                "、".join(x.name for x in self.talents) or "暂无已收录奇穴",
                "装备",
            )
        )
        for row in self.gear:
            lines.append(
                " · ".join(
                    filter(
                        None,
                        (
                            row.item.name,
                            row.details,
                            *(v.name for v in (*row.stones, *row.effects)),
                        ),
                    )
                )
            )
        return "\n".join(lines)[:4000]


def _gear(row: dict) -> Gear:
    name = _text(row.get("itemName")) or "未知装备"
    level = _text(row.get("strengthLevel"))
    title = f"{name}（{level}）" if level else name
    grade = _text(row.get("itemLevel"))
    attrs = _text(row.get("magicType")).replace(",", "  ").replace("，", "  ")
    details = " · ".join(filter(None, (f"{grade} 品" if grade else "", attrs)))
    stones = tuple(
        IconLabel(_text(s.get("itemName")) or "五行石", _icon(s))
        for s in _rows(row.get("mountDiamond"), 6)
        if s.get("itemName") or _icon(s)
    )
    effects = []
    enchant = row.get("minEnchant")
    if not isinstance(enchant, dict) or not enchant.get("itemName"):
        enchant = row.get("maxEnchant")
    for key, effect in (("enchant", enchant), ("colorDiamond", row.get("colorDiamond"))):
        if not isinstance(effect, dict) or not (label := _text(effect.get("itemName"))):
            continue
        icon = _icon(effect)
        if key == "colorDiamond":
            label = label.replace("(", "（").replace(")", "）")
            label = re.sub(
                r"（([1-9一二三四五六七八九])）$",
                lambda m: f"（{m[1].translate(GRADE_NUMERALS)}）",
                label,
            )
        else:
            icon = icon or "enchant:" + label
            attr = _text(effect.get("attribute1Name"))
            if attr and "（" not in label and "(" not in label:
                label += f"（{attr}）"
        effects.append(IconLabel(label, icon))
    return Gear(IconLabel(title, _icon(row)), details, stones, tuple(effects))


def equipment_from(data: Any, server: str, name: str) -> Equipment | None:
    if not isinstance(data, dict):
        return None
    items = _rows(data.get("equipList"), 32)
    if not items:
        return None
    order = {str(slot): i for i, slot in enumerate(SLOT_ORDER)}
    order.update({"0": len(SLOT_ORDER) + 1, "1": len(SLOT_ORDER) + 2})
    items.sort(key=lambda row: order.get(str(row.get("itemIndex")), len(SLOT_ORDER)))
    stats = []
    for row in _rows(data.get("panelList"), 64):
        label = _text(row.get("name"))
        percent = _text(row.get("percent"))
        value = percent.rstrip("%") + "%" if percent else _text(row.get("value"))
        if label and value:
            stats.append((label.removesuffix("等级") if percent else label, value))
    talents = []
    for row in _rows(
        data.get("talentList") or data.get("qixueList") or data.get("talents"), 12
    ):
        talent = _text(row.get("name") or row.get("skillName"))
        if talent:
            talents.append(IconLabel(talent, _icon(row)))
    kungfu_id = _text(data.get("kungfuId"))
    hero = _text(data.get("kungfuIcon"))
    if not hero and re.fullmatch(r"[1-9][0-9]{0,8}", kungfu_id):
        hero = f"https://img.jx3box.com/image/xf/{kungfu_id}.png"
    return Equipment(
        f"{_text(data.get('serverName')) or server} · {_text(data.get('roleName')) or name}",
        IconLabel(_text(data.get("kungfuName")) or "心法", hero),
        _text(data.get("equipScore")) or "暂无装分",
        tuple(stats),
        tuple(talents),
        tuple(_gear(row) for row in items),
    )
