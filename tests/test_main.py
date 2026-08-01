"""Verify command behavior, article locking, and lifecycle."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import astrbot_plugin_jx3tools.main as main_module
import pytest
from astrbot_plugin_jx3tools.core.api import JX3ApiError
from astrbot_plugin_jx3tools.main import Jx3toolsPlugin


class FakeEvent:
    """Minimal AstrBot event double for command replies."""

    def __init__(
        self,
        message: str,
        session: str = "webchat:session",
        sender: str = "sender-a",
    ) -> None:
        self.message_str = message
        self.unified_msg_origin = session
        self.sender = sender
        self.tracked: list[str] = []
        self.sent: list[str] = []
        self.stopped = False

    @staticmethod
    def plain_result(text: str) -> str:
        return text

    @staticmethod
    def image_result(url: str) -> str:
        return f"image:{url}"

    def get_sender_id(self) -> str:
        return self.sender

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(path)

    async def send(self, result: str) -> None:
        self.sent.append(result)

    def stop_event(self) -> None:
        self.stopped = True


class FakeContext:
    """Capture one-shot timeout notifications without a platform."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, session: str, message: Any) -> bool:
        self.sent.append((session, message.get_plain_text()))
        return True


class FakeClient:
    """Capture validated requests and return prepared data."""

    def __init__(self, data: Any) -> None:
        self.data = data
        self.calls: list[tuple[Any, dict[str, str | int]]] = []
        self.media_calls: list[str] = []
        self.closed = False

    async def request(self, endpoint: Any, parameters: dict[str, str | int]) -> Any:
        self.calls.append((endpoint, parameters))
        return self.data

    async def fetch_image(self, _url: str) -> bytes:
        return b"image-bytes"

    async def fetch_media_image(self, _url: str) -> bytes:
        self.media_calls.append(_url)
        return b"media-image-bytes"

    async def fetch_article(self, _kind: str, item: Any) -> dict[str, str]:
        return {
            "title": str(item["title"]),
            "date": str(item["date"]),
            "content": "<p>正文内容</p>",
        }

    async def close(self) -> None:
        self.closed = True


class FakeRenderer:
    """Return deterministic local paths without invoking Pillow."""

    @staticmethod
    def render(
        *_args: Any,
        output_path: str | Path | None = None,
        **_kwargs: Any,
    ) -> str:
        if output_path is None:
            return "jx3-result.png"
        path = Path(output_path)
        path.unlink(missing_ok=True)
        return str(path)

    @staticmethod
    def save_source_image(
        _data: bytes,
        *,
        output_path: str | Path | None = None,
    ) -> str:
        if output_path is None:
            return "jx3-card.png"
        path = Path(output_path)
        path.unlink(missing_ok=True)
        return str(path)


class RecordingRenderer(FakeRenderer):
    """Capture optional profile bytes passed to the result renderer."""

    def __init__(self) -> None:
        self.profile_image_bytes: bytes | None = None

    def render(
        self,
        *_args: Any,
        profile_image_bytes: bytes | None = None,
        output_path: str | Path | None = None,
        **_kwargs: Any,
    ) -> str:
        self.profile_image_bytes = profile_image_bytes
        return super().render(output_path=output_path)


def config(**overrides: Any) -> dict[str, Any]:
    """Return representative nested plugin configuration."""
    value: dict[str, Any] = {
        "general": {
            "enabled": True,
            "api_base_url": "https://api.jx3api.com",
            "default_server": "梦江南",
        },
        "credentials": {"token": "", "ticket": ""},
        "features": {
            "free_enabled": True,
            "member_enabled": True,
            "other_enabled": True,
        },
        "network": {
            "timeout_seconds": 10,
            "max_concurrency": 2,
            "requests_per_minute": 12,
            "max_response_kib": 4096,
        },
        "presentation": {"render_mode": "text", "max_items": 30},
    }
    for section, section_value in overrides.items():
        value.setdefault(section, {}).update(section_value)
    return value


