"""Run the vendored upstream tests that need no OCR/GPU runtime.

The complete upstream suite additionally requires PaddleOCR, OpenCV, ZXing
and Torch. These core cases run against the actual deployed source copies.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ocr_service/legacy"), str(ROOT / "yolo_service/legacy"),
                str(ROOT / "tests/upstream")]

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "test_identifier_normalization", "test_yolo_stage_equivalence",
        "test_ood_filter", "test_realtime_memory",
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
