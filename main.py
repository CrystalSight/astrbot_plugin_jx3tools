"""AstrBot entry point for bounded JX3API queries and local images."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, get_astrbot_data_path

from .api import (
    JX3ApiClient,
    JX3ApiConfigurationError,
    JX3ApiError,
    official_article_url,
)
from .endpoints import (
    ENDPOINT_INDEX,
    ENDPOINTS,
    TIER_LABELS,
    EndpointSpec,
    ServiceTier,
)
from .image_renderer import (
    FontPaths,
    LocalImageRenderer,
    LocalRenderError,
    temporary_image_path,
)
from .query import QueryInputError, parse_command, parse_endpoint_arguments
from .rate_limit import SessionRateLimiter
from .rendering import (
    build_article_document,
    build_document,
    card_identity,
    format_text,
    item_search_names,
)
from .settings import PluginSettings

PLUGIN_NAME = "astrbot_plugin_jx3tools"
ARTICLE_SELECTION_SECONDS = 10.0
TIER_SEARCH_ALIASES: dict[str, ServiceTier] = {
    "免费": ServiceTier.FREE,
    "free": ServiceTier.FREE,
    "会员": ServiceTier.MEMBER,
    "member": ServiceTier.MEMBER,
    "其他": ServiceTier.OTHER,
    "other": ServiceTier.OTHER,
}
ALL_SEARCH_ALIASES = {"全部", "all"}


@dataclass(slots=True)
class PendingArticleSelection:
    """Bounded state for one 10-second article choice."""

    owner_id: str
    unified_msg_origin: str
    endpoint_name: str
    kind: str
    items: tuple[Mapping[str, Any], ...]
    expires_at: float
    timeout_task: asyncio.Task[None] | None = None


class Jx3toolsPlugin(Star):
    """Expose retained JX3API queries through one discoverable command."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self.settings = PluginSettings.from_config(self.config)
        self._client: JX3ApiClient | None = None
        self._renderer: LocalImageRenderer | None = None
        self._initialized = False
        self._startup_error = ""
        self._rate_limiter = SessionRateLimiter(self.settings.requests_per_minute)
        self._render_semaphore = asyncio.Semaphore(1)
        self._pending_articles: dict[str, PendingArticleSelection] = {}

    async def initialize(self) -> None:
        """Open the shared client and load private local fonts idempotently."""
        if self._initialized:
            return
        self._startup_error = ""
        self.settings = PluginSettings.from_config(self.config)
        self._rate_limiter = SessionRateLimiter(self.settings.requests_per_minute)
        self._render_semaphore = asyncio.Semaphore(1)
        await self._clear_pending_articles()
        font_directory = (
            Path(get_astrbot_data_path()) / "plugin_data" / PLUGIN_NAME / "fonts"
        )
        try:
            self._renderer = await asyncio.to_thread(
                LocalImageRenderer,
                FontPaths.from_directory(font_directory),
            )
        except LocalRenderError:
            self._renderer = None
            logger.warning(
                "JX3Tools local fonts are unavailable under plugin_data; image output will fall back to text"
            )

        if self.settings.enabled:
            try:
                client = JX3ApiClient(
                    base_url=self.settings.api_base_url,
                    token=self.settings.token,
                    ticket=self.settings.ticket,
                    timeout_seconds=self.settings.timeout_seconds,
                    max_concurrency=self.settings.max_concurrency,
                    max_response_bytes=self.settings.max_response_bytes,
                )
                await client.start()
                self._client = client
            except JX3ApiConfigurationError as exc:
                self._startup_error = exc.user_message
                logger.error("JX3Tools network configuration is invalid")
        self._initialized = True
        logger.info("Plugin astrbot_plugin_jx3tools initialized")

    @filter.command("jx3", alias={"剑三", "剑网三"})
    async def jx3(self, event: AstrMessageEvent):
        """Handle help, validation, querying, and local rendering."""
        if not self.settings.enabled:
            yield event.plain_result("JX3Tools 当前已由管理员禁用。")
            return
        if not self._initialized:
            yield event.plain_result("JX3Tools 正在初始化，请稍后再试。")
            return
        if self._startup_error:
            yield event.plain_result(self._startup_error)
            return

        endpoint: EndpointSpec | None = None
        try:
            command = parse_command(event.message_str)
            if command.action == "help":
                yield event.plain_result(self._help_text(command.keyword))
                return
            if command.action == "list":
                yield event.plain_result(self._list_text(command.keyword))
                return

            endpoint = command.endpoint
            assert endpoint is not None
            self._validate_access(endpoint)
            parameters = parse_endpoint_arguments(
                endpoint,
                command.arguments,
                default_server=self.settings.default_server,
            )
            parameters.update(dict(endpoint.fixed_parameters))
            await self._check_article_lock(event, endpoint)

            retry_after = self._rate_limiter.check(_session_key(event))
            if retry_after:
                raise QueryInputError(
                    f"请求过于频繁，请在 {math.ceil(retry_after)} 秒后重试。"
                )

            client = self._client
            if client is None:
                raise JX3ApiError("JX3API 客户端尚未就绪，请稍后再试。")
            data = await client.request(endpoint, parameters)
        except QueryInputError as exc:
            yield event.plain_result(str(exc))
            return
        except JX3ApiError as exc:
            yield event.plain_result(_friendly_api_error(endpoint, exc))
            return

        if endpoint.output == "article":
            _pending, message = await self._start_article_selection(
                event,
                endpoint,
                data,
            )
            yield event.plain_result(message)
            return

        should_render = self._should_render_image(endpoint, data)
        document = (
            build_document(endpoint, data, max_items=self.settings.max_items)
            if should_render and endpoint.output != "card"
            else None
        )
        text_result = format_text(
            endpoint,
            data,
            max_items=self.settings.max_items,
            document=document,
        )
        if endpoint.key == "trade.item_search":
            names = item_search_names(data)
            if names:
                yield event.plain_result(names)
        if endpoint.output == "card":
            async for result in self._card_results(event, data, text_result):
                yield result
            return

        if not should_render:
            yield event.plain_result(text_result)
            return
        renderer = self._renderer
        if renderer is None:
            yield event.plain_result(text_result)
            return

        assert document is not None
        icon_bytes: bytes | None = None
        profile_image_bytes: bytes | None = None
        if document.icon_url:
            try:
                icon_bytes = await client.fetch_image(document.icon_url)
            except JX3ApiError:
                logger.info("JX3Tools optional item icon was not downloaded")
        if (
            endpoint.key == "arena.recent"
            and document.sections
            and len(document.sections[0].cards) == 1
        ):
            profile_image_bytes = await self._arena_profile_image(
                client,
                parameters,
            )
        try:
            async with self._render_semaphore:
                image_path = await _run_tracked_file_job(
                    event,
                    renderer.render,
                    document,
                    icon_bytes=icon_bytes,
                    profile_image_bytes=profile_image_bytes,
                )
        except LocalRenderError:
            logger.warning("JX3Tools local image rendering failed")
            yield event.plain_result(text_result)
            return
        yield event.image_result(image_path)

    @filter.regex(r"^\s*\d+\s*$")
    async def article_selection(self, event: AstrMessageEvent):
        """Consume a numeric selection only for the initiating user."""
        identity = _article_identity(event)
        if identity is None:
            yield event.plain_result("无法确认当前会话与发起者，不能处理文章序号。")
            return
        session, sender_id = identity
        pending = self._pending_articles.get(session)
        if pending is None:
            return
        now = asyncio.get_running_loop().time()
        if now > pending.expires_at:
            await self._finish_article_selection(session, pending)
            if sender_id == pending.owner_id:
                yield event.plain_result("选择已超时，请重新发送对应查询指令。")
            return
        if sender_id != pending.owner_id:
            yield event.plain_result("当前序号选择仅限本次查询的发起者操作。")
            return

        index = int(event.message_str.strip())
        if index < 1 or index > len(pending.items):
            yield event.plain_result(
                f"序号无效，请在 10 秒内回复 1–{len(pending.items)}。"
            )
            return
        await self._finish_article_selection(session, pending)
        stop_event = getattr(event, "stop_event", None)
        try:
            await event.send(
                event.plain_result(
                    f"已选择第 {index} 条，正在读取{pending.endpoint_name}正文……"
                )
            )
            client = self._client
            renderer = self._renderer
            if client is None:
                yield event.plain_result("文章客户端尚未就绪，请稍后再试。")
                return
            if renderer is None:
                yield event.plain_result(
                    "本地字体尚未就绪，无法生成正文图片，请管理员检查字体目录。"
                )
                return
            try:
                article = await client.fetch_article(
                    pending.kind,
                    pending.items[index - 1],
                )
                await event.send(event.plain_result("正文已获取，正在本地生成图片……"))
                document = build_article_document(article)
                async with self._render_semaphore:
                    image_path = await _run_tracked_file_job(
                        event,
                        renderer.render,
                        document,
                    )
            except JX3ApiError as exc:
                yield event.plain_result(exc.user_message)
                return
            except LocalRenderError:
                logger.warning("JX3Tools article image rendering failed")
                yield event.plain_result("正文图片生成失败，请稍后重试。")
                return
            selected_url = official_article_url(
                pending.kind,
                pending.items[index - 1],
            )
            if selected_url:
                await event.send(event.plain_result(selected_url))
            yield event.image_result(image_path)
        finally:
            if callable(stop_event):
                stop_event()

    async def terminate(self) -> None:
        """Close resources and clear ephemeral state idempotently."""
        self._initialized = False
        await self._clear_pending_articles()
        client = self._client
        self._client = None
        if client is not None:
            await client.close()
        self._renderer = None
        self._rate_limiter.clear()
        logger.info("Plugin astrbot_plugin_jx3tools terminated")

    def _validate_access(self, endpoint: EndpointSpec) -> None:
        if not self.settings.tier_enabled[endpoint.tier]:
            raise QueryInputError(f"{TIER_LABELS[endpoint.tier]}功能已由管理员关闭。")
        if endpoint.requires_token and not self.settings.token:
            raise QueryInputError("该功能需要 JX3API Token，请管理员在插件配置中填写。")
        if endpoint.requires_ticket and not self.settings.ticket:
            raise QueryInputError("该功能还需要推栏 Ticket，请管理员补充配置。")

    def _help_text(self, keyword: str) -> str:
        if keyword:
            normalized = keyword.casefold()
            exact = ENDPOINT_INDEX.get(normalized)
            if exact is not None:
                matches = [exact]
            else:
                matches = [
                    endpoint
                    for endpoint in ENDPOINTS
                    if normalized in endpoint.name.casefold()
                    or normalized in endpoint.description.casefold()
                    or any(
                        normalized in alias.casefold() for alias in endpoint.aliases
                    )
                ][:20]
            if not matches:
                return f"没有找到与“{keyword}”相关的功能。使用 /jx3 指令 查看分组。"
            lines = [f"【JX3Tools · 搜索“{keyword}”】", "说明：<参数> 必填，[参数] 可选。"]
            lines.extend(_endpoint_help_line(endpoint) for endpoint in matches)
            return "\n".join(lines)

        counts = {
            tier: sum(endpoint.tier is tier for endpoint in ENDPOINTS)
            for tier in ServiceTier
        }
        return "\n".join(
            (
                "【JX3Tools】",
                "用法：/jx3 <功能> [参数]",
                "说明：<参数> 必填，[参数] 可选。",
                "发现：/jx3 指令 [全部|免费|会员|其他]",
                "搜索：/jx3 帮助 <关键词>",
                "示例：/jx3 日常 梦江南",
                "示例：/jx3 角色 梦江南 角色名",
                "分组："
                + "，".join(
                    f"{TIER_LABELS[tier]} {counts[tier]} 项" for tier in ServiceTier
                ),
            )
        )

    def _list_text(self, keyword: str) -> str:
        normalized = keyword.casefold() if keyword else ""
        tier = TIER_SEARCH_ALIASES.get(normalized) if normalized else None
        show_all = not normalized or normalized in ALL_SEARCH_ALIASES
        selected = [
            endpoint for endpoint in ENDPOINTS if tier is None or endpoint.tier is tier
        ]
        title = TIER_LABELS[tier] if tier is not None else "全部"
        lines = [f"【JX3Tools · {title}功能】"]
        if keyword and tier is None and not show_all:
            lines.append("未知分组，已显示全部。可用：全部、免费、会员、其他。")
        for service_tier in ServiceTier:
            group = [endpoint for endpoint in selected if endpoint.tier is service_tier]
            if group:
                lines.append(
                    f"{TIER_LABELS[service_tier]}："
                    + "、".join(endpoint.name for endpoint in group)
                )
        lines.append("使用 /jx3 帮助 <功能名> 查看参数。")
        return "\n".join(lines)

    def _should_render_image(self, endpoint: EndpointSpec, data: Any) -> bool:
        if endpoint.output == "text":
            return False
        if endpoint.key in {"chitu.records", "chitu.week_records"} and not data:
            return False
        if self.settings.render_mode == "text":
            return False
        if endpoint.output == "image" or self.settings.render_mode == "image":
            return True
        return isinstance(data, Sequence) and not isinstance(
            data,
            (str, bytes, bytearray),
        ) and len(data) > 3

    async def _check_article_lock(
        self,
        event: AstrMessageEvent,
        endpoint: EndpointSpec,
    ) -> None:
        if endpoint.output != "article":
            return
        identity = _article_identity(event)
        if identity is None:
            raise QueryInputError("无法确认当前会话与发起者，不能开始文章选择。")
        session, sender_id = identity
        pending = self._pending_articles.get(session)
        if pending is None:
            return
        now = asyncio.get_running_loop().time()
        if now > pending.expires_at:
            await self._finish_article_selection(session, pending)
            return
        if pending.owner_id != sender_id:
            raise QueryInputError("当前会话已有其他用户发起的序号选择，请等待 10 秒。")

    async def _start_article_selection(
        self,
        event: AstrMessageEvent,
        endpoint: EndpointSpec,
        data: Any,
    ) -> tuple[PendingArticleSelection | None, str]:
        if not self._initialized:
            return None, "JX3Tools 正在停止，请稍后重试。"
        identity = _article_identity(event)
        if identity is None:
            return None, "无法确认当前会话与发起者，不能开始文章选择。"
        session, sender_id = identity
        previous = self._pending_articles.get(session)
        if previous is not None:
            now = asyncio.get_running_loop().time()
            if now > previous.expires_at:
                await self._finish_article_selection(session, previous)
            elif previous.owner_id != sender_id:
                return None, "当前会话已有其他用户发起的序号选择，请等待 10 秒。"
            else:
                await self._finish_article_selection(session, previous)
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes, bytearray)):
            return None, "接口未返回可选择的标题列表。"
        items = tuple(item for item in data if isinstance(item, Mapping))
        if endpoint.article_kind == "rework":
            items = items[:5]
        if not items:
            return None, "暂时没有可选择的内容。"
        pending = PendingArticleSelection(
            owner_id=sender_id,
            unified_msg_origin=session,
            endpoint_name=endpoint.name,
            kind=endpoint.article_kind,
            items=items,
            expires_at=asyncio.get_running_loop().time() + ARTICLE_SELECTION_SECONDS,
        )
        self._pending_articles[session] = pending
        pending.timeout_task = asyncio.create_task(
            self._expire_article_selection(session, pending),
            name=f"jx3tools-article-timeout-{endpoint.article_kind}",
        )
        lines = [f"【{endpoint.name}】"]
        for index, item in enumerate(items, start=1):
            title = " ".join(str(item.get("title", "未命名")).split())[:100]
            date = " ".join(
                str(item.get("date", item.get("time", ""))).split()
            )[:32]
            lines.append(f"{index}. {title}{f'（{date}）' if date else ''}")
        lines.append(f"请由发起者在 {int(ARTICLE_SELECTION_SECONDS)} 秒内回复纯数字序号。")
        return pending, "\n".join(lines)

    async def _expire_article_selection(
        self,
        session: str,
        pending: PendingArticleSelection,
    ) -> None:
        delay = max(
            0.0,
            pending.expires_at - asyncio.get_running_loop().time(),
        )
        try:
            await asyncio.sleep(delay)
            if self._pending_articles.get(session) is not pending:
                return
            self._pending_articles.pop(session, None)
            pending.timeout_task = None
            sent = await self.context.send_message(
                pending.unified_msg_origin,
                MessageChain().message("选择已超时，请重新发送对应查询指令。"),
            )
            if not sent:
                logger.info("JX3Tools article timeout notification was not delivered")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("JX3Tools article timeout notification failed")
        finally:
            if self._pending_articles.get(session) is pending:
                self._pending_articles.pop(session, None)

    async def _finish_article_selection(
        self,
        session: str,
        pending: PendingArticleSelection,
    ) -> None:
        if self._pending_articles.get(session) is pending:
            self._pending_articles.pop(session, None)
        task = pending.timeout_task
        pending.timeout_task = None
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _clear_pending_articles(self) -> None:
        pending = tuple(self._pending_articles.items())
        for session, selection in pending:
            await self._finish_article_selection(session, selection)

    async def _card_results(
        self,
        event: AstrMessageEvent,
        data: Any,
        text_result: str,
    ):
        yield event.plain_result(text_result)
        _server, _role, image_url = card_identity(data)
        if not image_url:
            yield event.plain_result("接口未返回可发送的名片图片。")
            return
        client = self._client
        renderer = self._renderer
        if client is None or renderer is None:
            yield event.plain_result("本地图片组件尚未就绪，请管理员检查字体目录。")
            return
        try:
            image_bytes = await client.fetch_media_image(image_url)
            async with self._render_semaphore:
                image_path = await _run_tracked_file_job(
                    event,
                    renderer.save_source_image,
                    image_bytes,
                )
        except JX3ApiError as exc:
            yield event.plain_result(exc.user_message)
            return
        except LocalRenderError:
            logger.warning("JX3Tools card image normalization failed")
            yield event.plain_result("名片图片处理失败，请稍后重试。")
            return
        yield event.image_result(image_path)

    async def _arena_profile_image(
        self,
        client: JX3ApiClient,
        parameters: Mapping[str, str | int],
    ) -> bytes | None:
        """Fetch an optional trusted role card without affecting arena results."""
        server = parameters.get("server")
        name = parameters.get("name")
        if not isinstance(server, str) or not isinstance(name, str):
            return None
        try:
            card = await client.request(
                ENDPOINT_INDEX["card.record"],
                {"server": server, "name": name},
            )
            _server, _role, image_url = card_identity(card)
            if not image_url:
                return None
            return await client.fetch_media_image(image_url)
        except JX3ApiError:
            logger.info("JX3Tools optional arena profile image was not downloaded")
            return None