async def collect(
    plugin: Jx3toolsPlugin,
    message: str,
    *,
    sender: str = "sender-a",
) -> list[str]:
    event = FakeEvent(message, sender=sender)
    return [result async for result in plugin.jx3(event)]


async def test_help_exact_match_hides_internal_service_metadata() -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())
    plugin._initialized = True

    help_results = await collect(plugin, "/jx3 帮助 角色")
    list_results = await collect(plugin, "/jx3 指令 会员")

    assert "角色基础资料" in help_results[0]
    assert "奇遇记录" not in help_results[0]
    assert "role.detail" not in help_results[0]
    assert "服务" not in help_results[0]
    assert "<区服>" in help_results[0]
    assert "会员一" not in list_results[0]
    assert "角色" in list_results[0]

    all_results = await collect(plugin, "/jx3 指令 全部")
    assert "未知分组" not in all_results[0]
    assert "鲜花" not in all_results[0]


async def test_missing_token_fails_before_network() -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())
    fake_client = FakeClient({"ignored": True})
    plugin._client = fake_client  # type: ignore[assignment]
    plugin._initialized = True

    results = await collect(plugin, "/jx3 角色 梦江南 夜温言")

    assert results == ["该功能需要 JX3API Token，请管理员在插件配置中填写。"]
    assert not fake_client.calls


async def test_open_status_uses_default_server_and_fixed_type() -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())
    fake_client = FakeClient({"zone": "电信区", "server": "梦江南", "status": 1})
    plugin._client = fake_client  # type: ignore[assignment]
    plugin._initialized = True

    results = await collect(plugin, "/jx3 开服")

    assert results == ["区服：电信区-梦江南\n开服状态：开服"]
    assert fake_client.calls[0][1] == {"server": "梦江南", "type": 1}


async def test_saohua_is_always_plain_content() -> None:
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(presentation={"render_mode": "image"}),
    )
    plugin._client = FakeClient({"id": 1, "text": "清风明月"})  # type: ignore[assignment]
    plugin._initialized = True

    results = await collect(plugin, "/jx3 骚话")

    assert results == ["清风明月"]


async def test_local_image_is_tracked_and_returned(monkeypatch) -> None:
    original_build_document = main_module.build_document
    build_calls = 0

    def count_builds(*args: Any, **kwargs: Any) -> Any:
        nonlocal build_calls
        build_calls += 1
        return original_build_document(*args, **kwargs)

    monkeypatch.setattr(main_module, "build_document", count_builds)
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(presentation={"render_mode": "image"}),
    )
    plugin._client = FakeClient({"war": "大战", "team": []})  # type: ignore[assignment]
    plugin._renderer = FakeRenderer()  # type: ignore[assignment]
    plugin._initialized = True
    event = FakeEvent("/jx3 日常")

    results = [result async for result in plugin.jx3(event)]

    assert len(event.tracked) == 1
    assert results == [f"image:{event.tracked[0]}"]
    assert build_calls == 1


async def test_item_search_sends_all_names_before_the_result_image() -> None:
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(
            credentials={"token": "token"},
            presentation={"render_mode": "image"},
        ),
    )
    plugin._client = FakeClient(
        [
            {"name": "物品甲", "view": "https://nico.nicemoe.cn/item.png"},
            {"name": "物品乙"},
        ]
    )  # type: ignore[assignment]
    plugin._renderer = FakeRenderer()  # type: ignore[assignment]
    plugin._initialized = True

    results = await collect(plugin, "/jx3 物品搜索 物品")

    assert results[0] == "物品甲\n物品乙"
    assert results[1].startswith("image:")


async def test_card_sends_identity_then_direct_local_image() -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())
    plugin.settings = plugin.settings.__class__.from_config(
        config(credentials={"token": "token"})
    )
    fake_client = FakeClient(
        {
            "zoneName": "双线区",
            "serverName": "天鹅坪",
            "roleName": "侠士",
            "showAvatar": "https://www.jx3api.com/card.png",
        }
    )
    plugin._client = fake_client  # type: ignore[assignment]
    plugin._renderer = FakeRenderer()  # type: ignore[assignment]
    plugin._initialized = True
    event = FakeEvent("/jx3 名片 天鹅坪 侠士")

    results = [result async for result in plugin.jx3(event)]

    assert results == [
        "区服：双线区-天鹅坪\n角色名：侠士",
        f"image:{event.tracked[0]}",
    ]
    assert all("https://" not in result for result in results)
    assert fake_client.media_calls == ["https://www.jx3api.com/card.png"]


