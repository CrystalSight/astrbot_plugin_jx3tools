"""Exercise article selection through AstrBot's real WebChat transport."""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import aiohttp

TIMEOUT_TEXT = "选择已超时，请重新发送对应查询指令。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:6185")
    parser.add_argument("--config", default="/AstrBot/data/cmd_config.json")
    parser.add_argument("--selection-timeout", type=float, default=90.0)
    return parser.parse_args()


def validate_base_url(value: str) -> str:
    """Allow dashboard credentials to reach only a local HTTP listener."""
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise RuntimeError("WebChat base URL has an invalid port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
    ):
        raise RuntimeError("WebChat base URL must be a local HTTP origin with a port")
    return value.rstrip("/")


def load_jwt_secret(config_path: str) -> str:
    document = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    secret = document.get("dashboard", {}).get("jwt_secret")
    if not isinstance(secret, str) or not secret:
        raise RuntimeError("Dashboard JWT secret is unavailable")
    return secret


def encode_dashboard_token(username: str, secret: str, now: int) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"username": username, "iat": now, "exp": now + 300}

    def encode_part(value: dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    unsigned = f"{encode_part(header)}.{encode_part(payload)}"
    signature = hmac.new(
        secret.encode(),
        unsigned.encode(),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{unsigned}.{encoded_signature}"


def chat_message(session_id: str, message_id: str, text: str) -> dict[str, Any]:
    return {
        "ct": "chat",
        "t": "send",
        "session_id": session_id,
        "message_id": message_id,
        "message": [{"type": "plain", "text": text}],
        "enable_streaming": False,
    }


async def receive_request(
    websocket: aiohttp.ClientWebSocketResponse,
    message_id: str,
    *,
    timeout_seconds: float,
) -> tuple[list[dict[str, Any]], float]:
    frames: list[dict[str, Any]] = []
    first_result_at: float | None = None
    started_at = time.monotonic()
    async with asyncio.timeout(timeout_seconds):
        while True:
            message = await websocket.receive()
            if message.type is aiohttp.WSMsgType.TEXT:
                payload = json.loads(message.data)
                if not isinstance(payload, dict):
                    continue
                if payload.get("message_id") == message_id:
                    frames.append(payload)
                    if payload.get("type") in {"plain", "image", "file"}:
                        first_result_at = first_result_at or time.monotonic()
                    if payload.get("type") == "end":
                        finished_at = time.monotonic()
                        return frames, finished_at - (first_result_at or started_at)
                elif payload.get("t") == "error":
                    raise RuntimeError(f"WebChat returned {payload.get('code', 'error')}")
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            }:
                raise RuntimeError("WebChat closed before the request completed")


async def receive_timeout_notification(
    websocket: aiohttp.ClientWebSocketResponse,
    *,
    timeout_seconds: float,
) -> bool:
    async with asyncio.timeout(timeout_seconds):
        while True:
            message = await websocket.receive()
            if message.type is aiohttp.WSMsgType.TEXT:
                payload = json.loads(message.data)
                if (
                    isinstance(payload, dict)
                    and payload.get("type") == "plain"
                    and payload.get("data") == TIMEOUT_TEXT
                ):
                    return True
                if isinstance(payload, dict) and payload.get("t") == "error":
                    raise RuntimeError(
                        f"WebChat returned {payload.get('code', 'error')}"
                    )
            elif message.type in {
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.ERROR,
            }:
                raise RuntimeError("WebChat closed before the timeout notification")


def result_types(frames: list[dict[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(frame.get("type", "unknown")) for frame in frames))


async def run() -> int:
    args = parse_args()
    args.base_url = validate_base_url(args.base_url)
    username = f"jx3tools-smoke-{uuid.uuid4().hex}"
    now = int(time.time())
    token = encode_dashboard_token(
        username,
        load_jwt_secret(args.config),
        now,
    )
    headers = {"Authorization": f"Bearer {token}"}
    session_id: str | None = None
    summary: dict[str, Any] = {}

    timeout = aiohttp.ClientTimeout(total=args.selection_timeout + 60.0)
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        try:
            response = await session.get(
                f"{args.base_url}/api/chat/new_session",
                params={"platform_id": "webchat"},
            )
            response.raise_for_status()
            envelope = await response.json()
            session_id = envelope.get("data", {}).get("session_id")
            if not isinstance(session_id, str) or not session_id:
                raise RuntimeError("WebChat session creation returned no session ID")

            websocket = await session.ws_connect(
                f"{args.base_url}/api/unified_chat/ws",
                params={"token": token},
                heartbeat=20.0,
            )
            async with websocket:
                list_id = f"list-{uuid.uuid4().hex}"
                await websocket.send_json(
                    chat_message(session_id, list_id, "/jx3 新闻 1")
                )
                list_frames, list_finish_span = await receive_request(
                    websocket,
                    list_id,
                    timeout_seconds=30.0,
                )
                list_texts = [
                    str(frame.get("data", ""))
                    for frame in list_frames
                    if frame.get("type") == "plain"
                ]
                list_ok = any("【新闻】" in text and "10 秒内" in text for text in list_texts)
                if not list_ok:
                    raise RuntimeError("Article list response was not observed")
                if list_finish_span >= 5.0:
                    raise RuntimeError("Article list stream did not finish promptly")

                selection_id = f"selection-{uuid.uuid4().hex}"
                await websocket.send_json(chat_message(session_id, selection_id, "1"))
                selection_frames, _ = await receive_request(
                    websocket,
                    selection_id,
                    timeout_seconds=args.selection_timeout,
                )
                selection_texts = [
                    str(frame.get("data", ""))
                    for frame in selection_frames
                    if frame.get("type") == "plain"
                ]
                selected = any("已选择第 1 条" in text for text in selection_texts)
                rendered = any("正在本地生成图片" in text for text in selection_texts)
                image = any(frame.get("type") == "image" for frame in selection_frames)
                false_timeout = any(TIMEOUT_TEXT in text for text in selection_texts)
                if not selected or not rendered or not image or false_timeout:
                    raise RuntimeError("Article selection pipeline did not complete cleanly")

                timeout_list_id = f"timeout-list-{uuid.uuid4().hex}"
                await websocket.send_json(
                    chat_message(session_id, timeout_list_id, "/jx3 新闻 1")
                )
                _, timeout_list_finish_span = await receive_request(
                    websocket,
                    timeout_list_id,
                    timeout_seconds=30.0,
                )
                if timeout_list_finish_span >= 5.0:
                    raise RuntimeError("Timeout-case list stream did not finish promptly")
                timeout_notified = await receive_timeout_notification(
                    websocket,
                    timeout_seconds=15.0,
                )

                summary.update(
                    {
                        "list_finish_span_seconds": round(list_finish_span, 3),
                        "list_types": result_types(list_frames),
                        "selection_types": result_types(selection_frames),
                        "selection_progress": selected and rendered,
                        "selection_image": image,
                        "false_timeout": false_timeout,
                        "timeout_notification": timeout_notified,
                    }
                )
        finally:
            if session_id is not None:
                cleanup = await session.get(
                    f"{args.base_url}/api/chat/delete_session",
                    params={"session_id": session_id},
                )
                cleanup_envelope = await cleanup.json()
                summary["cleanup"] = (
                    cleanup.status == 200 and cleanup_envelope.get("status") == "ok"
                )

    print(json.dumps(summary, ensure_ascii=True, sort_keys=True))
    return 0 if summary.get("cleanup") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
