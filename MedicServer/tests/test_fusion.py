import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ocr_service"), str(ROOT / "ocr_service" / "legacy")]

from app.fusion import fuse_results, verification_outcome


def yolo_evidence(**overrides):
    return {"prediction": "Concor 5mg", "confidence": 0.99, "candidates": [],
            "ood_status": "PASS", "ood_decision": "PASS", "ood_method": "cosine_knn1",
            "ood_score": 0.9, "ood_threshold": 0.7981438636779785,
            "ood_error": None, "pair_forward_count": 1, **overrides}


class FusionTests(unittest.TestCase):
    def test_exact_identifier_requires_ood_pass(self):
        result = fuse_results(
            {"status": "EXACT_ID", "drug_id": 7, "drug": {"folder_name": "Concor 5mg"}, "candidates": []},
            yolo_evidence(),
        )
        self.assertEqual(result["final_prediction"], "Concor 5mg")
        self.assertEqual(result["decision_source"], "OCR_EXACT_ID")
        self.assertEqual(result["final_confidence"], 1.0)

    def test_low_ocr_allows_only_high_confidence_yolo(self):
        ocr = {"status": "UNKNOWN", "candidates": []}
        accepted = fuse_results(ocr, yolo_evidence(prediction="XANAX 0.5mg", confidence=0.97))
        rejected = fuse_results(ocr, yolo_evidence(prediction="XANAX 0.5mg", confidence=0.94))
        self.assertEqual(accepted["final_prediction"], "XANAX 0.5mg")
        self.assertEqual(rejected["final_prediction"], "unknown")

    def test_expected_name_drives_validation_outcome(self):
        self.assertEqual(verification_outcome("Concor 5mg", "Concor 5 mg"), "MATCH")
        self.assertEqual(verification_outcome("Concor 5mg", "XANAX 0.5mg"), "MISMATCH")
        self.assertEqual(verification_outcome("unknown", "Concor 5mg"), "NEEDS_REVIEW")

    def test_historical_lotus_alias_maps_to_mesyrel(self):
        result = fuse_results(
            {"status": "UNKNOWN", "candidates": []},
            yolo_evidence(prediction="Lotus", candidates=[{"name": "Lotus", "confidence": 0.99}]),
        )
        self.assertEqual(result["final_prediction"], "Mesyrel")


if __name__ == "__main__":
    unittest.main()