@pytest.mark.parametrize("card_fails", (False, True))
async def test_arena_profile_image_is_optional_and_reuses_query_identity(
    card_fails: bool,
) -> None:
    class ArenaClient(FakeClient):
        async def request(
            self,
            endpoint: Any,
            parameters: dict[str, str | int],
        ) -> Any:
            self.calls.append((endpoint, parameters))
            if endpoint.key == "arena.recent":
                return {
                    "zoneName": "双线区",
                    "serverName": "天鹅坪",
                    "roleName": "侠士",
                    "forceName": "万花",
                    "performance": {
                        "3v3": {
                            "mmr": 2200,
                            "grade": 12,
                            "ranking": 10,
                            "winCount": 8,
                            "totalCount": 10,
                            "mvpCount": 3,
                        }
                    },
                }
            if card_fails:
                raise JX3ApiError("名片查询失败。")
            return {
                "zoneName": "双线区",
                "serverName": "天鹅坪",
                "roleName": "侠士",
                "showAvatar": "https://www.jx3api.com/card.png",
            }

    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(
            credentials={"token": "token", "ticket": "ticket"},
            presentation={"render_mode": "image"},
        ),
    )
    client = ArenaClient(None)
    renderer = RecordingRenderer()
    plugin._client = client  # type: ignore[assignment]
    plugin._renderer = renderer  # type: ignore[assignment]
    plugin._initialized = True

    results = await collect(plugin, "/jx3 名剑战绩 天鹅坪 侠士")

    assert len(results) == 1 and results[0].startswith("image:")
    assert [call[0].key for call in client.calls] == [
        "arena.recent",
        "card.record",
    ]
    assert client.calls[1][1] == {"server": "天鹅坪", "name": "侠士"}
    assert renderer.profile_image_bytes == (
        None if card_fails else b"media-image-bytes"
    )
    assert client.media_calls == (
        [] if card_fails else ["https://www.jx3api.com/card.png"]
    )


@pytest.mark.parametrize("command", ("/jx3 新闻 2", "/jx3 公告 2", "/jx3 技改"))
async def test_article_selection_continues_after_progress_in_framework_order(
    command: str,
) -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())
    plugin._client = FakeClient(
        [
            {
                "id": 1,
                "title": "第一条",
                "date": "2026-07-18",
                "url": "https://jx3.xoyo.com/announce/gg.html?id=1335601",
            },
            {
                "id": 2,
                "title": "第二条",
                "date": "2026-07-17",
                "url": "https://jx3.xoyo.com/announce/gg.html?id=1335602",
            },
        ]
    )  # type: ignore[assignment]
    plugin._renderer = FakeRenderer()  # type: ignore[assignment]
    plugin._initialized = True

    command_event = FakeEvent(command, sender="sender-a")
    command_results = plugin.jx3(command_event)
    start = await anext(command_results)
    pending = plugin._pending_articles[command_event.unified_msg_origin]
    timeout_task = pending.timeout_task
    with pytest.raises(StopAsyncIteration):
        await anext(command_results)
    other_event = FakeEvent("1", sender="sender-b")
    other = [result async for result in plugin.article_selection(other_event)]
    owner_event = FakeEvent("2", sender="sender-a")
    selection_results = plugin.article_selection(owner_event)

    assert "10 秒内" in start
    assert other == ["当前序号选择仅限本次查询的发起者操作。"]
    assert await anext(selection_results) == f"image:{owner_event.tracked[0]}"
    assert not owner_event.stopped
    with pytest.raises(StopAsyncIteration):
        await anext(selection_results)
    assert owner_event.stopped
    expected_sent = [
        "已选择第 2 条，正在读取新闻正文……".replace(
            "新闻",
            command.split()[1],
        ),
        "正文已获取，正在本地生成图片……",
    ]
    if command == "/jx3 技改":
        expected_sent.append(
            "https://jx3.xoyo.com/announce/gg.html?id=1335602"
        )
    assert owner_event.sent == expected_sent
    assert pending.timeout_task is None
    assert timeout_task is not None and timeout_task.cancelled()
    assert not plugin._pending_articles


