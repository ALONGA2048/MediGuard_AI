import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ocr_service"), str(ROOT / "ocr_service/legacy"),
                str(ROOT / "yolo_service/legacy")]

import numpy as np
from app.fusion import fuse_results, validate_ood_result
from barcode_pipeline import decode_roi, run
from drug_matching.identifiers import decoded_evidence
from ood_filter.scoring import cosine_knn1, OODScoringError
from test_fusion import yolo_evidence


class OODIntegrationTests(unittest.TestCase):
    def test_reject_cannot_be_rescued_by_yolo_alone(self):
        result = fuse_results({"status": "UNKNOWN"}, yolo_evidence(
            ood_score=0.5, ood_status="REJECT", ood_decision="REJECT"))
        self.assertEqual(result["recognition_status"], "NON_DRUG")
        self.assertEqual(result["final_prediction"], "unknown")

    def test_reject_consensus_and_boundary(self):
        for status in ["EXACT_ID", "MATCHED", "NAME_ONLY_UNIQUE"]:
            ocr = {"status": status, "drug": {"folder_name": "Concor 5mg"}}
            for prediction, confidence, accepted in [
                ("Concor 5mg", 0.95, True), ("Concor 5mg", 0.949, False),
                ("Concor 10mg", 0.999, False)]:
                with self.subTest(status=status, prediction=prediction, confidence=confidence):
                    result = fuse_results(ocr, yolo_evidence(
                        prediction=prediction, confidence=confidence, ood_score=0.5,
                        ood_status="REJECT", ood_decision="REJECT"))
                    self.assertEqual(result["ood_gate_final_decision"], "OVERRIDDEN" if accepted else "REJECT")

    def test_missing_error_nonfinite_and_multiple_forwards_fail_closed(self):
        for changes in [{"pair_forward_count": 2}, {"ood_score": float("nan")},
                        {"ood_decision": "OOD_ERROR"}, {"ood_error": "bad bank"},
                        {"ood_score": 0.3}, {"confidence": float("inf")},
                        {"ood_method": "other"}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fuse_results({"status": "EXACT_ID", "drug": {"folder_name": "X"}}, yolo_evidence(**changes))
        for value in [None, {}, {"error": "offline"}]:
            with self.assertRaises(ValueError):
                validate_ood_result(value)

    def test_missing_identifier_in_database_blocks_high_confidence_yolo(self):
        result = fuse_results({"status": "UNKNOWN", "identifier_sources": [
            {"type": "BARCODE", "status": "BARCODE_DECODED_DB_NOT_FOUND", "database_match": None}
        ]}, yolo_evidence())
        self.assertEqual(result["recognition_status"], "UNKNOWN_DRUG")
        self.assertEqual(result["final_prediction"], "unknown")

    def test_database_error_cannot_fall_back_to_yolo(self):
        with self.assertRaises(ValueError):
            fuse_results({"status": "UNKNOWN", "database_error": True}, yolo_evidence())

    def test_passing_fusion_matches_upstream_without_mutating_evidence(self):
        from YOLO_STAGE import hybrid_decision
        cases = [{"status": "UNKNOWN", "candidates": []},
                 {"status": "EXACT_ID", "drug": {"folder_name": "Concor 5mg"}},
                 {"status": "MATCHED", "candidates": [{"folder_name": "Concor 5mg", "score": 90}]},
                 {"status": "AMBIGUOUS", "candidates": [{"folder_name": "Concor 5mg", "score": 90},
                                                          {"folder_name": "Concor 10mg", "score": 89}]}]
        for ocr in cases:
            yolo = yolo_evidence(candidates=[{"name": "Concor 5mg", "confidence": 0.99}])
            before = copy.deepcopy(yolo)
            actual = fuse_results(ocr, yolo)
            expected = hybrid_decision(ocr, None, None, None, 0.95, 0.60, 50, 8, yolo)
            for key in ["final_prediction", "final_confidence", "decision_source"]:
                self.assertEqual(actual[key], expected[key])
            self.assertEqual(yolo, before)

    def test_packaged_artifact_hashes_and_bank(self):
        directory = ROOT / "yolo_service/legacy/ood_filter"
        config = json.loads((directory / "config.json").read_text())
        paths = {"feature_bank": directory / config["feature_bank"],
                 "pair_checkpoint": ROOT / "models/best_pair.pt", "base_model": ROOT / "models/yolo_best.pt"}
        for key, path in paths.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), config["sha256"][key])
        with np.load(paths["feature_bank"], allow_pickle=False) as bank:
            self.assertEqual(bank["vectors"].shape, (1046, 256))
            self.assertTrue(np.isfinite(bank["vectors"]).all())

    def test_strict_ood_boundary_and_invalid_features(self):
        feature = np.zeros(256, dtype=np.float32)
        feature[0] = 1
        args = (feature[None], np.array(["id"]), np.array(["drug"]))
        self.assertEqual(cosine_knn1(feature, *args, 1.0)["ood_decision"], "PASS")
        self.assertEqual(cosine_knn1(feature, *args, 1.001)["ood_decision"], "REJECT")
        with self.assertRaises(OODScoringError):
            cosine_knn1(np.zeros(256), *args, 0.8)


class BarcodeCompatibilityTests(unittest.TestCase):
    def test_only_valid_decodes_become_exact_identifier_evidence(self):
        valid = SimpleNamespace(text="4006381333931", format="EAN13", valid=True)
        bad_check = SimpleNamespace(text="4006381333932", format="EAN13", valid=True)
        invalid = SimpleNamespace(text="4006381333931", format="EAN13", valid=False)
        result = decode_roi(object(), lambda _: [valid, valid, bad_check, invalid])
        self.assertEqual(len(result), 1)
        self.assertEqual(len(decoded_evidence(result)), 1)
        self.assertEqual(result[0]["raw_value"], "4006381333931")

    def test_geometry_never_becomes_evidence_or_runs_on_production_path(self):
        frame = object()
        def decoder(image):
            self.assertIs(image, frame)
            return []
        def geometry(_):
            self.fail("Debug geometry must not run during production decoding")
        result = run(frame, "front.png", decoder, geometry)
        self.assertEqual(result["barcodes"], [])
        self.assertEqual(result["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
