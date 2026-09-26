import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.security import decode_access_token
from app.services.realtime import manager

logger = logging.getLogger("sync_ws")
router = APIRouter(prefix="/sync/ws", tags=["Sync"])


@router.websocket("/{company_id}")
async def sync_ws(websocket: WebSocket, company_id: int, token: str):
    """Real-time change notifications for one company. Connect with
    `?token=<jwt>`. Sends {"type": "SYNC_CHANGED", "tables": [...]} whenever
    another device pushes changes for this company — the client should
    respond by calling /sync/pull for those tables."""
    if not decode_access_token(token):
        await websocket.close(code=4401)
        return

    await manager.connect(company_id, websocket)
    try:
        await websocket.send_text(json.dumps({"type": "CONNECTED", "company_id": company_id}))
        while True:
            raw = await websocket.receive_text()
            if not raw.strip():
                continue
            data = json.loads(raw)
            if data.get("type") == "PING":
                await websocket.send_text(json.dumps({"type": "PONG"}))
    except WebSocketDisconnect:
        manager.disconnect(company_id, websocket)
    except Exception as exc:
        logger.error("sync_ws error company=%s: %s", company_id, exc)
        manager.disconnect(company_id, websocket)
