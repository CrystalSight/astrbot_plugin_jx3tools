"""Bounded LV0 WebSocket intake and isolated group delivery."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .api import official_article_url
from .groups import GroupPolicy

SOCKET_URL = "wss://socket.nicemoe.cn"
QUEUE_SIZE = 100
QUEUE_TTL = 600.0
SEND_INTERVAL = 2.0
SEEN_TTL = 86400.0
MAX_SEEN = 20000
KV_KEY = "push_seen_v1"
BEIJING = timezone(timedelta(hours=8))


@dataclass(frozen=True, slots=True)
class PushEvent:
    """Validated content; no received objects escape into message components."""

    action: int
    text: str
    server: str
    fingerprint: str


def _text(detail: Mapping[str, Any], key: str, limit: int = 1024) -> str:
    value = detail.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("Invalid event field")
    if any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise ValueError("Invalid event control character")
    return value.strip()


def parse_push(payload: Any) -> PushEvent | None:
    """Validate the three supported envelopes and produce exact plain text."""
    if not isinstance(payload, Mapping) or payload.get("status") != "success":
        return None
    action = payload.get("action")
    if type(action) is not int or action not in (2001, 2002, 2003):
        return None
    detail = payload.get("detail")
    if not isinstance(detail, Mapping):
        return None
    server = ""
    try:
        if action == 2001:
            server = _text(detail, "server", 128)
            zone = _text(detail, "zone", 128)
            status = detail.get("status")
            if type(status) not in (str, int) or str(status) not in ("0", "1"):
                return None
            stamp = detail.get("time")
            if type(stamp) is not int:
                return None
            date = datetime.fromtimestamp(stamp, BEIJING).strftime("%Y-%m-%d %H:%M:%S")
            label = "已开服" if str(status) == "1" else "已关服"
            text = f"区服：{zone}-{server}\n{label}\n时间：{date}"
        elif action == 2002:
            title = _text(detail, "title")
            raw_url = _text(detail, "url", 2048)
            url = official_article_url("news", {"url": raw_url})
            if not url:
                return None
            date = _text(detail, "date", 128)
            text = f"标题：{title}\n链接：{url}\n日期：{date}"
        else:
            current = _text(detail, "now_version", 128)
            new = _text(detail, "new_version", 128)
            size = _text(detail, "package_size", 128)
            text = f"{current}\n↓  ↓  ↓  ↓\n{new}\n更新大小：{size}"
    except (ValueError, OverflowError, OSError):
        return None
    fingerprint = hashlib.sha256(f"{action}\n{text}".encode()).hexdigest()
    return PushEvent(action, text, server, fingerprint)


class PushService:
    """Own the socket, bounded queues, workers, and durable attempt ledger."""

    def __init__(
        self,
        targets: tuple[GroupPolicy, ...],
        *,
        allowed: Callable[[str], bool],
        send: Callable[[str, str], Awaitable[bool]],
        saohua: Callable[[], Awaitable[str]],
        read_kv: Callable[[str, Any], Awaitable[Any]],
        write_kv: Callable[[str, Any], Awaitable[None]],
        logger: Any,
    ) -> None:
        self.targets = targets
        self.allowed = allowed
        self.send = send
        self.saohua = saohua
        self.read_kv = read_kv
        self.write_kv = write_kv
        self.logger = logger
        self.queues: dict[str, asyncio.Queue[tuple[PushEvent, float, str]]] = {
            target.umo: asyncio.Queue(maxsize=QUEUE_SIZE) for target in targets
        }
        self._pending: set[str] = set()
        self._seen: dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task[None]] = []
        self._session: aiohttp.ClientSession | None = None
        self._running = False

    async def start(self) -> None:
        """Restore deduplication before any externally visible activity."""
        if self._running or not self.targets:
            return
        async with asyncio.timeout(10):
            saved = await self.read_kv(KV_KEY, {})
        now = time.time()
        if isinstance(saved, dict):
            valid = {
                key: float(stamp)
                for key, stamp in saved.items()
                if isinstance(key, str)
                and len(key) == 64
                and type(stamp) in (int, float)
                and math.isfinite(stamp)
                and now - SEEN_TTL < stamp <= now
            }
            self._seen = dict(
                sorted(valid.items(), key=lambda item: item[1])[-MAX_SEEN:]
            )
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20, sock_connect=20),
            trust_env=False,
        )
        self._running = True
        self._tasks = [
            asyncio.create_task(self._receive(), name="jx3tools-push-receive")
        ]
        self._tasks.extend(
            asyncio.create_task(self._deliver(target), name="jx3tools-push-deliver")
            for target in self.targets
        )
        for task in self._tasks:
            task.add_done_callback(self._task_finished)

    def _task_finished(self, task: asyncio.Task[None]) -> None:
        """Observe unexpected task failures without exposing received content."""
        if not task.cancelled() and task.exception() is not None:
            self.logger.error(
                "JX3Tools push background task stopped unexpectedly; reload required"
            )

    async def stop(self) -> None:
        """Stop scheduling, join all tasks, then close the network session."""
        self._running = False
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self._session is not None:
            await self._session.close()
            self._session = None
        for queue in self.queues.values():
            while not queue.empty():
                queue.get_nowait()
                queue.task_done()
        self._pending.clear()

    async def _receive(self) -> None:
        delay = 1.0
        while self._running:
            started = time.monotonic()
            try:
                assert self._session is not None
                async with self._session.ws_connect(
                    SOCKET_URL, heartbeat=30, max_msg_size=65536
                ) as socket:
                    self.logger.info("JX3Tools push socket connected")
                    async for message in socket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(message.data)
                            except (ValueError, RecursionError):
                                self.logger.warning(
                                    "JX3Tools skipped malformed push JSON"
                                )
                                continue
                            self.enqueue(payload)
                        elif message.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                        ):
                            break
            except (aiohttp.ClientError, TimeoutError, OSError):
                self.logger.warning(
                    "JX3Tools push connection unavailable; reconnect scheduled"
                )
            if time.monotonic() - started >= 60:
                delay = 1.0
            if self._running:
                await asyncio.sleep(min(60.0, delay * random.uniform(1.0, 1.2)))
                delay = min(60.0, delay * 2)

    def enqueue(self, payload: Any) -> None:
        """Fan out only validated, authorized, nonduplicate events."""
        if not self._running:
            return
        event = parse_push(payload)
        if event is None:
            return
        for target in self.targets:
            if event.action not in target.actions:
                continue
            if event.action == 2001 and event.server != target.settings.default_server:
                continue
            key = hashlib.sha256(
                f"{target.umo}\n{event.fingerprint}".encode()
            ).hexdigest()
            if key in self._pending or self._seen.get(key, 0) > time.time() - SEEN_TTL:
                continue
            queue = self.queues[target.umo]
            try:
                queue.put_nowait((event, time.monotonic(), key))
            except asyncio.QueueFull:
                self.logger.warning("JX3Tools push queue full; new event discarded")
            else:
                self._pending.add(key)

    async def _record_attempt(self, key: str) -> None:
        async with self._lock:
            now = time.time()
            seen = {
                k: stamp
                for k, stamp in self._seen.items()
                if now - SEEN_TTL < stamp <= now
            }
            seen[key] = now
            seen = dict(sorted(seen.items(), key=lambda item: item[1])[-MAX_SEEN:])
            async with asyncio.timeout(10):
                await self.write_kv(KV_KEY, seen)
            self._seen = seen

    async def _deliver(self, target: GroupPolicy) -> None:
        queue = self.queues[target.umo]
        next_send = 0.0
        while self._running:
            event, queued_at, key = await queue.get()
            try:
                await asyncio.sleep(max(0.0, next_send - time.monotonic()))
                if time.monotonic() - queued_at > QUEUE_TTL:
                    self.logger.warning("JX3Tools expired queued push discarded")
                    continue
                if not self.allowed(target.umo):
                    continue
                tail = await self.saohua()
                if not self._running or not self.allowed(target.umo):
                    continue
                if time.monotonic() - queued_at > QUEUE_TTL:
                    self.logger.warning("JX3Tools expired prepared push discarded")
                    continue
                await self._record_attempt(key)
                if not self._running or not self.allowed(target.umo):
                    continue
                if time.monotonic() - queued_at > QUEUE_TTL:
                    self.logger.warning("JX3Tools expired recorded push discarded")
                    continue
                next_send = time.monotonic() + SEND_INTERVAL
                async with asyncio.timeout(30):
                    delivered = await self.send(target.umo, f"{event.text}\n\n{tail}")
                if not delivered:
                    self.logger.warning(
                        "JX3Tools push platform unavailable; delivery not retried"
                    )
            except Exception:
                self.logger.warning(
                    "JX3Tools push delivery failed; delivery not retried"
                )
            finally:
                self._pending.discard(key)
                queue.task_done()
