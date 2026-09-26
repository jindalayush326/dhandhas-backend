from typing import Dict, List


def group_boxes_into_rows(boxes: List[Dict]) -> List[List[Dict]]:
    boxes = sorted(boxes, key=lambda b: b["y"])
    rows: List[List[Dict]] = []
    for b in boxes:
        placed = False
        for row in rows:
            ref_y = sum(r["y"] for r in row) / len(row)
            avg_h = sum(r["h"] for r in row) / len(row)
            if abs(b["y"] - ref_y) < max(avg_h, 10) * 0.6:
                row.append(b)
                placed = True
                break
        if not placed:
            rows.append([b])
    for row in rows:
        row.sort(key=lambda b: b["x"])
    rows.sort(key=lambda row: sum(b["y"] for b in row) / len(row))
    return rows
