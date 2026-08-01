"""Verify the bounded asynchronous JX3API client."""

from __future__ import annotations

import json
from typing import Any

import aiohttp
import astrbot_plugin_jx3tools.core.api as api_module
import pytest
from astrbot_plugin_jx3tools.core.api import (
    JX3ApiClient,
    JX3ApiConfigurationError,
    JX3ApiError,
    _article_api_params,
    _is_allowed_image_url,
    official_article_url,
)
from astrbot_plugin_jx3tools.core.endpoints import ENDPOINT_INDEX


class FakeContent:
    """Return a prepared response body."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.offset = 0

    async def read(self, limit: int) -> bytes:
        chunk = self.body[self.offset : self.offset + limit]
        self.offset += len(chunk)
        return chunk


class CompleteJsonWithBrokenLengthContent(FakeContent):
    """Raise after yielding a complete JSON document, like a broken length header."""

    async def read(self, limit: int) -> bytes:
        if self.offset >= len(self.body):
            raise aiohttp.ClientPayloadError("response payload is not completed")
        return await super().read(limit)


class FakeResponse:
    """Minimal aiohttp response double."""

    def __init__(self, status: int, document: Any, *, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(document).encode()
        self.status = status
        self.content_length = len(body)
        self.content = FakeContent(body)
        self.headers = {"Content-Type": "application/json"}


class FakeRequestContext:
    """Async context manager returned by ClientSession.post."""

    def __init__(
        self,
        response: FakeResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error

    async def __aenter__(self) -> FakeResponse:
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response

    async def __aexit__(self, *_args: object) -> None:
        return None


class FakeSession:
    """Capture outgoing request details without network access."""

    def __init__(self, contexts: FakeRequestContext | list[FakeRequestContext]) -> None:
        self.contexts = contexts if isinstance(contexts, list) else [contexts]
        self.closed = False
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeRequestContext:
        self.calls.append({"url": url, **kwargs})
        index = min(len(self.calls) - 1, len(self.contexts) - 1)
        return self.contexts[index]

    async def close(self) -> None:
        self.closed = True


def make_client(
    session: FakeSession,
    *,
    max_response_bytes: int = 2_048,
) -> JX3ApiClient:
    client = JX3ApiClient(
        base_url="https://api.jx3api.com",
        token="member-token",
        ticket="push-ticket",
        timeout_seconds=10,
        max_concurrency=2,
        max_response_bytes=max_response_bytes,
    )
    client._session = session  # type: ignore[assignment]
    return client


async def test_credentials_are_scoped_to_endpoint_requirements() -> None:
    response = FakeResponse(
        200,
        {"code": 200, "msg": "success", "data": {"text": "ok"}},
    )
    free_session = FakeSession(FakeRequestContext(response))
    free_client = make_client(free_session)

    await free_client.request(ENDPOINT_INDEX["saohua.random"], {})

    free_call = free_session.calls[0]
    assert "headers" not in free_call
    assert "token" not in free_call["json"]
    assert "ticket" not in free_call["json"]

    member_session = FakeSession(
        FakeRequestContext(
            FakeResponse(
                200,
                {"code": 200, "msg": "success", "data": {"text": "ok"}},
            )
        )
    )
    member_client = make_client(member_session)
    await member_client.request(ENDPOINT_INDEX["school.matrix"], {"name": "太虚剑意"})

    member_call = member_session.calls[0]
    assert "headers" not in member_call
    assert member_call["json"]["token"] == "member-token"
    assert member_call["json"]["ticket"] == "push-ticket"


@pytest.mark.parametrize("endpoint_name", ("card.random", "mech.calculator"))
async def test_current_member_endpoints_receive_only_their_required_token(
    endpoint_name: str,
) -> None:
    session = FakeSession(
        FakeRequestContext(
            FakeResponse(200, {"code": 200, "msg": "success", "data": {}})
        )
    )
    client = make_client(session)

    await client.request(ENDPOINT_INDEX[endpoint_name], {})

    call = session.calls[0]
    assert "headers" not in call
    assert call["json"]["token"] == "member-token"
    assert "ticket" not in call["json"]


@pytest.mark.parametrize("method_name", ("fetch_image", "fetch_media_image"))
async def test_legacy_backup_rewrites_stale_primary_media_host(
    monkeypatch,
    method_name: str,
) -> None:
    client = make_client(FakeSession(FakeRequestContext()))
    captured_urls: list[str] = []

    async def capture(
        url: str,
        *,
        request_timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        captured_urls.append(url)
        return b"image"

    monkeypatch.setattr(client, "_fetch_image_with_retries", capture)

    result = await getattr(client, method_name)(
        "https://www.jx3api.com/upload/card.png?size=large"
    )

    assert result == b"image"
    assert captured_urls == [
        "https://api.jx3api.com/upload/card.png?size=large"
    ]


async def test_custom_base_does_not_rewrite_primary_media_host(monkeypatch) -> None:
    client = make_client(FakeSession(FakeRequestContext()))
    client.base_url = "https://mirror.example"
    captured_urls: list[str] = []

    async def capture(
        url: str,
        *,
        request_timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        captured_urls.append(url)
        return b"image"

    monkeypatch.setattr(client, "_fetch_image_with_retries", capture)

    await client.fetch_image("https://www.jx3api.com/upload/item.png")

    assert captured_urls == ["https://www.jx3api.com/upload/item.png"]


async def test_invalid_json_is_retried_and_recovers() -> None:
    session = FakeSession(
        [
            FakeRequestContext(FakeResponse(200, {}, raw=b"")),
            FakeRequestContext(FakeResponse(200, {}, raw=b"not-json")),
            FakeRequestContext(
                FakeResponse(200, {"code": 200, "data": {"ok": True}})
            ),
        ]
    )
    client = make_client(session)

    data = await client.request(ENDPOINT_INDEX["active.list_calendar"], {"num": 30})

    assert data == {"ok": True}
    assert len(session.calls) == 3


async def test_excessively_nested_json_has_a_safe_retry_error(monkeypatch) -> None:
    session = FakeSession(
        [
            FakeRequestContext(FakeResponse(200, {"code": 200, "data": {}}))
            for _ in range(3)
        ]
    )
    client = make_client(session)

    def reject_nested_json(_body: bytes) -> Any:
        raise RecursionError("nested document")

    monkeypatch.setattr(api_module.json, "loads", reject_nested_json)

    with pytest.raises(JX3ApiError, match="无法识别的数据格式"):
        await client.request(ENDPOINT_INDEX["active.list_calendar"], {"num": 15})
    assert len(session.calls) == 3


async def test_complete_json_survives_a_broken_content_length_trailer() -> None:
    response = FakeResponse(
        200,
        {"code": 200, "data": {"list": [{"sale": 1, "value": 100}]}},
    )
    response.content = CompleteJsonWithBrokenLengthContent(response.content.body)
    session = FakeSession(FakeRequestContext(response))
    client = make_client(session)

    data = await client.request(ENDPOINT_INDEX["trade.item_records"], {"name": "物品"})

    assert data == {"list": [{"sale": 1, "value": 100}]}
    assert len(session.calls) == 1


async def test_response_size_is_bounded() -> None:
    response = FakeResponse(200, {}, raw=b"x" * 101)
    session = FakeSession(FakeRequestContext(response))
    client = make_client(session, max_response_bytes=100)

    with pytest.raises(JX3ApiError, match="过大"):
        await client.request(ENDPOINT_INDEX["saohua.random"], {})


async def test_business_error_redacts_request_secrets() -> None:
    response = FakeResponse(
        200,
        {
            "code": 500,
            "msg": "member-token push-ticket",
            "data": None,
        },
    )
    session = FakeSession(FakeRequestContext(response))
    client = make_client(session)

    with pytest.raises(JX3ApiError) as captured:
        await client.request(ENDPOINT_INDEX["school.matrix"], {"name": "太虚剑意"})

    message = captured.value.user_message
    assert "member-token" not in message
    assert "push-ticket" not in message
    assert "[redacted]" in message


@pytest.mark.parametrize("code", (401, 403))
async def test_business_auth_errors_do_not_relay_upstream_messages(code: int) -> None:
    response = FakeResponse(
        200,
        {
            "code": code,
            "msg": "Visit https://example.invalid and include member-token",
            "data": None,
        },
    )
    client = make_client(FakeSession(FakeRequestContext(response)))

    with pytest.raises(JX3ApiError) as captured:
        await client.request(ENDPOINT_INDEX["trade.demon"], {})

    assert captured.value.user_message == (
        "JX3API 鉴权失败，请管理员检查 Token/Ticket 权限。"
    )


@pytest.mark.parametrize("endpoint_name", ("今日赤兔", "本周赤兔"))
async def test_chitu_business_no_data_is_normalized_to_empty_mapping(
    endpoint_name: str,
) -> None:
    response = FakeResponse(
        200,
        {"code": 400, "msg": "暂无数据", "data": None},
    )
    client = make_client(FakeSession(FakeRequestContext(response)))

    data = await client.request(ENDPOINT_INDEX[endpoint_name], {})

    assert data == {}


async def test_timeout_has_safe_error_after_three_attempts() -> None:
    session = FakeSession(FakeRequestContext(error=TimeoutError("internal")))
    client = make_client(session)

    with pytest.raises(JX3ApiError, match="请求超时"):
        await client.request(ENDPOINT_INDEX["saohua.random"], {})
    assert len(session.calls) == 3


async def test_close_is_idempotent() -> None:
    session = FakeSession(FakeRequestContext())
    client = make_client(session)

    await client.close()
    await client.close()

    assert session.closed
    assert not client.started


@pytest.mark.parametrize(
    "base_url",
    (
        "http://api.jx3api.com",
        "https://user@api.jx3api.com",
        "https://api.jx3api.com/data",
        "https://api.jx3api.com?target=other",
    ),
)
def test_invalid_base_url_is_rejected(base_url: str) -> None:
    with pytest.raises(JX3ApiConfigurationError):
        JX3ApiClient(
            base_url=base_url,
            token="",
            ticket="",
            timeout_seconds=10,
            max_concurrency=2,
            max_response_bytes=2_048,
        )


def test_article_api_parameters_are_parsed_from_official_urls() -> None:
    news = _article_api_params(
        "news",
        {"id": 1, "url": "https://jx3.xoyo.com/show-2458-7389-1.html"},
    )
    query_news = _article_api_params(
        "news",
        {"id": 4, "url": "https://jx3.xoyo.com/announce/gg.html?id=1336001"},
    )
    announce = _article_api_params(
        "announce",
        {"id": 2, "url": "https://jx3.xoyo.com/announce/gg.html?id=1335653"},
    )
    rework = _article_api_params(
        "rework",
        {"id": 3, "url": "https://jx3.xoyo.com/announce/gg.html?id=1335648"},
    )

    assert news == {
        "op": "search_api",
        "action": "get_article_detail",
        "catid": "2458",
        "id": "7389",
    }
    assert announce is not None and announce["kid"] == "1335653"
    assert rework is not None and rework["kid"] == "1335648"
    assert query_news is not None and query_news["kid"] == "1336001"
    assert _article_api_params(
        "news", {"url": "https://evil.example/show-1-2-1.html"}
    ) is None
    assert _article_api_params(
        "news", {"url": "https://jx3.xoyo.com/other.html?id=1336001"}
    ) is None


def test_only_selected_rework_gets_a_canonical_public_article_url() -> None:
    selected = {
        "url": "https://jx3.xoyo.com/announce/gg.html?id=1335648&from=list"
    }

    assert official_article_url("rework", selected) == (
        "https://jx3.xoyo.com/announce/gg.html?id=1335648"
    )
    assert official_article_url("news", selected) == ""
    assert official_article_url(
        "rework",
        {"url": "https://evil.example/announce/gg.html?id=1335648"},
    ) == ""
    assert official_article_url(
        "rework",
        {"url": "https://jx3.xoyo.com/other.html?id=1335648"},
    ) == ""


def test_official_item_icon_host_is_allowed_without_broadening_http() -> None:
    assert _is_allowed_image_url("https://nico.nicemoe.cn/item.png")
    assert not _is_allowed_image_url("http://nico.nicemoe.cn/item.png")
    assert not _is_allowed_image_url("https://nicemoe.cn/item.png")


async def test_item_image_retries_a_transient_broken_payload(monkeypatch) -> None:
    client = make_client(FakeSession(FakeRequestContext()))
    calls = 0

    async def fetch_once(
        _url: str,
        *,
        request_timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        nonlocal calls
        calls += 1
        assert request_timeout is None
        if calls == 1:
            raise JX3ApiError("图片下载失败，请稍后重试。")
        return b"complete-image"

    async def skip_backoff(_delay: float) -> None:
        return None

    monkeypatch.setattr(client, "_fetch_image_once", fetch_once)
    monkeypatch.setattr(api_module.asyncio, "sleep", skip_backoff)

    result = await client.fetch_image("https://nico.nicemoe.cn/item.png")

    assert result == b"complete-image"
    assert calls == 2