async def test_article_selection_notifies_timeout_after_list_stream_finishes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(main_module, "ARTICLE_SELECTION_SECONDS", 0.01)
    context = FakeContext()
    plugin = Jx3toolsPlugin(context=context, config=config())  # type: ignore[arg-type]
    plugin._client = FakeClient(
        [{"id": 1, "title": "第一条", "date": "2026-07-18"}]
    )  # type: ignore[assignment]
    plugin._initialized = True

    results = plugin.jx3(FakeEvent("/jx3 新闻 1"))
    start = await anext(results)

    assert "0 秒内" in start
    with pytest.raises(StopAsyncIteration):
        await anext(results)
    await asyncio.sleep(0.02)
    assert context.sent == [
        (
            "webchat:session",
            "选择已超时，请重新发送对应查询指令。",
        )
    ]
    assert not plugin._pending_articles


async def test_article_replacement_and_termination_wake_old_waiters() -> None:
    context = FakeContext()
    plugin = Jx3toolsPlugin(context=context, config=config())  # type: ignore[arg-type]
    plugin._client = FakeClient(
        [{"id": 1, "title": "第一条", "date": "2026-07-18"}]
    )  # type: ignore[assignment]
    plugin._initialized = True

    first_results = plugin.jx3(FakeEvent("/jx3 新闻 1"))
    assert "第一条" in await anext(first_results)
    first_task = plugin._pending_articles["webchat:session"].timeout_task
    with pytest.raises(StopAsyncIteration):
        await anext(first_results)
    second_results = plugin.jx3(FakeEvent("/jx3 公告 1"))
    assert "第一条" in await anext(second_results)
    second_task = plugin._pending_articles["webchat:session"].timeout_task
    with pytest.raises(StopAsyncIteration):
        await anext(second_results)

    await plugin.terminate()

    assert first_task is not None and first_task.cancelled()
    assert second_task is not None and second_task.cancelled()
    assert not context.sent
    assert not plugin._pending_articles


async def test_racing_article_queries_do_not_replace_another_user() -> None:
    class RacingClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([{"id": 1, "title": "第一条", "date": "2026-07-18"}])
            self.first_started = asyncio.Event()
            self.release_first = asyncio.Event()

        async def request(
            self,
            endpoint: Any,
            parameters: dict[str, str | int],
        ) -> Any:
            self.calls.append((endpoint, parameters))
            if len(self.calls) == 1:
                self.first_started.set()
                await self.release_first.wait()
            return self.data

    context = FakeContext()
    plugin = Jx3toolsPlugin(context=context, config=config())  # type: ignore[arg-type]
    client = RacingClient()
    plugin._client = client  # type: ignore[assignment]
    plugin._initialized = True

    first = asyncio.create_task(collect(plugin, "/jx3 新闻 1", sender="sender-a"))
    await client.first_started.wait()
    second = await collect(plugin, "/jx3 公告 1", sender="sender-b")
    client.release_first.set()
    first_result = await first

    assert "【公告】" in second[0]
    assert first_result == ["当前会话已有其他用户发起的序号选择，请等待 10 秒。"]
    assert plugin._pending_articles["webchat:session"].owner_id == "sender-b"
    await plugin.terminate()


