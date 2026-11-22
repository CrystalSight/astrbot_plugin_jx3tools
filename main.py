"""AstrBot entry point for bounded JX3API queries and local images."""

from __future__ import annotations

import asyncio
from contextlib import aclosing
from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, get_astrbot_data_path

from .plugin.core.api import (
    JX3ApiClient,
    JX3ApiConfigurationError,
)
from .plugin.core.groups import GroupPolicies
from .plugin.core.push import PushService
from .plugin.core.rate_limit import SessionRateLimiter
from .plugin.core.settings import PluginSettings
from .plugin.presentation.image_renderer import (
    FontPaths,
    LocalImageRenderer,
    LocalRenderError,
)
from .plugin.queries import PendingArticleSelection, QueryOperations

PLUGIN_NAME = "astrbot_plugin_jx3tools"


class Jx3toolsPlugin(QueryOperations, Star):
    """Expose retained JX3API queries through one discoverable command."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | None = None,
    ) -> None:
        Star.__init__(self, context, config)
        self.config = config or {}
        self.settings = PluginSettings.from_config(self.config)
        self._groups = GroupPolicies(self.config, self.settings)
        self._push: PushService | None = None
        self.logger = getattr(self, "logger", logger)
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
        self._groups = GroupPolicies(self.config, self.settings)
        for error in self._groups.errors:
            self.logger.warning("JX3Tools configuration: %s", error)
        if self.settings.legacy_base_url_upgraded:
            self.logger.warning(
                "JX3Tools replaced the retired legacy API base URL with the current official service"
            )
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
            self.logger.warning(
                "JX3Tools local fonts are unavailable under plugin_data; image output will fall back to text"
            )

        if (
            self.settings.enabled
            or any(group.settings.enabled for group in self._groups.groups.values())
            or self._groups.targets
        ):
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
                self.logger.error("JX3Tools network configuration is invalid")
        if self._groups.targets and self._client is not None:
            self._push = PushService(
                self._groups.targets,
                allowed=self._push_allowed,
                send=self._send_push,
                saohua=self._random_saohua,
                read_kv=self.get_kv_data,
                write_kv=self.put_kv_data,
                logger=self.logger,
            )
            try:
                await self._push.start()
            except Exception:
                await self._push.stop()
                self._push = None
                self.logger.error(
                    "JX3Tools push initialization failed; reload after checking storage"
                )
        self._initialized = True
        self.logger.info("Plugin astrbot_plugin_jx3tools initialized")

    @filter.command("jx3", alias={"剑三", "剑网三", "在线", "装备"})
    async def jx3(self, event: AstrMessageEvent):
        """Dispatch the query through the public command."""
        async with aclosing(self.query_results(event)) as results:
            async for result in results:
                yield result

    @filter.regex(r"^\s*\d+\s*$")
    async def article_selection(self, event: AstrMessageEvent):
        """Dispatch a numeric reply to the pending article selection."""
        async with aclosing(self.selection_results(event)) as results:
            async for result in results:
                yield result

    async def terminate(self) -> None:
        """Close resources and clear ephemeral state idempotently."""
        self._initialized = False
        if self._push is not None:
            await self._push.stop()
            self._push = None
        await self._clear_pending_articles()
        client = self._client
        self._client = None
        if client is not None:
            await client.close()
        self._renderer = None
        self._rate_limiter.clear()
        self.logger.info("Plugin astrbot_plugin_jx3tools terminated")

    def _push_allowed(self, umo: str) -> bool:
        """Honor the current AstrBot session plugin selection before sending."""
        selected = self.context.get_config(umo).get("plugin_set", ["*"])
        return isinstance(selected, list) and (
            selected == ["*"] or PLUGIN_NAME in selected
        )

    async def _send_push(self, umo: str, text: str) -> bool:
        return await self.context.send_message(umo, MessageChain().message(text))
