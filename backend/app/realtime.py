"""WebSocket fan-out to every open dispatcher dashboard."""

import asyncio
import json
import logging

from fastapi import WebSocket

log = logging.getLogger("lifeline.realtime")


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self.clients.discard(ws)

    async def broadcast(self, message: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(message, default=str)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.disconnect(ws)


hub = Hub()
