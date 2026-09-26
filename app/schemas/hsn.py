
from typing import Optional

from pydantic import BaseModel


class HSNDetails(BaseModel):
    code: str
    description: str
    chapter: str = ""
    source: str = "offline"


class HSNValidateResponse(BaseModel):
    valid: bool
    message: str = "HSN/SAC code verified successfully"
    data: Optional[HSNDetails] = None


