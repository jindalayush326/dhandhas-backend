from typing import Any, Literal

from pydantic import BaseModel


class Change(BaseModel):
    table: str
    uuid: str
    op: Literal["insert", "update", "delete"]
    payload: dict[str, Any]


class PushRequest(BaseModel):
    device_id: str
    changes: list[Change]
