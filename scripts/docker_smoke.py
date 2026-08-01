"""Run credential-safe read-only smoke checks inside a matching AstrBot container."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from PIL import Image

from ..core.api import JX3ApiClient, JX3ApiError
from ..core.endpoints import ENDPOINT_INDEX, EndpointSpec
from ..core.settings import PluginSettings
from ..main import Jx3toolsPlugin
from ..presentation.image_renderer import (
    FontPaths,
    LocalImageRenderer,
)
from ..presentation.rendering import (
    RenderDocument,
    build_article_document,
    build_document,
    card_identity,
    item_search_names,
)

LEGACY_BACKUP_BASE_URL = "https://api.jx3api.com"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="/AstrBot/data/config/astrbot_plugin_jx3tools_config.json",
    )
    parser.add_argument(
        "--fonts",
        default="/AstrBot/data/plugin_data/astrbot_plugin_jx3tools/fonts",
    )
    parser.add_argument(
        "--trade-only",
        action="store_true",
        help="Run only item-search and item-record checks.",
    )
    parser.add_argument(
        "--foods-only",
        action="store_true",
        help="Run only the school-food query and render check.",
    )
    parser.add_argument(
        "--articles-only",
        action="store_true",
        help="Run only article list, body, and event-chain checks.",
    )
    parser.add_argument(
        "--legacy-backup",
        action="store_true",
        help="Use the fixed legacy JX3API backup without changing saved config.",
    )
    parser.add_argument(
        "--arena-only",
        action="store_true",
        help="Run one end-to-end arena query with optional profile artwork.",
    )
    parser.add_argument("--arena-server", default="")
    parser.add_argument("--arena-name", default="")
    parser.add_argument("--arena-mode", type=int, default=33, choices=(22, 33, 55))
    return parser.parse_args()


def shape(value: Any) -> str:
    """Return a non-sensitive structural summary."""
    if isinstance(value, Mapping):
        return f"mapping:{len(value)}"
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return f"sequence:{len(value)}"
    return type(value).__name__


class SmokeEvent:
    """Minimal real-AstrBot event double for handler-order smoke checks."""

    def __init__(self, message: str) -> None:
        self.message_str = message
        self.unified_msg_origin = "webchat:FriendMessage:docker-smoke"
        self.tracked: list[str] = []
        self.sent: list[Any] = []
        self.stopped = False

    @staticmethod
    def plain_result(text: str) -> str:
        return text

    @staticmethod
    def image_result(path: str) -> str:
        return path

    @staticmethod
    def get_sender_id() -> str:
        return "docker-smoke-user"

    def track_temporary_local_file(self, path: str) -> None:
        self.tracked.append(path)

    async def send(self, result: Any) -> None:
        self.sent.append(result)

    def stop_event(self) -> None:
        self.stopped = True


class ArenaSmokeRenderer:
    """Record whether a real profile image reached the local renderer."""

    def __init__(self, delegate: LocalImageRenderer) -> None:
        self.delegate = delegate
        self.profile_bytes = 0

    def render(
        self,
        document: RenderDocument,
        *,
        icon_bytes: bytes | None = None,
        profile_image_bytes: bytes | None = None,
        output_path: str | Path | None = None,
    ) -> str:
        self.profile_bytes = len(profile_image_bytes or b"")
        return self.delegate.render(
            document,
            icon_bytes=icon_bytes,
            profile_image_bytes=profile_image_bytes,
            output_path=output_path,
        )


async def run() -> int:
    args = parse_args()
    config_text = await asyncio.to_thread(
        Path(args.config).read_text,
        encoding="utf-8-sig",
    )
    document = json.loads(config_text)
    settings = PluginSettings.from_config(document)
    client = JX3ApiClient(
        base_url=(
            LEGACY_BACKUP_BASE_URL if args.legacy_backup else settings.api_base_url
        ),
        token=settings.token,
        ticket=settings.ticket,
        timeout_seconds=settings.timeout_seconds,
        max_concurrency=settings.max_concurrency,
        max_response_bytes=settings.max_response_bytes,
    )
    renderer = LocalImageRenderer(FontPaths.from_directory(Path(args.fonts)))
    results: list[dict[str, str]] = []
    failures = 0

    async def query(
        key: str,
        parameters: dict[str, str | int] | None = None,
        *,
        allow_no_data: bool = False,
    ) -> tuple[EndpointSpec, Any | None]:
        nonlocal failures
        endpoint = ENDPOINT_INDEX[key]
        if endpoint.requires_token and not settings.token:
            results.append({"key": key, "status": "SKIP", "detail": "token missing"})
            return endpoint, None
        if endpoint.requires_ticket and not settings.ticket:
            results.append({"key": key, "status": "SKIP", "detail": "ticket missing"})
            return endpoint, None
        payload = dict(parameters or {})
        payload.update(dict(endpoint.fixed_parameters))
        try:
            data = await client.request(endpoint, payload)
        except JX3ApiError as exc:
            if allow_no_data and ("暂无" in exc.user_message or "400" in exc.user_message):
                results.append({"key": key, "status": "PASS", "detail": "no data"})
                return endpoint, None
            results.append({"key": key, "status": "FAIL", "detail": exc.user_message})
            failures += 1
            return endpoint, None
        results.append({"key": key, "status": "PASS", "detail": shape(data)})
        return endpoint, data

    def render(endpoint: EndpointSpec, data: Any, icon: bytes | None = None) -> None:
        nonlocal failures
        try:
            render_document = build_document(endpoint, data, max_items=30)
            output = Path(renderer.render(render_document, icon_bytes=icon))
            size = output.stat().st_size
            output.unlink(missing_ok=True)
            if size <= 0:
                raise ValueError("empty output")
            results.append(
                {"key": f"render:{endpoint.key}", "status": "PASS", "detail": f"png:{size}"}
            )
        except Exception as exc:  # noqa: BLE001 - smoke report only
            failures += 1
            results.append(
                {"key": f"render:{endpoint.key}", "status": "FAIL", "detail": type(exc).__name__}
            )

    def diagnose_tianluo_foods(endpoint: EndpointSpec, data: Any) -> None:
        """Compare raw, unique, and rendered Tianluo food counts."""
        nonlocal failures
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes, bytearray)):
            failures += 1
            results.append(
                {
                    "key": "diagnose:school.foods:tianluo",
                    "status": "FAIL",
                    "detail": "unexpected payload",
                }
            )
            return
        raw_values: list[str] = []
        for item in data:
            if not isinstance(item, Mapping) or str(item.get("kungfu", "")) != "天罗诡道":
                continue
            name = str(item.get("name", "小药")).strip() or "小药"
            detail = str(item.get("boost", item.get("desc", "-"))).strip() or "-"
            raw_values.append(name if detail == "-" else f"{name}（{detail}）")
        unique_values = tuple(dict.fromkeys(raw_values))
        document = build_document(endpoint, data, max_items=1)
        rendered_values = next(
            (row.items for row in document.food_rows if row.kungfu == "天罗诡道"),
            (),
        )
        passed = rendered_values == unique_values
        if not passed:
            failures += 1
        results.append(
            {
                "key": "diagnose:school.foods:tianluo",
                "status": "PASS" if passed else "FAIL",
                "detail": (
                    f"raw:{len(raw_values)} unique:{len(unique_values)} "
                    f"rendered:{len(rendered_values)}"
                ),
            }
        )

    async def collect_results(source: Any) -> list[Any]:
        return [result async for result in source]

    async def fetch_optional_icon(key: str, url: str) -> bytes | None:
        """Mirror runtime fallback when an optional upstream icon is unusable."""
        if not url:
            return None
        try:
            return await client.fetch_image(url)
        except JX3ApiError:
            results.append(
                {
                    "key": f"optional-icon:{key}",
                    "status": "PASS",
                    "detail": "rejected safely; render continues without icon",
                }
            )
            return None

    async def check_trade() -> None:
        nonlocal failures
        item_endpoint, items = await query(
            "trade.item_search",
            {"name": "十五"},
        )
        if items is None:
            return
        item_document = build_document(item_endpoint, items, max_items=30)
        copied_names = item_search_names(items)
        if not copied_names:
            failures += 1
            results.append(
                {
                    "key": "copy:trade.item_search",
                    "status": "FAIL",
                    "detail": "names missing",
                }
            )
        else:
            results.append(
                {
                    "key": "copy:trade.item_search",
                    "status": "PASS",
                    "detail": f"names:{len(copied_names.splitlines())}",
                }
            )
        icon = await fetch_optional_icon(item_endpoint.key, item_document.icon_url)
        render(item_endpoint, items, icon)
        first = items[0] if isinstance(items, Sequence) and items else items
        if not isinstance(first, Mapping) or not first.get("name"):
            return
        record_parameters: dict[str, str | int] = {"name": str(first["name"])}
        if settings.default_server:
            record_parameters["server"] = settings.default_server
        records_endpoint, records = await query(
            "trade.item_records",
            record_parameters,
        )
        if records is None:
            return
        record_document = build_document(records_endpoint, records, max_items=30)
        record_icon = await fetch_optional_icon(
            records_endpoint.key,
            record_document.icon_url,
        )
        render(records_endpoint, records, record_icon)

    await client.start()
    if args.arena_only:
        wrapper = ArenaSmokeRenderer(renderer)
        plugin = Jx3toolsPlugin(context=object(), config=document)
        plugin._client = client
        plugin._renderer = wrapper  # type: ignore[assignment]
        plugin._initialized = True
        event = SmokeEvent(
            f"/jx3 名剑战绩 {args.arena_server} {args.arena_name} {args.arena_mode}"
        )
        output: Path | None = None
        try:
            if not args.arena_server or not args.arena_name:
                failures += 1
                results.append(
                    {
                        "key": "event:arena.recent",
                        "status": "FAIL",
                        "detail": "server and name are required",
                    }
                )
            else:
                responses = [result async for result in plugin.jx3(event)]
                if len(responses) == 1 and isinstance(responses[0], str):
                    candidate = Path(responses[0])
                    if await asyncio.to_thread(candidate.is_file):
                        output = candidate
                if output is not None:
                    with Image.open(output) as rendered:
                        dimensions = f"{rendered.width}x{rendered.height}"
                else:
                    dimensions = "no image"
                passed = output is not None and wrapper.profile_bytes > 0
                if not passed:
                    failures += 1
                results.append(
                    {
                        "key": "event:arena.recent",
                        "status": "PASS" if passed else "FAIL",
                        "detail": (
                            f"profile:{wrapper.profile_bytes} bytes; png:{dimensions}"
                        ),
                    }
                )
        finally:
            if output is not None:
                await asyncio.to_thread(output.unlink, missing_ok=True)
            await plugin.terminate()
        print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False))
        return 1 if failures else 0
    if args.foods_only:
        try:
            foods_endpoint, foods = await query("school.foods")
            if foods is not None:
                diagnose_tianluo_foods(foods_endpoint, foods)
                render(foods_endpoint, foods)
        finally:
            await client.close()
        print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False))
        return 1 if failures else 0
    if args.trade_only:
        try:
            await check_trade()
        finally:
            await client.close()
        print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False))
        return 1 if failures else 0
    try:
        if not args.articles_only:
            monthly_endpoint, monthly = await query("active.list_calendar")
            if monthly is not None:
                render(monthly_endpoint, monthly)

            await query("active.celebs", {"name": "觅宝会"})
            await query("exam.search", {"subject": "DXTGQYJGX", "limit": 3})

            foods_endpoint, foods = await query("school.foods")
            if foods is not None:
                diagnose_tianluo_foods(foods_endpoint, foods)
                render(foods_endpoint, foods)

        article_items: dict[str, Sequence[Any]] = {}
        for article_key in ("news.allnews", "news.announce", "skill.rework"):
            endpoint, items = await query(
                article_key,
                {"limit": 2} if article_key != "skill.rework" else {},
            )
            if isinstance(items, Sequence) and not isinstance(
                items,
                (str, bytes, bytearray),
            ):
                article_items[article_key] = items
            if isinstance(items, Sequence) and items and isinstance(items[0], Mapping):
                try:
                    article = await client.fetch_article(endpoint.article_kind, items[0])
                    output = Path(renderer.render(build_article_document(article)))
                    await asyncio.to_thread(output.unlink, missing_ok=True)
                    results.append(
                        {"key": f"article:{article_key}", "status": "PASS", "detail": "body png"}
                    )
                except Exception as exc:  # noqa: BLE001 - smoke report only
                    failures += 1
                    results.append(
                        {"key": f"article:{article_key}", "status": "FAIL", "detail": type(exc).__name__}
                    )

        article_commands = {
            "news.allnews": "/jx3 新闻 1",
            "news.announce": "/jx3 公告 1",
            "skill.rework": "/jx3 技改",
        }
        for article_key, article_command in article_commands.items():
            if not article_items.get(article_key):
                continue
            plugin = Jx3toolsPlugin(context=object(), config=document)
            plugin._client = client
            plugin._renderer = renderer
            plugin._initialized = True
            command_event = SmokeEvent(article_command)
            command_results = plugin.jx3(command_event)
            selection_event = SmokeEvent("1")
            command_tail: asyncio.Task[list[Any]] | None = None
            try:
                start_message = await anext(command_results)
                command_tail = asyncio.create_task(collect_results(command_results))
                selection_results = [
                    result
                    async for result in plugin.article_selection(selection_event)
                ]
                tail_results = await command_tail
                image_path = Path(selection_results[-1])
                image_exists = await asyncio.to_thread(image_path.is_file)
                sent_urls = [
                    value
                    for value in selection_event.sent
                    if isinstance(value, str) and value.startswith("https://")
                ]
                is_rework = article_key == "skill.rework"
                passed = (
                    "10 秒内" in start_message
                    and len(selection_results) == 1
                    and len(selection_event.sent) == (3 if is_rework else 2)
                    and len(sent_urls) == (1 if is_rework else 0)
                    and (
                        not is_rework
                        or sent_urls[0].startswith(
                            "https://jx3.xoyo.com/announce/gg.html?id="
                        )
                    )
                    and image_exists
                    and selection_event.stopped
                    and not tail_results
                )
                await asyncio.to_thread(image_path.unlink, missing_ok=True)
                results.append(
                    {
                        "key": f"event:{article_key}",
                        "status": "PASS" if passed else "FAIL",
                        "detail": "no false timeout; approved URL policy and body png",
                    }
                )
                if not passed:
                    failures += 1
            except Exception as exc:  # noqa: BLE001 - smoke report only
                if command_tail is not None and not command_tail.done():
                    command_tail.cancel()
                    await asyncio.gather(command_tail, return_exceptions=True)
                for tracked in selection_event.tracked:
                    await asyncio.to_thread(Path(tracked).unlink, missing_ok=True)
                failures += 1
                results.append(
                    {
                        "key": f"event:{article_key}",
                        "status": "FAIL",
                        "detail": type(exc).__name__,
                    }
                )

        if args.articles_only:
            print(
                json.dumps(
                    {"failures": failures, "results": results},
                    ensure_ascii=False,
                )
            )
            return 1 if failures else 0

        gold_parameters: dict[str, str | int] = {}
        if settings.default_server:
            gold_parameters["server"] = settings.default_server
        gold_endpoint, gold = await query("trade.demon", gold_parameters)
        if gold is not None:
            render(gold_endpoint, gold)

        monster_endpoint, monster = await query("active.monster")
        if monster is not None:
            render(monster_endpoint, monster)

        await check_trade()

        card_endpoint, card = await query("card.random")
        if card is not None:
            _server, _role, image_url = card_identity(card)
            image = await client.fetch_media_image(image_url)
            output = Path(renderer.save_source_image(image))
            await asyncio.to_thread(output.unlink, missing_ok=True)
            results.append(
                {"key": f"media:{card_endpoint.key}", "status": "PASS", "detail": f"bytes:{len(image)}"}
            )

        await query("mech.calculator")
        await query("chitu.records", allow_no_data=True)
        await query("chitu.week_records", allow_no_data=True)
    finally:
        await client.close()
    print(json.dumps({"failures": failures, "results": results}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
