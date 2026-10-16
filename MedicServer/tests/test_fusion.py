import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ocr_service"), str(ROOT / "ocr_service" / "legacy")]

from app.fusion import fuse_results, verification_outcome


class FusionTests(unittest.TestCase):
    def test_exact_identifier_skips_yolo(self):
        result = fuse_results(
            {"status": "EXACT_ID", "drug_id": 7, "drug": {"folder_name": "Concor 5mg"}, "candidates": []},
            {"skipped": True},
        )
        self.assertEqual(result["final_prediction"], "Concor 5mg")
        self.assertEqual(result["decision_source"], "OCR_EXACT_ID")
        self.assertEqual(result["final_confidence"], 1.0)

    def test_low_ocr_allows_only_high_confidence_yolo(self):
        ocr = {"status": "UNKNOWN", "candidates": []}
        accepted = fuse_results(ocr, {"prediction": "XANAX 0.5mg", "confidence": 0.97, "candidates": []})
        rejected = fuse_results(ocr, {"prediction": "XANAX 0.5mg", "confidence": 0.94, "candidates": []})
        self.assertEqual(accepted["final_prediction"], "XANAX 0.5mg")
        self.assertEqual(rejected["final_prediction"], "unknown")

    def test_expected_name_drives_validation_outcome(self):
        self.assertEqual(verification_outcome("Concor 5mg", "Concor 5 mg"), "MATCH")
        self.assertEqual(verification_outcome("Concor 5mg", "XANAX 0.5mg"), "MISMATCH")
        self.assertEqual(verification_outcome("unknown", "Concor 5mg"), "NEEDS_REVIEW")

    def test_historical_lotus_alias_maps_to_mesyrel(self):
        result = fuse_results(
            {"status": "UNKNOWN", "candidates": []},
            {"prediction": "Lotus", "confidence": 0.99, "candidates": [{"name": "Lotus", "confidence": 0.99}]},
        )
        self.assertEqual(result["final_prediction"], "Mesyrel")


if __name__ == "__main__":
    unittest.main()

