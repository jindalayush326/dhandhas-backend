import re
from typing import Dict, List

import fitz  # PyMuPDF


def clean_num(val_str: str) -> float:
    try:
        cleaned = re.sub(r"[^\d.]", "", val_str)
        return float(cleaned) if cleaned else 0.0
    except Exception:
        return 0.0


# A line-item row on a single line with space-separated columns, e.g.
# "1  LED Panel Light 18W  94054090  25  PCS  420.00  10,500.00  18%".
# Handles digital-text PDFs with no visible ruling lines, where find_tables()
# can't detect a table at all.
ITEM_LINE_RE = re.compile(
    r"^\s*\d{0,3}\.?\s+"
    r"(?P<name>[A-Za-z][A-Za-z0-9\s\-&/().]{1,60}?)\s+"
    r"(?:(?P<hsn>\d{4,8})\s+)?"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"(?P<unit>[A-Za-z]{2,6})\s+"
    r"(?P<rate>[\d,]+(?:\.\d{1,2})?)\s+"
    r"(?:(?P<taxable>[\d,]+(?:\.\d{1,2})?)\s+)?"
    r"(?P<gst>\d{1,2})\s*%\s*$"
)

_HEADER_KEYWORDS = ("item", "description", "particular", "hsn", "qty", "quantity", "rate", "price", "unit", "gst", "amount")
_STOP_KEYWORDS = ("total", "taxable", "cgst", "sgst", "subtotal", "amount in words", "grand total")


def extract_items_from_text_lines(lines: List[str]) -> List[Dict]:
    """Fast path for real (digital-text) PDFs whose line items sit on one
    space-separated line."""
    items = []
    for l in lines:
        m = ITEM_LINE_RE.match(l)
        if not m:
            continue
        name = m.group("name").strip()
        if not name or name.isdigit() or len(name) < 2:
            continue
        unit = m.group("unit").upper()
        items.append(
            {
                "name": name,
                "hsn": m.group("hsn") or "",
                "qty": clean_num(m.group("qty")) or 1.0,
                "unit": unit if len(unit) <= 5 else "PCS",
                "rate": clean_num(m.group("rate")),
                "taxRatePercent": float(m.group("gst")),
            }
        )
    return items


def extract_items_from_ocr_rows(rows: List[List[Dict]]) -> List[Dict]:
    """Fallback used for scanned PDFs / photographed invoices — no vector
    table and no column separators, only OCR word-boxes grouped into rows."""
    header_idx = -1
    col_map: Dict[str, int] = {}

    for i, row in enumerate(rows):
        texts = [c["text"].lower() for c in row]
        hits = sum(1 for t in texts for k in _HEADER_KEYWORDS if k in t)
        if hits >= 2 and len(row) >= 3:
            header_idx = i
            for idx, t in enumerate(texts):
                if "name" not in col_map and any(k in t for k in ["item", "description", "particular"]):
                    col_map["name"] = idx
                elif "hsn" not in col_map and "hsn" in t:
                    col_map["hsn"] = idx
                elif "qty" not in col_map and ("qty" in t or "quantity" in t):
                    col_map["qty"] = idx
                elif "unit" not in col_map and "unit" in t:
                    col_map["unit"] = idx
                elif "rate" not in col_map and ("rate" in t or "price" in t):
                    col_map["rate"] = idx
                elif "tax" not in col_map and ("gst" in t or "%" in t or "tax" in t):
                    col_map["tax"] = idx
            break

    if header_idx == -1 or "name" not in col_map:
        return []

    items = []
    for row in rows[header_idx + 1 :]:
        texts = [c["text"] for c in row]
        joined_low = " ".join(texts).lower()
        if any(k in joined_low for k in _STOP_KEYWORDS):
            break
        if len(texts) < 2:
            continue

        def col(key: str, default: str = "") -> str:
            idx = col_map.get(key)
            return texts[idx] if idx is not None and idx < len(texts) else default

        name = col("name")
        if not name or name.isdigit() or len(name) < 2:
            alpha_cells = [t for t in texts if not t.replace(".", "").replace(",", "").isdigit() and len(t) > 2]
            name = max(alpha_cells, key=len) if alpha_cells else ""
        if not name or len(name) < 2 or name.isdigit():
            continue

        hsn = col("hsn")
        if hsn and not re.match(r"^\d{4,8}$", hsn):
            hsn = ""
        if not hsn:
            for t in texts:
                if re.match(r"^\d{4,8}$", t):
                    hsn = t
                    break

        qty = clean_num(col("qty", "1")) or 1.0
        unit = col("unit", "PCS").upper()
        rate = clean_num(col("rate", "0"))

        tax = 18.0
        t_m = re.findall(r"(\d{1,2})\s*%", col("tax", ""))
        if t_m:
            tax = float(t_m[0])

        items.append(
            {
                "name": name.strip(),
                "hsn": hsn,
                "qty": qty if qty > 0 else 1.0,
                "unit": unit if len(unit) <= 5 else "PCS",
                "rate": rate,
                "taxRatePercent": tax,
            }
        )
    return items


