import io
from typing import Dict, List

import fitz  # PyMuPDF
from PIL import Image

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.services.ocr.engine import run_ocr_boxes
from app.services.ocr.invoice_parser import parse_invoice_text
from app.services.ocr.item_extraction import extract_items_from_ocr_rows, extract_tables_from_pdf
from app.services.ocr.rows import group_boxes_into_rows


def scan_document(filename: str, content_type: str, data: bytes) -> Dict:
    """Returns a draft voucher dict for the caller to review/edit before it
    is posted via POST /vouchers — a scan never writes to the ledger
    directly, it only proposes one."""
    pre_extracted_items: List[Dict] = []
    ocr_texts: List[str] = []
    raw_text = ""

    try:
        if filename.endswith(".pdf") or content_type == "application/pdf":
            doc = fitz.open(stream=data, filetype="pdf")
            try:
                pre_extracted_items = extract_tables_from_pdf(doc)
                raw_text = "\n".join(page.get_text("text") for page in doc).strip()

                # A scanned/photographed PDF has little to no extractable
                # text and no vector table, so fall back to page-render + OCR.
                if not pre_extracted_items and len(raw_text) < 40:
                    ocr_rows: List[List[Dict]] = []
                    page_limit = min(len(doc), settings.scan_max_pdf_pages)
                    for page in doc[:page_limit]:
                        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                        img = Image.open(io.BytesIO(pix.tobytes("png")))
                        boxes = run_ocr_boxes(img)
                        ocr_texts.append("\n".join(b["text"] for b in boxes))
                        ocr_rows.extend(group_boxes_into_rows(boxes))
                    if ocr_rows:
                        pre_extracted_items = extract_items_from_ocr_rows(ocr_rows)
                    if not raw_text.strip():
                        raw_text = "\n".join(ocr_texts).strip()
            finally:
                doc.close()
        else:
            img = Image.open(io.BytesIO(data))
            boxes = run_ocr_boxes(img)
            raw_text = "\n".join(b["text"] for b in boxes)
            pre_extracted_items = extract_items_from_ocr_rows(group_boxes_into_rows(boxes))
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError(f"Could not read document: {exc}") from exc

    if not raw_text.strip():
        raise ValidationError("No readable text found in the document")

    return parse_invoice_text(raw_text, pre_extracted_items)
