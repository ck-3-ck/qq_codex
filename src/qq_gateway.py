from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import websockets

from .qq_client import QQBotClient


GROUP_AND_C2C_EVENT = 1 << 25


@dataclass(frozen=True)
class C2CMessage:
    event_id: str
    message_id: str
    openid: str
    content: str
    timestamp: str


class QQGateway:
    def __init__(self, client: QQBotClient):
        self.client = client
        self.last_seq: int | None = None

    async def listen_c2c_once(self) -> C2CMessage:
        async for message in self.iter_c2c_messages():
            return message
        raise RuntimeError("Gateway closed before receiving a C2C message")

    async def iter_c2c_messages(self):
        gateway_url = self.client.get_gateway_url()
        access_token = self.client.get_access_token()
        async with websockets.connect(gateway_url, ping_interval=None) as ws:
            hello = await self._receive_json(ws)
            if hello.get("op") != 10:
                raise RuntimeError(f"Expected Hello op=10, got: {hello}")
            interval_ms = int(hello.get("d", {}).get("heartbeat_interval", 45000))
            heartbeat_task = asyncio.create_task(self._heartbeat(ws, interval_ms / 1000))
            try:
                await ws.send(
                    json.dumps(
                        {
                            "op": 2,
                            "d": {
                                "token": f"QQBot {access_token}",
                                "intents": GROUP_AND_C2C_EVENT,
                                "shard": [0, 1],
                                "properties": {
                                    "$os": "windows",
                                    "$browser": "codex-qq-bridge",
                                    "$device": "codex-qq-bridge",
                                },
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                while True:
                    payload = await self._receive_json(ws)
                    if "s" in payload and payload["s"] is not None:
                        self.last_seq = int(payload["s"])
                    op = payload.get("op")
                    if op == 7:
                        raise RuntimeError("Gateway requested reconnect")
                    if op == 9:
                        raise RuntimeError(f"Invalid gateway session: {payload}")
                    if op != 0:
                        continue
                    event_type = payload.get("t")
                    if event_type == "READY":
                        user = payload.get("d", {}).get("user", {})
                        print(f"QQ gateway ready as {user.get('username', '<unknown>')}")
                        continue
                    if event_type == "C2C_MESSAGE_CREATE":
                        yield parse_c2c_message(payload)
            finally:
                heartbeat_task.cancel()

    async def _heartbeat(self, ws: Any, interval_seconds: float) -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            await ws.send(json.dumps({"op": 1, "d": self.last_seq}, ensure_ascii=False))

    async def _receive_json(self, ws: Any) -> dict[str, Any]:
        raw = await ws.recv()
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Gateway returned non-object payload: {payload}")
        return payload


def parse_c2c_message(payload: dict[str, Any]) -> C2CMessage:
    data = payload.get("d", {})
    author = data.get("author", {})
    openid = author.get("user_openid")
    if not openid:
        raise RuntimeError(f"C2C event missing author.user_openid: {payload}")
    return C2CMessage(
        event_id=str(payload.get("id", "")),
        message_id=str(data.get("id", "")),
        openid=str(openid),
        content=str(data.get("content", "")),
        timestamp=str(data.get("timestamp", "")),
    )
