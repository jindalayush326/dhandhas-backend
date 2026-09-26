import re
from typing import Dict, List, Optional

from app.services.ocr.item_extraction import clean_num, extract_items_from_text_lines

GSTIN_RE = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z]\d[Z][A-Z\d]\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b")


def _extract_invoice_no(full: str) -> str:
    inv_m = re.search(
        r"(?:Invoice\s*No\.?|Inv\s*No\.?|Bill\s*No\.?|Invoice\s*#)[\s.:#|]*\n?[\s|]*([A-Za-z0-9/\-]+)",
        full,
        re.IGNORECASE,
    )
    if inv_m and inv_m.group(1).lower() not in ("date", "gstin", "invoice"):
        return inv_m.group(1).strip()
    m2 = re.search(r"\b([A-Z]{2,5}[/-]\d{2}[/-]\d+|\b[A-Z]{2,5}/\d{2}-\d{2}/\d+)\b", full)
    return m2.group(1).strip() if m2 else ""


def _extract_party_name(lines: List[str]) -> str:
    party_name = ""
    for idx, l in enumerate(lines):
        if any(w in l.lower() for w in ["bill to", "buyer", "customer"]):
            if ":" in l:
                cand = l.split(":", 1)[1].strip()
                if cand:
                    party_name = cand
                    break
            if idx + 1 < len(lines):
                cand = lines[idx + 1].strip().lstrip("|").strip()
                if not any(cand.lower().startswith(x) for x in ["site:", "address:", "gstin:"]):
                    party_name = cand
                    break
    if not party_name and lines:
        for l in lines[:6]:
            cand = l.lstrip("|").strip()
            if not any(w in cand.lower() for w in ["tax", "invoice", "gstin", "date"]):
                party_name = cand
                break
    party_name = re.sub(r"^(?:bill\s*to|buyer|customer)[\s.:]*", "", party_name, flags=re.I).strip()
    return re.split(r"\s{2,}", party_name)[0].strip()


def _extract_sundries(lines: List[str]) -> List[Dict]:
    sundries: List[Dict] = []
    for l in lines:
        low = l.lower()
        nums = re.findall(r"[\d,]+(?:\.\d{2})?", l)
        if "discount" in low and nums:
            amt = clean_num(nums[-1])
            if amt > 0:
                sundries.append({"name": "Discount", "amount": amt, "isNegative": True})
        elif ("freight" in low or "transport" in low) and nums:
            amt = clean_num(nums[-1])
            if amt > 0:
                sundries.append({"name": "Freight & Forwarding Charges", "amount": amt, "isNegative": False})
    return sundries


def _extract_items_pipe_fallback(lines: List[str]) -> List[Dict]:
    pipe_cells: List[str] = []
    summary_bottom = ("taxable value", "gross taxable", "net taxable", "grand total", "total amount", "amount in words")
    for l in lines:
        low = l.lower()
        if any(tok in low for tok in summary_bottom):
            break
        cleaned = l.strip()
        if cleaned.startswith("|") or cleaned.isdigit():
            val = cleaned.lstrip("|").strip()
            if val and not any(hdr in val.lower() for hdr in ["item description", "particulars", "hsn/sac", "unit", "rate"]):
                pipe_cells.append(val)

    items = []
    k = 0
    while k < len(pipe_cells):
        if pipe_cells[k].isdigit() and int(pipe_cells[k]) < 100 and k + 5 < len(pipe_cells):
            name = pipe_cells[k + 1]
            hsn = pipe_cells[k + 2] if re.match(r"^\d{4,8}$", pipe_cells[k + 2]) else ""
            offset = 0 if hsn else -1
            qty = clean_num(pipe_cells[k + 3 + offset]) or 1.0
            unit = pipe_cells[k + 4 + offset].upper()
            rate = clean_num(pipe_cells[k + 5 + offset])
            tax = 18.0
            for probe in range(k + 5 + offset, min(k + 9 + offset, len(pipe_cells))):
                t_m = re.findall(r"(\d{1,2})\s*%", pipe_cells[probe])
                if t_m:
                    tax = float(t_m[0])
                    break
            if len(name) > 1 and not name.isdigit():
                items.append(
                    {
                        "name": name,
                        "hsn": hsn,
                        "qty": qty,
                        "unit": unit if len(unit) <= 5 else "PCS",
                        "rate": rate,
                        "taxRatePercent": tax,
                    }
                )
            k += 7 + offset
            continue
        k += 1
    return items


def parse_invoice_text(raw_text: str, pre_extracted_items: Optional[List[Dict]] = None) -> Dict:
    lines = [l.strip() for l in raw_text.splitlines() if l.strip()]
    full = "\n".join(lines)

    gstins = GSTIN_RE.findall(full)
    party_gstin = gstins[1].upper() if len(gstins) > 1 else (gstins[0].upper() if gstins else "")
    dates = DATE_RE.findall(full)

    items = pre_extracted_items or extract_items_from_text_lines(lines) or _extract_items_pipe_fallback(lines)

    return {
        "voucherType": "Sales",
        "partyName": _extract_party_name(lines),
        "partyGstin": party_gstin,
        "invoiceNo": _extract_invoice_no(full),
        "invoiceDate": dates[0].replace("/", "-") if dates else "",
        "items": items,
        "sundries": _extract_sundries(lines),
        "totalAmount": 0.0,
        "confidence": 0.95 if items else 0.4,
        "rawText": raw_text,
    }
