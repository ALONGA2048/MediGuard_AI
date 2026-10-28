from __future__ import annotations

import time
from typing import Any

import cv2
import numpy as np


def validate_frame(frame: np.ndarray) -> dict[str, Any]:
    """Validate capture integrity on a private 640x360 working copy."""
    started = time.perf_counter()
    if not isinstance(frame, np.ndarray):
        return {"valid_image": False, "decision": "INVALID_IMAGE", "reason": "IMAGE_READ_FAILED", "time_ms": (time.perf_counter() - started) * 1000.0}
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        return {"valid_image": False, "decision": "INVALID_IMAGE", "reason": f"INVALID_ARRAY_{frame.dtype}_{frame.shape}", "time_ms": (time.perf_counter() - started) * 1000.0}
    work = cv2.resize(frame, (640, 360), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    mean = float(np.mean(gray))
    std = float(np.std(gray))
    black_ratio = float(np.mean(gray <= 5))
    white_ratio = float(np.mean(gray >= 250))
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blank_score = max(black_ratio, white_ratio, max(0.0, 1.0 - std / 12.0))
    decision, reason, valid_image = "VALID", "PASS", True
    if black_ratio >= 0.995 and std <= 2.0:
        decision, reason, valid_image = "INVALID_IMAGE", "NEARLY_ALL_BLACK", False
    elif white_ratio >= 0.995 and std <= 2.0:
        decision, reason, valid_image = "INVALID_IMAGE", "NEARLY_ALL_WHITE", False
    elif std <= 1.5:
        decision, reason, valid_image = "INVALID_IMAGE", "UNIFORM_NO_INFORMATION", False
    elif blur_score < 10.0:
        decision, reason = "UNCERTAIN", "POSSIBLE_SEVERE_BLUR"
    return {
        "valid_image": valid_image,
        "decision": decision,
        "blank_score": blank_score,
        "blur_score": blur_score,
        "mean_luma": mean,
        "luma_std": std,
        "black_ratio": black_ratio,
        "white_ratio": white_ratio,
        "processing_resolution": [640, 360],
        "reason": reason,
        "time_ms": (time.perf_counter() - started) * 1000.0,
    }


def validate_pair(cam0: np.ndarray, cam1: np.ndarray) -> dict[str, Any]:
    started = time.perf_counter()
    results = [validate_frame(cam0), validate_frame(cam1)]
    if any(item["decision"] == "INVALID_IMAGE" for item in results):
        decision = "INVALID_IMAGE"
    elif any(item["decision"] == "UNCERTAIN" for item in results):
        decision = "UNCERTAIN"
    else:
        decision = "VALID"
    return {
        "decision": decision,
        "valid_image": decision != "INVALID_IMAGE",
        "cam0": results[0],
        "cam1": results[1],
        "time_ms": (time.perf_counter() - started) * 1000.0,
    }


__all__ = ["validate_frame", "validate_pair"]
