"""Parse and validate user-facing JX3 query commands."""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from .endpoints import ENDPOINT_INDEX, EndpointSpec, ParameterSpec

COMMAND_ALIASES = {"jx3", "剑三", "剑网三"}
HELP_ALIASES = {"帮助", "help", "使用"}
LIST_ALIASES = {"指令", "接口", "功能", "list"}
SENSITIVE_ARGUMENTS = {
    "access",
    "appkey",
    "base_url",
    "endpoint",
    "path",
    "secret",
    "ticket",
    "token",
    "url",
}


class QueryInputError(ValueError):
    """Represent a safe, actionable command validation error."""


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Represent the top-level command selected by a user."""

    action: str
    endpoint: EndpointSpec | None = None
    arguments: tuple[str, ...] = ()
    keyword: str = ""


def parse_command(message: str) -> ParsedCommand:
    """Parse a raw AstrBot message into a help, list, or query action."""
    try:
        tokens = shlex.split(message, posix=True)
    except ValueError as exc:
        raise QueryInputError("参数中的引号没有成对闭合。") from exc

    command_index = next(
        (
            index
            for index, token in enumerate(tokens[:3])
            if token.lstrip("/").casefold() in COMMAND_ALIASES
        ),
        None,
    )
    if command_index is None:
        raise QueryInputError("请使用 /jx3 帮助 查看用法。")

    query_tokens = tokens[command_index + 1 :]
    if not query_tokens:
        return ParsedCommand(action="help")

    selector = query_tokens[0].casefold()
    remainder = tuple(query_tokens[1:])
    if selector in HELP_ALIASES:
        return ParsedCommand(
            action="help",
            keyword=" ".join(remainder).strip(),
        )
    if selector in LIST_ALIASES:
        return ParsedCommand(
            action="list",
            keyword=" ".join(remainder).strip(),
        )

    endpoint = ENDPOINT_INDEX.get(selector)
    if endpoint is None:
        raise QueryInputError(
            f"未找到功能“{query_tokens[0]}”。请使用 /jx3 帮助 <关键词> 搜索。"
        )
    return ParsedCommand(
        action="query",
        endpoint=endpoint,
        arguments=remainder,
    )


def parse_endpoint_arguments(
    endpoint: EndpointSpec,
    arguments: tuple[str, ...],
    *,
    default_server: str = "",
) -> dict[str, str | int]:
    """Validate positional and key-value arguments for one endpoint."""
    values: dict[str, str] = {}
    positional: list[str] = []
    parameters_by_alias: dict[str, ParameterSpec] = {}
    for parameter in endpoint.parameters:
        parameters_by_alias[parameter.name.casefold()] = parameter
        parameters_by_alias[parameter.label.casefold()] = parameter

    for token in arguments:
        if "=" not in token:
            positional.append(token)
            continue
        raw_key, raw_value = token.split("=", maxsplit=1)
        key = raw_key.strip().casefold()
        if key in SENSITIVE_ARGUMENTS:
            raise QueryInputError(f"参数“{raw_key}”只能由管理员在插件配置中设置。")
        parameter = parameters_by_alias.get(key)
        if parameter is None:
            raise QueryInputError(f"功能“{endpoint.name}”不支持参数“{raw_key}”。")
        if parameter.name in values:
            raise QueryInputError(f"参数“{parameter.label}”重复。")
        values[parameter.name] = raw_value

    remaining = [
        parameter for parameter in endpoint.parameters if parameter.name not in values
    ]
    if len(positional) > len(remaining):
        raise QueryInputError(
            f"参数过多。正确用法：{endpoint.usage}，也可使用 key=value。"
        )
    for parameter, value in zip(remaining, positional, strict=False):
        values[parameter.name] = value

    normalized: dict[str, str | int] = {}
    for parameter in endpoint.parameters:
        raw_value = values.get(parameter.name)
        if raw_value is None and parameter.name == "server" and default_server:
            raw_value = default_server
        if raw_value is None:
            if parameter.default is not None:
                normalized[parameter.name] = parameter.default
            elif parameter.required:
                raise QueryInputError(
                    f"缺少“{parameter.label}”。正确用法：{endpoint.usage}"
                )
            continue
        normalized[parameter.name] = _convert_parameter(parameter, raw_value)

    return normalized


def _convert_parameter(parameter: ParameterSpec, raw_value: str) -> str | int:
    value = raw_value.strip()
    if not value:
        if parameter.required:
            raise QueryInputError(f"参数“{parameter.label}”不能为空。")
        raise QueryInputError(f"参数“{parameter.label}”为空，请删除该参数。")
    if any(ord(character) < 32 for character in value):
        raise QueryInputError(f"参数“{parameter.label}”包含不允许的控制字符。")

    if parameter.kind is str:
        if len(value) > parameter.max_length:
            raise QueryInputError(
                f"参数“{parameter.label}”最长为 {parameter.max_length} 个字符。"
            )
        return value

    try:
        integer_value = int(value)
    except ValueError as exc:
        raise QueryInputError(f"参数“{parameter.label}”必须是整数。") from exc
    if parameter.choices and integer_value not in parameter.choices:
        choices = "、".join(str(choice) for choice in parameter.choices)
        raise QueryInputError(f"参数“{parameter.label}”只能是：{choices}。")
    if parameter.minimum is not None and integer_value < parameter.minimum:
        raise QueryInputError(f"参数“{parameter.label}”不能小于 {parameter.minimum}。")
    if parameter.maximum is not None and integer_value > parameter.maximum:
        raise QueryInputError(f"参数“{parameter.label}”不能大于 {parameter.maximum}。")
    return integer_value