def extract_tables_from_pdf(doc: "fitz.Document") -> List[Dict]:
    """Best path when available — PyMuPDF detects an actual ruled/vector
    table in a digital PDF, so column identity is exact, not inferred."""
    items = []
    header_keywords = {"item", "description", "particulars", "hsn", "qty", "rate", "price", "unit"}

    for page in doc:
        try:
            tabs = page.find_tables()
            if not tabs or not tabs.tables:
                continue
            for tab in tabs.tables:
                extracted = tab.extract()
                if not extracted or len(extracted) < 2:
                    continue

                headers = [str(c).strip().lower() if c else "" for c in extracted[0]]
                name_idx = hsn_idx = qty_idx = unit_idx = rate_idx = gst_idx = -1
                for idx, h in enumerate(headers):
                    if any(k in h for k in ["item", "description", "particulars"]):
                        name_idx = idx
                    elif "hsn" in h:
                        hsn_idx = idx
                    elif "qty" in h:
                        qty_idx = idx
                    elif "unit" in h:
                        unit_idx = idx
                    elif "rate" in h or "price" in h:
                        rate_idx = idx
                    elif "gst" in h or "%" in h:
                        gst_idx = idx

                for row in extracted[1:]:
                    if not row or len(row) < 3:
                        continue
                    row_str = " ".join([str(c).lower() for c in row if c])
                    if any(k in row_str for k in ["total", "taxable", "cgst", "sgst", "subtotal"]):
                        continue

                    name = str(row[name_idx]).strip() if name_idx != -1 else ""
                    if not name or name.isdigit() or any(k in name.lower() for k in header_keywords):
                        if len(row) > 1 and str(row[1]).strip() and not str(row[1]).strip().isdigit():
                            name = str(row[1]).strip()
                    if not name or len(name) < 2:
                        continue

                    hsn = str(row[hsn_idx]).strip() if hsn_idx != -1 and row[hsn_idx] else ""
                    if not hsn:
                        for cell in row:
                            if cell and re.match(r"^\d{4,8}$", str(cell).strip()):
                                hsn = str(cell).strip()
                                break

                    qty = clean_num(str(row[qty_idx])) if qty_idx != -1 and row[qty_idx] else 1.0
                    unit = str(row[unit_idx]).strip().upper() if unit_idx != -1 and row[unit_idx] else "PCS"
                    rate = clean_num(str(row[rate_idx])) if rate_idx != -1 and row[rate_idx] else 0.0

                    tax = 18.0
                    if gst_idx != -1 and row[gst_idx]:
                        t_m = re.findall(r"(\d{1,2})\s*%", str(row[gst_idx]))
                        if t_m:
                            tax = float(t_m[0])

                    items.append(
                        {
                            "name": name,
                            "hsn": hsn,
                            "qty": qty if qty > 0 else 1.0,
                            "unit": unit if len(unit) <= 5 else "PCS",
                            "rate": rate,
                            "taxRatePercent": tax,
                        }
                    )
        except Exception:
            continue
    return items
