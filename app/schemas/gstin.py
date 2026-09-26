
from typing import Optional

from pydantic import BaseModel


class GSTINDetails(BaseModel):
    gstin: str
    legal_name: str
    trade_name: str = ""
    status: str = ""
    state: str = ""
    address: str = ""
    city: str = ""
    pincode: str = ""


class GSTINValidateResponse(BaseModel):
    valid: bool
    message: str = "GSTIN verified successfully"
    data: Optional[GSTINDetails] = None


