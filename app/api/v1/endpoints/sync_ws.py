import json
import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.deps import get_company_member, get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.services.realtime import manager

logger = logging.getLogger("sync_ws")
router = APIRouter(prefix="/sync/ws", tags=["Sync"])


@router.websocket("/{company_id}")
async def sync_ws(websocket: WebSocket, company_id: int, token: str, db: Session = Depends(get_db)):
    """Real-time change notifications for one company. Connect with
    `?token=<access_token>`. Sends {"type": "SYNC_CHANGED", "tables": [...]}
    whenever another device pushes changes for this company — the client
    should respond by calling /sync/pull for those tables.

    Auth: the token must be valid AND the user must actually be an active
    member of `company_id` (or a superuser) — otherwise the connection is
    rejected before accept(), so no data about that company ever reaches
    an unauthorized client.
    """
    payload = decode_access_token(token)
    if not payload:
        await websocket.close(code=4401)  # unauthorized
        return

    user = db.query(User).filter(User.id == int(payload["sub"]), User.deleted_at.is_(None)).first()
    if not user or not user.is_active:
        await websocket.close(code=4401)
        return

    if not user.is_superuser:
        member = get_company_member(company_id, db, user)
        if not member:
            await websocket.close(code=4403)  # forbidden
            return

    await manager.connect(company_id, websocket)
    try:
        await websocket.send_text(json.dumps({"type": "CONNECTED", "company_id": company_id}))
        while True:
            raw = await websocket.receive_text()
            if not raw.strip():
                continue
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "PING":
                await websocket.send_text(json.dumps({"type": "PONG"}))
    except WebSocketDisconnect:
        manager.disconnect(company_id, websocket)
    except Exception as exc:
        logger.error("sync_ws error company=%s user=%s: %s", company_id, user.id, exc)
        manager.disconnect(company_id, websocket)
