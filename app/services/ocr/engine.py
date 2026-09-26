"""Lazy-loaded OCR engine. RapidOCR's model load is expensive, so it happens
once per process (not per request) and is reused — this is the difference
between ~2s and ~200ms on the second and later scans."""

from typing import Dict, List

import numpy as np
from PIL import Image

_ocr_engine = None


def get_ocr_engine():
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def run_ocr_boxes(image: Image.Image) -> List[Dict]:
    """OCR an image and keep each detected box's text + position, so table
    rows/columns can be reconstructed downstream (plain concatenated text
    loses this and line items can't be extracted reliably from it)."""
    engine = get_ocr_engine()
    arr = np.array(image.convert("RGB"))
    result, _ = engine(arr)
    boxes: List[Dict] = []
    if not result:
        return boxes
    for box, text, _conf in result:
        text = str(text).strip()
        if not text:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        boxes.append({"text": text, "x": min(xs), "y": (min(ys) + max(ys)) / 2.0, "h": max(ys) - min(ys) or 10.0})
    return boxes
