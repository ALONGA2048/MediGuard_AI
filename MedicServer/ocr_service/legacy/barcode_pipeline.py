"""Server compatibility module for the missing drug-project barcode helper.

Only valid ZXing decodes from original pixels become identifier evidence.
Candidate geometry is optional diagnostics and never manufactures a value.
"""
from __future__ import annotations

from typing import Any

from drug_matching.identifiers import valid_barcode_value


def result_item(barcode: Any) -> dict | None:
    if not bool(getattr(barcode, "valid", False)):
        return None
    raw = str(getattr(barcode, "text", "") or "")
    value = raw.strip()
    fmt = getattr(barcode, "format", "")
    format_name = str(getattr(fmt, "name", fmt))
    if not valid_barcode_value(value, format_name):
        return None
    return {"text": value, "value": value, "raw_value": raw,
            "normalized_value": value, "format": format_name,
            "source": "BARCODE_DECODED", "decoder": "zxingcpp", "decode_success": True}


def decode_roi(image, read_barcodes) -> list[dict]:
    unique = {}
    for barcode in read_barcodes(image):
        item = result_item(barcode)
        if item is not None:
            unique.setdefault((item["format"], item["normalized_value"]), item)
    return list(unique.values())


def run(original_frame, image_path, read_barcodes, detect_candidates, debug_dir=None) -> dict:
    decoded = decode_roi(original_frame, read_barcodes)
    for item in decoded:
        item["image"] = str(image_path)
    candidates = []
    # Production inference (write_outputs=False) never pays for debug geometry.
    if debug_dir is not None:
        boxes, _, entries = detect_candidates(original_frame)
        candidates = [{"index": index, "decode_attempted": False,
                       "diagnostic_only": True} for index, _ in enumerate(boxes)]
        # Keep diagnostics JSON safe; entries can contain ndarray crops.
        for candidate, entry in zip(candidates, entries):
            if isinstance(entry, dict):
                candidate["reason"] = str(entry.get("reason", "candidate geometry"))
    return {"barcodes": decoded, "decoded_barcodes": decoded,
            "barcode_candidates": candidates, "candidate_count": len(candidates),
            "decoder": "zxingcpp", "decode_input": "original_frame"}
