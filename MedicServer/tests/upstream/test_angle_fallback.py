import unittest

import ocr
from drug_matching.pipeline import (
    _has_confirmed_identifier_absence,
    _observation_signature,
    should_adopt_angle_fallback,
)


class AngleFallbackTests(unittest.TestCase):
    def test_fallback_does_not_repeat_normal_zero_degree_pass(self):
        self.assertNotIn(0, ocr.ANGLE_FALLBACK_ANGLES)
        self.assertEqual(
            len(ocr.ANGLE_FALLBACK_ANGLES), len(set(ocr.ANGLE_FALLBACK_ANGLES))
        )

    def test_equivalent_ocr_evidence_has_same_signature(self):
        first = {
            "text_evidence": [{"normalized": "acetal"}, {"normalized": "500mg"}],
            "barcodes": ["12345"],
        }
        reordered = {
            "text_evidence": [{"normalized": "500MG"}, {"normalized": "Acetal"}],
            "barcodes": ["12345"],
        }
        self.assertEqual(_observation_signature(first), _observation_signature(reordered))

    def test_reliable_identifier_not_found_can_stop_angle_fallback(self):
        self.assertTrue(_has_confirmed_identifier_absence({
            "status": "UNKNOWN",
            "identifier_sources": [
                {"type": "LICENSE", "status": "LICENSE_DB_NOT_FOUND", "database_match": None}
            ],
        }))
        self.assertFalse(_has_confirmed_identifier_absence({
            "status": "UNKNOWN",
            "identifier_sources": [],
        }))

    def test_quality_penalizes_fragmented_single_characters(self):
        fragments = [
            {"text": "7", "confidence": 0.99},
            {"text": "S", "confidence": 0.99},
            {"text": "e", "confidence": 0.99},
        ]
        useful = [{"text": "Mesyrel Tablets 50mg", "confidence": 0.90}]
        self.assertGreater(
            ocr.ocr_text_quality(useful)["score"],
            ocr.ocr_text_quality(fragments)["score"],
        )

    def test_failed_match_can_be_replaced_by_better_unique_match(self):
        self.assertTrue(should_adopt_angle_fallback(
            {"status": "UNKNOWN", "match_score": 20.0},
            {"status": "MATCHED", "match_score": 60.0},
        ))

    def test_successful_baseline_is_never_replaced(self):
        self.assertFalse(should_adopt_angle_fallback(
            {"status": "MATCHED", "match_score": 60.0},
            {"status": "MATCHED", "match_score": 80.0},
        ))

    def test_failed_fallback_is_never_adopted(self):
        self.assertFalse(should_adopt_angle_fallback(
            {"status": "UNKNOWN", "match_score": 20.0},
            {"status": "AMBIGUOUS", "match_score": 70.0},
        ))


if __name__ == "__main__":
    unittest.main()
