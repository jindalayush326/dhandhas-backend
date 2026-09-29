from decimal import Decimal

from pydantic import BaseModel


class ScannedItem(BaseModel):
    name: str
    hsn: str = ""
    qty: Decimal = Decimal("1")
    unit: str = "PCS"
    rate: Decimal = Decimal("0")
    taxRatePercent: Decimal = Decimal("18")


class Sundry(BaseModel):
    name: str
    amount: Decimal
    isNegative: bool = False


class ScanResult(BaseModel):
    """A draft voucher proposed from a scanned/photographed invoice. The
    caller reviews/edits this client-side, then posts it as a normal
    VoucherCreate to POST /vouchers — scanning never writes the ledger
    directly. All money/qty fields are Decimal, never float — OCR output
    that ends up in a real ledger must never pick up binary-float rounding
    error before a human even sees it."""

    voucherType: str = "Sales"
    partyName: str = ""
    partyGstin: str = ""
    invoiceNo: str = ""
    invoiceDate: str = ""
    items: list[ScannedItem] = []
    sundries: list[Sundry] = []
    totalAmount: Decimal = Decimal("0")
    confidence: float = 0.0  # confidence score is legitimately a float, not money
    rawText: str = ""