async def test_article_state_requires_nonempty_session_and_sender() -> None:
    context = FakeContext()
    plugin = Jx3toolsPlugin(context=context, config=config())  # type: ignore[arg-type]
    client = FakeClient([{"id": 1, "title": "第一条", "date": "2026-07-18"}])
    plugin._client = client  # type: ignore[assignment]
    plugin._initialized = True

    missing_event = FakeEvent("/jx3 新闻 1", session="", sender="")
    rejected = [result async for result in plugin.jx3(missing_event)]
    assert rejected == ["无法确认当前会话与发起者，不能开始文章选择。"]
    assert not client.calls

    await collect(plugin, "/jx3 新闻 1", sender="sender-a")
    invalid_selection = FakeEvent("1", session="", sender="")
    selection_result = [
        result async for result in plugin.article_selection(invalid_selection)
    ]
    assert selection_result == ["无法确认当前会话与发起者，不能处理文章序号。"]
    assert plugin._pending_articles["webchat:session"].owner_id == "sender-a"
    await plugin.terminate()


async def test_terminate_during_article_request_creates_no_timeout_task() -> None:
    class DelayedClient(FakeClient):
        def __init__(self) -> None:
            super().__init__([{"id": 1, "title": "第一条", "date": "2026-07-18"}])
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def request(
            self,
            endpoint: Any,
            parameters: dict[str, str | int],
        ) -> Any:
            self.calls.append((endpoint, parameters))
            self.started.set()
            await self.release.wait()
            return self.data

    plugin = Jx3toolsPlugin(context=FakeContext(), config=config())  # type: ignore[arg-type]
    client = DelayedClient()
    plugin._client = client  # type: ignore[assignment]
    plugin._initialized = True

    request_task = asyncio.create_task(collect(plugin, "/jx3 新闻 1"))
    await client.started.wait()
    await plugin.terminate()
    client.release.set()

    assert await request_task == ["JX3Tools 正在停止，请稍后重试。"]
    assert not plugin._pending_articles


async def test_cancelled_file_worker_is_awaited_and_removes_reserved_path() -> None:
    started = threading.Event()
    release = threading.Event()
    event = FakeEvent("/jx3 日常")

    def worker(*, output_path: str | Path) -> str:
        path = Path(output_path)
        path.write_bytes(b"partial")
        started.set()
        release.wait(timeout=2.0)
        path.write_bytes(b"complete")
        return str(path)

    task = asyncio.create_task(main_module._run_tracked_file_job(event, worker))
    assert await asyncio.to_thread(started.wait, 2.0)
    path = Path(event.tracked[0])
    assert await asyncio.to_thread(path.is_file)

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not await asyncio.to_thread(path.exists)


async def test_rate_limit_prevents_second_network_call() -> None:
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(network={"requests_per_minute": 1}),
    )
    fake_client = FakeClient({"text": "ok"})
    plugin._client = fake_client  # type: ignore[assignment]
    plugin._initialized = True

    first = await collect(plugin, "/jx3 骚话")
    second = await collect(plugin, "/jx3 骚话")

    assert first == ["ok"]
    assert "请求过于频繁" in second[0]
    assert len(fake_client.calls) == 1


async def test_lifecycle_opens_and_closes_session_idempotently() -> None:
    plugin = Jx3toolsPlugin(context=object(), config=config())

    await plugin.initialize()
    client = plugin._client
    assert client is not None and client.started

    await plugin.initialize()
    await plugin.terminate()
    await plugin.terminate()

    assert not client.started
    assert not plugin._initialized


async def test_invalid_base_url_keeps_plugin_loaded_with_safe_error() -> None:
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(general={"api_base_url": "http://unsafe.example"}),
    )

    await plugin.initialize()
    results = await collect(plugin, "/jx3 骚话")
    await plugin.terminate()

    assert results == ["JX3API 基础地址无效，请管理员配置不含路径的 HTTPS 地址。"]


async def test_reinitialize_clears_a_resolved_startup_error() -> None:
    plugin = Jx3toolsPlugin(
        context=object(),
        config=config(general={"api_base_url": "http://unsafe.example"}),
    )

    await plugin.initialize()
    await plugin.terminate()
    plugin.config["general"]["api_base_url"] = "https://api.jx3api.com"
    await plugin.initialize()
    try:
        assert plugin._startup_error == ""
        assert plugin._client is not None and plugin._client.started
    finally:
        await plugin.terminate()