def _endpoint_help_line(endpoint: EndpointSpec) -> str:
    lines = [f"- {endpoint.name}", f"  {endpoint.description}", f"  {endpoint.usage}"]
    if endpoint.key == "exam.search":
        lines.append("  示例：单选题：古琴有几根弦（DXTGQYJGX）")
    return "\n".join(lines)


def _session_key(event: AstrMessageEvent) -> str:
    unified = getattr(event, "unified_msg_origin", "")
    if isinstance(unified, str) and unified:
        return unified
    sender = event.get_sender_id()
    return str(sender) or "unknown"


def _article_identity(event: AstrMessageEvent) -> tuple[str, str] | None:
    """Return the stable session and sender identity required by article state."""
    unified = getattr(event, "unified_msg_origin", "")
    sender = event.get_sender_id()
    session_id = unified.strip() if isinstance(unified, str) else ""
    sender_id = str(sender).strip() if sender is not None else ""
    if not session_id or not sender_id:
        return None
    return session_id, sender_id


def _track_temporary_file(event: AstrMessageEvent, path: str) -> None:
    tracker = getattr(event, "track_temporary_local_file", None)
    if callable(tracker):
        tracker(path)


async def _run_tracked_file_job(
    event: AstrMessageEvent,
    function: Callable[..., str],
    /,
    *args: Any,
    **kwargs: Any,
) -> str:
    """Run one file-producing worker while retaining cleanup ownership."""
    path = temporary_image_path()
    path_text = str(path)
    _track_temporary_file(event, path_text)
    kwargs["output_path"] = path
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        result = await asyncio.shield(task)
        if Path(result) != path:
            path.unlink(missing_ok=True)
            _track_temporary_file(event, result)
        return result
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if task.done() and not task.cancelled():
            try:
                task.result()
            except Exception:
                logger.debug("JX3Tools cancelled file worker exited with an error")
        path.unlink(missing_ok=True)
        raise
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _friendly_api_error(endpoint: EndpointSpec | None, error: JX3ApiError) -> str:
    if endpoint is not None and endpoint.key == "trade.item_records":
        if "（404）" in error.user_message:
            return (
                "未找到该商品的物价记录。请先使用 /jx3 物品搜索 <关键词> "
                "取得精确商品名，再查询物价。"
            )
    return error.user_message
