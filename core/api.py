"""Asynchronous bounded clients for JX3API and official article content."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qs, urlsplit

import aiohttp

from .endpoints import ENDPOINTS, EndpointSpec

ARTICLE_API_URL = "https://jx3.xoyo.com/api.php"
ALLOWED_ARTICLE_HOST = "jx3.xoyo.com"
ALLOWED_IMAGE_DOMAINS = (
    "jx3api.com",
    "jx3.xoyo.com",
    "jx3box.com",
    "j3pz.com",
    "nico.nicemoe.cn",
)
LEGACY_PRIMARY_HOST = "www.jx3api.com"
LEGACY_BACKUP_HOST = "api.jx3api.com"
MAX_IMAGE_BYTES = 8 * 1024 * 1024
FIXED_ENDPOINT_PATHS = frozenset(endpoint.path for endpoint in ENDPOINTS)


class JX3ApiError(RuntimeError):
    """Represent a safe error that can be shown to a chat user."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


class JX3ApiConfigurationError(JX3ApiError):
    """Represent invalid administrator-controlled network configuration."""


class _RetryableJX3ApiError(JX3ApiError):
    """Mark a safe read-only failure that may be retried."""


class JX3ApiClient:
    """Reuse one aiohttp session for fixed JX3API and media requests."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        ticket: str,
        timeout_seconds: int,
        max_concurrency: int,
        max_response_bytes: int,
    ) -> None:
        self.base_url = _validate_base_url(base_url)
        self.token = token
        self.ticket = ticket
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._session: aiohttp.ClientSession | None = None

    @property
    def started(self) -> bool:
        """Return whether the shared session is open."""
        return self._session is not None and not self._session.closed

    async def start(self) -> None:
        """Create the shared HTTP session once."""
        if self.started:
            return
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        connector = aiohttp.TCPConnector(
            limit=self.max_concurrency,
            ttl_dns_cache=300,
        )
        self._session = aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers={
                "Accept": "application/json",
                "User-Agent": "astrbot-plugin-jx3tools/0.7.3",
            },
        )

    async def close(self) -> None:
        """Close the shared HTTP session idempotently."""
        session = self._session
        self._session = None
        if session is not None and not session.closed:
            await session.close()

    async def request(
        self,
        endpoint: EndpointSpec,
        parameters: dict[str, str | int],
    ) -> Any:
        """POST one whitelisted legacy query and return its validated data field."""
        if not _is_fixed_endpoint_path(endpoint.path):
            raise JX3ApiConfigurationError("插件接口注册表包含无效路径。")
        if not self.started:
            raise JX3ApiError("JX3API 客户端尚未就绪，请稍后再试。")

        payload: dict[str, str | int] = dict(parameters)
        if endpoint.requires_token and self.token:
            payload["token"] = self.token
        if endpoint.requires_ticket and self.ticket:
            payload["ticket"] = self.ticket
        secrets = tuple(
            str(value)
            for key, value in payload.items()
            if key in {"ticket", "token"} and value
        )

        for attempt in range(3):
            try:
                return await self._request_once(
                    endpoint,
                    payload,
                    secrets=secrets,
                )
            except (
                TimeoutError,
                aiohttp.ClientConnectionError,
                aiohttp.ClientPayloadError,
            ) as exc:
                if attempt == 2:
                    message = (
                        "JX3API 请求超时，请稍后重试。"
                        if isinstance(exc, TimeoutError)
                        else "暂时无法完整读取 JX3API 响应，请稍后重试。"
                    )
                    raise JX3ApiError(message) from exc
            except _RetryableJX3ApiError:
                if attempt == 2:
                    raise
            except aiohttp.ClientError as exc:
                raise JX3ApiError("JX3API 网络请求失败，请稍后重试。") from exc
            await asyncio.sleep(0.2 * (2**attempt))
        raise JX3ApiError("JX3API 查询失败，请稍后重试。")

    async def _request_once(
        self,
        endpoint: EndpointSpec,
        payload: dict[str, str | int],
        *,
        secrets: tuple[str, ...],
    ) -> Any:
        assert self._session is not None
        async with self._semaphore:
            async with self._session.post(
                f"{self.base_url}{endpoint.path}",
                json=payload,
                allow_redirects=False,
            ) as response:
                return await self._decode_response(
                    response,
                    endpoint=endpoint,
                    secrets=secrets,
                )

    async def fetch_article(
        self,
        kind: str,
        item: Mapping[str, Any],
    ) -> dict[str, str]:
        """Fetch one selected article body from an approved official URL."""
        if not self.started:
            raise JX3ApiError("文章客户端尚未就绪，请稍后再试。")
        title = _bounded_text(item.get("title"), 200)
        date = _bounded_text(item.get("date", item.get("time", "")), 40)
        content = ""

        params = _article_api_params(kind, item)
        if params:
            content = await self._fetch_article_api(params)

        if not content:
            raw_url = item.get("url")
            if isinstance(raw_url, str) and _is_allowed_article_url(raw_url):
                content = await self._fetch_article_page(raw_url)
        if not content:
            raise JX3ApiError("未能读取所选内容，请重新查询后再试。")
        return {"title": title or "剑网 3 资讯", "date": date, "content": content}

    async def _fetch_article_api(self, params: dict[str, str]) -> str:
        assert self._session is not None
        try:
            async with self._semaphore:
                async with self._session.get(
                    ARTICLE_API_URL,
                    params=params,
                    allow_redirects=False,
                    headers={"Accept": "application/json"},
                ) as response:
                    body = await self._read_bounded(response, self.max_response_bytes)
                    if response.status < 200 or response.status >= 300:
                        return ""
        except (TimeoutError, aiohttp.ClientError):
            return ""
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return ""
        return _article_content(document)

    async def _fetch_article_page(self, url: str) -> str:
        assert self._session is not None
        try:
            async with self._semaphore:
                async with self._session.get(
                    url,
                    allow_redirects=False,
                    headers={"Accept": "text/html"},
                ) as response:
                    body = await self._read_bounded(response, self.max_response_bytes)
                    if response.status < 200 or response.status >= 300:
                        return ""
        except (TimeoutError, aiohttp.ClientError, JX3ApiError):
            return ""
        content = body.decode("utf-8", errors="replace")
        return "" if "接口参数异常" in content else content

    async def fetch_image(self, url: str) -> bytes:
        """Download one bounded raster image with retries from a trusted domain."""
        url = self._normalize_legacy_media_url(url)
        if not _is_allowed_image_url(url):
            raise JX3ApiError("接口返回了不受信任的图片地址，已停止下载。")
        if not self.started:
            raise JX3ApiError("图片客户端尚未就绪，请稍后再试。")
        return await self._fetch_image_with_retries(url)

    async def fetch_media_image(self, url: str) -> bytes:
        """Download a user-requested card with a media-specific timeout and retries."""
        url = self._normalize_legacy_media_url(url)
        if not _is_allowed_image_url(url):
            raise JX3ApiError("接口返回了不受信任的图片地址，已停止下载。")
        if not self.started:
            raise JX3ApiError("图片客户端尚未就绪，请稍后再试。")
        timeout = aiohttp.ClientTimeout(
            total=max(30, min(60, self.timeout_seconds * 2))
        )
        return await self._fetch_image_with_retries(
            url,
            request_timeout=timeout,
        )

    def _normalize_legacy_media_url(self, url: str) -> str:
        """Route stale primary-host media URLs through the selected legacy backup."""
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError:
            return url
        if (
            self.base_url == f"https://{LEGACY_BACKUP_HOST}"
            and parsed.scheme == "https"
            and parsed.hostname == LEGACY_PRIMARY_HOST
            and parsed.username is None
            and parsed.password is None
            and port in {None, 443}
        ):
            return parsed._replace(netloc=LEGACY_BACKUP_HOST).geturl()
        return url

    async def _fetch_image_with_retries(
        self,
        url: str,
        *,
        request_timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        for attempt in range(3):
            try:
                return await self._fetch_image_once(
                    url,
                    request_timeout=request_timeout,
                )
            except JX3ApiError as exc:
                retryable = exc.user_message in {
                    "图片下载超时，请稍后重试。",
                    "图片下载失败，请稍后重试。",
                }
                if not retryable or attempt == 2:
                    raise
                await asyncio.sleep(0.25 * (2**attempt))
        raise JX3ApiError("图片下载失败，请稍后重试。")

    async def _fetch_image_once(
        self,
        url: str,
        *,
        request_timeout: aiohttp.ClientTimeout | None = None,
    ) -> bytes:
        assert self._session is not None
        try:
            async with self._semaphore:
                async with self._session.get(
                    url,
                    allow_redirects=False,
                    headers={"Accept": "image/png,image/jpeg,image/webp"},
                    timeout=request_timeout,
                ) as response:
                    if response.status < 200 or response.status >= 300:
                        raise JX3ApiError("图片下载失败，请稍后重试。")
                    content_type = response.headers.get("Content-Type", "").split(";")[0]
                    if content_type not in {"image/png", "image/jpeg", "image/webp"}:
                        raise JX3ApiError("接口返回的图片格式不受支持。")
                    return await self._read_bounded(response, MAX_IMAGE_BYTES)
        except TimeoutError as exc:
            raise JX3ApiError("图片下载超时，请稍后重试。") from exc
        except aiohttp.ClientError as exc:
            raise JX3ApiError("图片下载失败，请稍后重试。") from exc

    async def _decode_response(
        self,
        response: aiohttp.ClientResponse,
        *,
        endpoint: EndpointSpec,
        secrets: tuple[str, ...],
    ) -> Any:
        if response.status == 429:
            raise JX3ApiError("JX3API 请求过于频繁，请稍后再试。")
        if response.status in {401, 403}:
            raise JX3ApiError("JX3API 鉴权失败，请管理员检查 Token/Ticket 权限。")
        if response.status >= 500:
            raise _RetryableJX3ApiError("JX3API 服务暂时不可用，请稍后重试。")
        if response.status < 200 or response.status >= 300:
            raise JX3ApiError(f"JX3API 返回 HTTP {response.status}。")
        body = await self._read_bounded(
            response,
            self.max_response_bytes,
            allow_complete_json_with_broken_length=True,
        )
        if not body.strip():
            raise _RetryableJX3ApiError("JX3API 返回了空内容，请稍后重试。")
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise _RetryableJX3ApiError(
                "JX3API 返回了无法识别的数据格式，请稍后重试。"
            ) from exc
        if not isinstance(document, dict):
            raise JX3ApiError("JX3API 返回结构不符合预期。")

        code = document.get("code")
        if code != 200:
            message = _safe_api_message(document.get("msg"), secrets=secrets)
            if (
                endpoint.key in {"chitu.records", "chitu.week_records"}
                and code == 400
                and "暂无数据" in message
            ):
                return {}
            if code in {401, 403}:
                raise JX3ApiError("JX3API 鉴权失败，请管理员检查 Token/Ticket 权限。")
            detail = f"：{message}" if message else ""
            raise JX3ApiError(f"JX3API 查询失败（{code!s}）{detail}。")
        return document.get("data")

    @staticmethod
    async def _read_bounded(
        response: aiohttp.ClientResponse,
        limit: int,
        *,
        allow_complete_json_with_broken_length: bool = False,
    ) -> bytes:
        content_length = response.content_length
        if content_length is not None and content_length > limit:
            raise JX3ApiError("远程内容过大，已停止处理。")
        body = bytearray()
        while True:
            try:
                chunk = await response.content.read(
                    min(64 * 1024, limit + 1 - len(body))
                )
            except aiohttp.ClientPayloadError:
                if allow_complete_json_with_broken_length and body:
                    return bytes(body)
                raise
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > limit:
                raise JX3ApiError("远程内容过大，已停止处理。")
        return bytes(body)


def _validate_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise JX3ApiConfigurationError(
            "JX3API 基础地址无效，请管理员配置不含路径的 HTTPS 地址。"
        )
    return normalized


def _is_fixed_endpoint_path(path: str) -> bool:
    return path in FIXED_ENDPOINT_PATHS


def _is_allowed_article_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == ALLOWED_ARTICLE_HOST
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
    )


def official_article_url(kind: str, item: Mapping[str, Any]) -> str:
    """Return a canonical public URL only for a selected rework article."""
    if kind != "rework":
        return ""
    raw_url = item.get("url")
    if not isinstance(raw_url, str) or len(raw_url) > 2_048:
        return ""
    parsed = urlsplit(raw_url)
    if parsed.path != "/announce/gg.html" or parsed.fragment:
        return ""
    params = _article_api_params(kind, item)
    if params is None:
        return ""
    identifier = params.get("kid", "")
    if not identifier:
        return ""
    return f"https://{ALLOWED_ARTICLE_HOST}/announce/gg.html?id={identifier}"


def _is_allowed_image_url(url: str) -> bool:
    parsed = urlsplit(url)
    hostname = parsed.hostname or ""
    allowed = any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in ALLOWED_IMAGE_DOMAINS
    )
    return (
        parsed.scheme == "https"
        and allowed
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
    )


def _article_api_params(
    kind: str,
    item: Mapping[str, Any],
) -> dict[str, str] | None:
    raw_url = item.get("url")
    if not isinstance(raw_url, str) or not _is_allowed_article_url(raw_url):
        return None
    parsed = urlsplit(raw_url)
    if kind == "news":
        match = re.search(r"/show-(\d+)-(\d+)-\d+\.html$", parsed.path)
        if match is not None:
            catid, identifier = match.groups()
            return {
                "op": "search_api",
                "action": "get_article_detail",
                "catid": catid,
                "id": identifier,
            }
        if parsed.path != "/announce/gg.html":
            return None
    if kind in {"announce", "rework"}:
        identifier = parse_qs(parsed.query).get("id", [""])[0]
    elif kind == "news":
        identifier = parse_qs(parsed.query).get("id", [""])[0]
    else:
        return None
    if not identifier.isdigit() or len(identifier) > 20:
        return None
    return {
        "op": "search_api",
        "action": "get_customer_article_detail",
        "kid": identifier,
        "game": "jx3",
    }


def _article_content(document: Any) -> str:
    if not isinstance(document, Mapping):
        return ""
    data: Any = document.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, Mapping):
        for key in ("content", "contents", "body", "text"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _bounded_text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def _safe_api_message(value: Any, *, secrets: tuple[str, ...]) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.split())
    for secret in secrets:
        cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned[:120]
