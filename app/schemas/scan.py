from pydantic import BaseModel


class ScannedItem(BaseModel):
    name: str
    hsn: str = ""
    qty: float = 1.0
    unit: str = "PCS"
    rate: float = 0.0
    taxRatePercent: float = 18.0


class Sundry(BaseModel):
    name: str
    amount: float
    isNegative: bool = False


class ScanResult(BaseModel):
    """A draft voucher proposed from a scanned/photographed invoice. The
    caller reviews/edits this client-side, then posts it as a normal
    VoucherCreate to POST /vouchers — scanning never writes the ledger
    directly."""

    voucherType: str = "Sales"
    partyName: str = ""
    partyGstin: str = ""
    invoiceNo: str = ""
    invoiceDate: str = ""
    items: list[ScannedItem] = []
    sundries: list[Sundry] = []
    totalAmount: float = 0.0
    confidence: float = 0.0
    rawText: str = ""
