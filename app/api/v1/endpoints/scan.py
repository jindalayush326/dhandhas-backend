from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.deps import get_current_user
from app.core.exceptions import ValidationError
from app.models.user import User
from app.schemas.scan import ScanResult
from app.services.ocr.scan_service import scan_document

router = APIRouter(prefix="/scan", tags=["Scan (AI Invoice Import)"])


@router.post("", response_model=ScanResult)
async def scan_invoice(file: UploadFile = File(...), user: User = Depends(get_current_user)) -> ScanResult:
    """Extracts a draft Sales voucher (party, GSTIN, invoice no/date, line
    items) from a photographed or PDF invoice — digital-text PDFs go through
    fast regex/table parsing, scanned/photographed ones fall back to OCR.
    CPU-bound work runs in a threadpool so it never blocks the event loop
    that's serving the rest of the API."""
    data = await file.read()
    if not data:
        raise ValidationError("Empty file")

    max_bytes = settings.scan_max_upload_mb * 1024 * 1024
    if len(data) > max_bytes:
        raise ValidationError(f"File exceeds the {settings.scan_max_upload_mb}MB limit")

    filename = (file.filename or "invoice.pdf").lower()
    content_type = file.content_type or ""
    result = await run_in_threadpool(scan_document, filename, content_type, data)
    return ScanResult(**result)
