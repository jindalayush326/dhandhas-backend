from typing import Any, Literal

from pydantic import BaseModel, Field


class Change(BaseModel):
    table: str
    uuid: str
    op: Literal["insert", "update", "delete"]
    payload: dict[str, Any]


class PushRequest(BaseModel):
    device_id: str
    # Client-generated, unique per logical push attempt (e.g. a UUID the app
    # creates once and reuses on retry — NOT regenerated per HTTP attempt).
    # Lets the server recognize "this exact push already happened" after a
    # timeout/network-drop retry, so nothing gets applied twice.
    operation_id: str = Field(min_length=1, max_length=64)
    changes: list[Change]
