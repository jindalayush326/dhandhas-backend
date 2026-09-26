"""Real-time notification channel for multi-terminal sync. This does NOT
store data (that's Postgres, via REST push/pull) — it only tells other
connected devices of the same company "something changed, go pull", so two
branch terminals refresh within milliseconds instead of on the next poll."""

import json
import logging
from typing import Dict, Set

from fastapi import WebSocket

logger = logging.getLogger("sync_ws")


class ConnectionManager:
    def __init__(self):
        self.active: Dict[int, Set[WebSocket]] = {}

    async def connect(self, company_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(company_id, set()).add(websocket)

    def disconnect(self, company_id: int, websocket: WebSocket) -> None:
        if company_id in self.active:
            self.active[company_id].discard(websocket)
            if not self.active[company_id]:
                del self.active[company_id]

    async def broadcast(self, company_id: int, message: dict, sender: WebSocket | None = None) -> None:
        if company_id not in self.active:
            return
        payload = json.dumps(message)
        dead = []
        for conn in list(self.active[company_id]):
            if conn is sender:
                continue
            try:
                await conn.send_text(payload)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(company_id, conn)


manager = ConnectionManager()
