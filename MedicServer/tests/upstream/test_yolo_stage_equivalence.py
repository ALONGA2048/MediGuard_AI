import unittest

from YOLO_STAGE import (
    confirmed_ocr_decision,
    final_drug_name_from_result,
    folder_names_match,
    has_strong_ocr_evidence,
    hybrid_decision,
)
from drug_matching.strength_parser import name_line_has_matching_strength
from drug_matching.matcher import DrugMatcher, _chinese_name_points


class DrugClassEquivalenceTests(unittest.TestCase):
    def test_exact_id_uses_resolved_drug_instead_of_first_candidate(self):
        ocr_result = {
            "status": "EXACT_ID",
            "drug_id": 97,
            "drug": {
                "drug_id": 97,
                "folder_name": "Tetracycline_HCI_250mg",
            },
            "candidates": [
                {"drug_id": 1, "folder_name": "Acetal Tablet 500mg", "score": 0.0},
            ],
        }

        result = hybrid_decision(
            ocr_result=ocr_result,
            predictor=None,
            cam0_path=None,
            cam1_path=None,
            final_threshold=0.95,
            ocr_supported_yolo_threshold=0.60,
            ocr_basic_score=50.0,
            ocr_tie_gap=8.0,
        )

        self.assertEqual(result["final_prediction"], "Tetracycline_HCI_250mg")
        self.assertEqual(result["decision_source"], "OCR_EXACT_ID")

    def test_cached_exact_id_matches_candidate_by_drug_id(self):
        result = {
            "drug_id": 104,
            "candidates": [
                {
                    "drug_id": 39,
                    "folder_name": "Famotidine F.C. Tablets 20mg",
                    "score": 105.0,
                },
                {"drug_id": 104, "folder_name": "ULSTOP 20mg", "score": 105.0},
            ],
        }

        self.assertEqual(final_drug_name_from_result(result), "ULSTOP 20mg")

    def test_resolved_id_never_falls_back_to_unrelated_candidate(self):
        result = {
            "drug_id": 97,
            "candidates": [
                {"drug_id": 1, "folder_name": "Acetal Tablet 500mg", "score": 0.0},
            ],
        }

        self.assertEqual(final_drug_name_from_result(result), "")

    def test_historical_yolo_alias_matches_database_folder_name(self):
        self.assertTrue(folder_names_match("Mesyrel", "Lotus"))
        self.assertTrue(folder_names_match("ULSTOP 20mg", "ULSTOP 20mg"))

    def test_different_product_folders_are_not_merged(self):
        pairs = (
            ("Cardolol Tablets 10mg", "Propranolol HCI 10mg"),
            ("ULSTOP 20mg", "FAMO F.C. Tablets 20mg"),
            ("ULSTOP 20mg", "Famotidine F.C. Tablets 20mg"),
            ("Zoloft", "Vfend F.c. Tablets 200mg"),
        )
        for ocr_folder, yolo_class in pairs:
            with self.subTest(ocr_folder=ocr_folder, yolo_class=yolo_class):
                self.assertFalse(folder_names_match(ocr_folder, yolo_class))

    def test_historical_yolo_alias_is_canonicalized_before_fusion(self):
        result = confirmed_ocr_decision(
            base={"ocr_candidates": []},
            ocr_name="Mesyrel",
            yolo={"prediction": "Lotus", "confidence": 1.0},
            veto_threshold=0.95,
            source_prefix="OCR_PRIMARY",
            ocr_candidate={},
        )
        self.assertEqual(result["final_prediction"], "Mesyrel")
        self.assertEqual(result["yolo_result"]["raw_prediction"], "Lotus")
        self.assertEqual(result["yolo_result"]["prediction"], "Mesyrel")
        self.assertEqual(result["decision_source"], "OCR_PRIMARY_YOLO_AGREEMENT")

    def test_unrelated_high_confidence_conflict_stays_unknown(self):
        result = confirmed_ocr_decision(
            base={"ocr_candidates": []},
            ocr_name="Zoloft",
            yolo={"prediction": "Vfend F.c. Tablets 200mg", "confidence": 0.999},
            veto_threshold=0.95,
            source_prefix="OCR_PRIMARY",
            ocr_candidate={},
        )
        self.assertEqual(result["final_prediction"], "unknown")
        self.assertEqual(result["decision_source"], "UNKNOWN_YOLO_HIGH_CONFIDENCE_VETO")

    def test_weak_substring_cannot_confirm_when_yolo_disagrees(self):
        result = confirmed_ocr_decision(
            base={"ocr_candidates": []},
            ocr_name="Jardiance 10mg",
            yolo={"prediction": "Zoloft", "confidence": 0.40},
            veto_threshold=0.95,
            source_prefix="OCR_NAME_ONLY",
            ocr_candidate={
                "ingredient_score": 0.0,
                "chinese_name_score": 0.0,
                "dose_status": "unknown",
                "best_evidence": {
                    "drug_name_en": {
                        "kind": "contains",
                        "evidence": "Jardiance Duo unknown product",
                        "database_value": "Jardiance",
                    }
                },
                "database_values": {"strength": "10mg"},
            },
        )
        self.assertEqual(result["final_prediction"], "unknown")
        self.assertEqual(result["decision_source"], "UNKNOWN_WEAK_SUBSTRING")

    def test_hybrid_uses_precomputed_yolo_without_predictor(self):
        result = hybrid_decision(
            ocr_result={"status": "UNKNOWN", "candidates": []},
            predictor=None,
            cam0_path=None,
            cam1_path=None,
            final_threshold=0.95,
            ocr_supported_yolo_threshold=0.60,
            ocr_basic_score=50.0,
            ocr_tie_gap=8.0,
            precomputed_yolo_result={
                "prediction": "Zoloft",
                "confidence": 0.99,
                "candidates": [
                    {"rank": 1, "class_id": 117, "name": "Zoloft", "confidence": 0.99}
                ],
            },
        )
        self.assertEqual(result["final_prediction"], "Zoloft")
        self.assertEqual(result["decision_source"], "YOLO_PRIMARY")

    def test_weak_ocr_restores_high_confidence_yolo_primary(self):
        result = hybrid_decision(
            ocr_result={
                "status": "UNKNOWN",
                "candidates": [
                    {"folder_name": "Azithromycin Zirocin 250mg", "score": 20.0},
                    {"folder_name": "NAPROXEN 250mg", "score": 20.0},
                    {"folder_name": "SOMA Cap", "score": 20.0},
                    {"folder_name": "Tetracycline_HCI_250mg", "score": 20.0},
                    {"folder_name": "MgO 250mg", "score": 20.0},
                ],
            },
            predictor=None,
            cam0_path=None,
            cam1_path=None,
            final_threshold=0.95,
            ocr_supported_yolo_threshold=0.60,
            ocr_basic_score=50.0,
            ocr_tie_gap=8.0,
            precomputed_yolo_result={
                "prediction": "MgO 250mg",
                "confidence": 1.0,
                "candidates": [],
            },
        )
        self.assertEqual(result["final_prediction"], "MgO 250mg")
        self.assertEqual(result["decision_source"], "YOLO_PRIMARY")

    def test_weak_ocr_keeps_low_confidence_yolo_unknown(self):
        result = hybrid_decision(
            ocr_result={"status": "UNKNOWN", "candidates": []},
            predictor=None,
            cam0_path=None,
            cam1_path=None,
            final_threshold=0.95,
            ocr_supported_yolo_threshold=0.60,
            ocr_basic_score=50.0,
            ocr_tie_gap=8.0,
            precomputed_yolo_result={
                "prediction": "MgO 250mg",
                "confidence": 0.949,
                "candidates": [],
            },
        )
        self.assertEqual(result["final_prediction"], "unknown")
        self.assertEqual(result["decision_source"], "UNKNOWN")

    def test_exact_name_with_unitless_matching_strength_is_strong(self):
        candidate = {
            "ingredient_score": 30.0,
            "dose_status": "unknown",
            "best_evidence": {
                "drug_name_en": {
                    "kind": "contains",
                    "evidence": "Concor 5",
                    "database_value": "Concor",
                }
            },
            "database_values": {"strength": "5mg"},
        }
        self.assertTrue(has_strong_ocr_evidence(candidate))

    def test_strength_suffix_matching_is_guarded(self):
        self.assertTrue(name_line_has_matching_strength("Concor 5", "Concor", "5mg"))
        self.assertTrue(name_line_has_matching_strength("Concor 5 mg", "Concor", "5mg"))
        self.assertFalse(name_line_has_matching_strength("Concor 5", "Concor", "10mg"))
        self.assertFalse(name_line_has_matching_strength("Jardiance Duo", "Jardiance", "10mg"))

    def test_matcher_promotes_name_and_strength_evidence(self):
        observation = {
            "texts": ["Concor 5", "Bisoprolol fumarate"],
            "english": ["Concor 5", "Bisoprolol fumarate"],
            "chinese": [],
            "strengths": [],
            "_barcode_exact_ids": set(),
        }
        product = {
            "drug_id": 21,
            "folder_name": "Concor 5mg",
            "drug_name_en": "Concor",
            "normalized_name_en": "Concor",
            "drug_name_zh": None,
            "normalized_name_zh": None,
            "aliases": [],
            "ingredients": [("bisoprolol fumarate",)],
            "strength_normalized": "5mg",
            "dosage_form_en": "Tablet",
            "dosage_form_zh": None,
            "release_type": None,
            "manufacturer_en": "Merck",
            "manufacturer_zh": None,
        }
        result = DrugMatcher(None)._score(observation, product)
        self.assertEqual(result["name_score"], 40.0)
        self.assertEqual(result["dose_status"], "match")
        self.assertEqual(result["dose_score"], 20.0)
        self.assertEqual(result["score"], 90.0)
        self.assertTrue(
            result["best_evidence"]["drug_name_en"]["strength_suffix_match"]
        )

    def test_generic_chinese_release_fragment_is_not_brand_evidence(self):
        self.assertEqual(
            _chinese_name_points({
                "kind": "contains",
                "similarity": 100.0,
                "evidence": "持續",
                "database_value": "替你坦舒持續性釋放",
            }),
            0.0,
        )

    def test_complete_chinese_name_inside_noisy_line_remains_strong(self):
        self.assertEqual(
            _chinese_name_points({
                "kind": "contains",
                "similarity": 100.0,
                "evidence": "增愛舒疼錠500毫克",
                "database_value": "愛舒疼",
            }),
            35.0,
        )

    def test_tamlosin_exact_brand_outranks_tamso_generic_evidence(self):
        observation = {
            "texts": [
                "Tamsulos", "Tamlosin", "Tamsulosin hyd", "Caps",
                "持續", "暢利凈", "0.2mg",
            ],
            "english": ["Tamsulos", "Tamlosin", "Tamsulosin hyd", "Caps"],
            "chinese": ["持續", "暢利凈"],
            "strengths": ["0.2mg"],
            "_barcode_exact_ids": set(),
        }
        shared = {
            "normalized_name_en": None,
            "normalized_name_zh": None,
            "aliases": [],
            "strength_normalized": "0.2mg",
            "dosage_form_en": "Sustained-release Capsule",
            "dosage_form_zh": "持續性釋放膠囊",
            "release_type": "sustained-release",
            "manufacturer_en": None,
            "manufacturer_zh": None,
        }
        tamso = {
            **shared,
            "drug_id": 96,
            "folder_name": "Tamso_SR",
            "drug_name_en": "Tamso SR",
            "drug_name_zh": "替你坦舒持續性釋放",
            "ingredients": [("tamsulosin hcl",)],
        }
        tamlosin = {
            **shared,
            "drug_id": 95,
            "folder_name": "Tamlosin Tamsulosin hydrochloride 0.2mg",
            "drug_name_en": "Tamlosin",
            "drug_name_zh": "暢利淨",
            "ingredients": [("tamsulosin hydrochloride",)],
        }

        matcher = DrugMatcher(None)
        tamso_score = matcher._score(observation, tamso)
        tamlosin_score = matcher._score(observation, tamlosin)

        self.assertEqual(tamso_score["chinese_name_score"], 0.0)
        self.assertEqual(tamso_score["score"], 95.0)
        self.assertEqual(tamlosin_score["score"], 105.0)
        self.assertGreater(tamlosin_score["score"], tamso_score["score"])

        decision = hybrid_decision(
            ocr_result={
                "status": "MATCHED",
                "drug_id": tamlosin["drug_id"],
                "drug": tamlosin,
                "candidates": [tamlosin_score, tamso_score],
            },
            predictor=None,
            cam0_path=None,
            cam1_path=None,
            final_threshold=0.95,
            ocr_supported_yolo_threshold=0.60,
            ocr_basic_score=50.0,
            ocr_tie_gap=8.0,
            precomputed_yolo_result={
                "prediction": tamlosin["folder_name"],
                "confidence": 1.0,
                "candidates": [{
                    "name": tamlosin["folder_name"],
                    "confidence": 1.0,
                }],
            },
        )
        self.assertEqual(decision["final_prediction"], tamlosin["folder_name"])
        self.assertEqual(decision["decision_source"], "OCR_PRIMARY_YOLO_AGREEMENT")


if __name__ == "__main__":
    unittest.main()
