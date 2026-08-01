"""Verify the retained registry and command parser."""

from __future__ import annotations

import pytest
from astrbot_plugin_jx3tools.core.endpoints import (
    ENDPOINT_INDEX,
    ENDPOINTS,
    ServiceTier,
)
from astrbot_plugin_jx3tools.core.query import (
    QueryInputError,
    parse_command,
    parse_endpoint_arguments,
)


def test_registry_only_contains_retained_commands() -> None:
    assert len(ENDPOINTS) == 27
    assert len({endpoint.key for endpoint in ENDPOINTS}) == len(ENDPOINTS)
    assert len({endpoint.path for endpoint in ENDPOINTS}) == len(ENDPOINTS)
    assert all(endpoint.path.startswith("/data/") for endpoint in ENDPOINTS)
    assert all("?" not in endpoint.path for endpoint in ENDPOINTS)
    assert {endpoint.tier for endpoint in ENDPOINTS} == set(ServiceTier)
    for removed in (
        "家具",
        "器物",
        "区服",
        "奇穴",
        "未做奇遇",
        "名剑排行",
        "招募",
        "师徒",
        "语音",
        "鲜花",
        "技能",
        "黑市",
        "关隘",
        "八卦",
        "名剑门派",
        "名剑统计",
        "竞技统计",
    ):
        assert removed.casefold() not in ENDPOINT_INDEX


def test_feedback_categories_and_parameters_are_fixed() -> None:
    assert ENDPOINT_INDEX["随机名片"].tier is ServiceTier.MEMBER
    assert ENDPOINT_INDEX["解密"].tier is ServiceTier.MEMBER
    assert ENDPOINT_INDEX["随机名片"].requires_token
    assert ENDPOINT_INDEX["解密"].requires_token
    status = ENDPOINT_INDEX["开服"]
    assert [parameter.name for parameter in status.parameters] == ["server"]
    assert dict(status.fixed_parameters) == {"type": 1}
    assert [parameter.name for parameter in ENDPOINT_INDEX["日常"].parameters] == [
        "server",
        "num",
    ]
    daily_offset = ENDPOINT_INDEX["日常"].parameters[1]
    assert daily_offset.minimum == -30
    assert daily_offset.maximum == 30
    assert dict(ENDPOINT_INDEX["日常"].fixed_parameters) == {}
    assert ENDPOINT_INDEX["月历"].parameters == ()
    assert dict(ENDPOINT_INDEX["月历"].fixed_parameters) == {"num": 15}
    assert [parameter.name for parameter in ENDPOINT_INDEX["金价"].parameters] == [
        "server"
    ]
    assert dict(ENDPOINT_INDEX["金价"].fixed_parameters) == {"limit": 15}
    assert ENDPOINT_INDEX["解密"].output == "text"
    assert ENDPOINT_INDEX["科举"].parameters[0].required


def test_command_discovery_accepts_instruction_and_all() -> None:
    parsed = parse_command("/jx3 指令 全部")

    assert parsed.action == "list"
    assert parsed.keyword == "全部"


def test_chinese_alias_and_stable_key_resolve_to_same_endpoint() -> None:
    chinese = parse_command("/jx3 角色 梦江南 夜温言")
    stable = parse_command("/jx3 role.detail server=梦江南 name=夜温言")

    assert chinese.endpoint is stable.endpoint
    assert chinese.endpoint is ENDPOINT_INDEX["role.detail"]


def test_arguments_support_default_server_and_key_values() -> None:
    endpoint = ENDPOINT_INDEX["role.detail"]

    parsed = parse_endpoint_arguments(
        endpoint,
        ("name=夜温言",),
        default_server="梦江南",
    )

    assert parsed == {"server": "梦江南", "name": "夜温言"}


@pytest.mark.parametrize(
    "argument",
    ("token=secret", "ticket=secret", "url=https://evil.example", "secret=x"),
)
def test_sensitive_arguments_are_rejected(argument: str) -> None:
    endpoint = ENDPOINT_INDEX["role.detail"]

    with pytest.raises(QueryInputError, match="只能由管理员"):
        parse_endpoint_arguments(endpoint, ("梦江南", "夜温言", argument))


def test_unknown_and_out_of_range_arguments_fail_before_network() -> None:
    endpoint = ENDPOINT_INDEX["news.allnews"]

    with pytest.raises(QueryInputError, match="不支持参数"):
        parse_endpoint_arguments(endpoint, ("other=value",))
    with pytest.raises(QueryInputError, match="不能大于"):
        parse_endpoint_arguments(endpoint, ("limit=21",))


def test_unclosed_quote_returns_safe_error() -> None:
    with pytest.raises(QueryInputError, match="引号"):
        parse_command('/jx3 科举 "未闭合')


def test_exam_subject_is_required() -> None:
    with pytest.raises(QueryInputError, match="缺少“题目”"):
        parse_endpoint_arguments(ENDPOINT_INDEX["科举"], ())
