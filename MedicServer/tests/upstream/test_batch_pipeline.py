import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from OCR_AND_YOLO import (
    FULL_REPORT_FIELDS,
    _error_category,
    _expected_type,
    _is_expected_result_correct,
    _write_full_html_report,
    parse_args,
    run_full_pipeline,
    run_ood_pipeline,
)


def args_for(root: Path):
    return SimpleNamespace(
        test_dir=root / "test", output_dir=root / "reports", background_dir=root / "background",
        checkpoint=root / "best_pair.pt", base_model=root / "best.pt", ood_config=root / "config.json",
        device="0", torch_device=None, ocr_device=None, ocr_timeout=25.0,
        total_timeout=180.0, final_threshold=0.95, ocr_supported_yolo_threshold=0.60,
        ocr_basic_score=50.0, ocr_tie_gap=8.0, limit=1,
    )


class BatchPipelineTests(unittest.TestCase):
    def test_ground_truth_types_and_error_categories(self):
        self.assertEqual(_expected_type("ood"), "NON_DRUG")
        self.assertEqual(_expected_type("out"), "UNKNOWN_DRUG")
        self.assertEqual(_expected_type("Known Drug"), "KNOWN_DRUG")
        non_drug = {"status": "NON_DRUG", "final_status": "NON_DRUG", "ood_decision": "REJECT"}
        self.assertTrue(_is_expected_result_correct("ood", non_drug))
        non_drug.update({"expected_class": "ood", "expected_type": "NON_DRUG", "correct": True})
        self.assertEqual(_error_category(non_drug), "")
        false_reject = {
            "expected_class": "Known Drug", "expected_type": "KNOWN_DRUG", "correct": False,
            "final_status": "NON_DRUG", "ood_decision": "REJECT",
        }
        self.assertEqual(_error_category(false_reject), "KNOWN_DRUG_FALSE_REJECT")

    def test_full_default_and_legacy_remains(self):
        with patch("sys.argv", ["OCR_AND_YOLO.py"]):
            self.assertEqual(parse_args().pipeline, "full")
        with patch("sys.argv", ["OCR_AND_YOLO.py", "--pipeline", "legacy"]):
            self.assertEqual(parse_args().pipeline, "legacy")

    def test_report_has_ood_and_no_gemma_or_binary_fields(self):
        self.assertIn("ood_score", FULL_REPORT_FIELDS)
        self.assertIn("ood_decision", FULL_REPORT_FIELDS)
        self.assertNotIn("binary_decision", FULL_REPORT_FIELDS)
        self.assertNotIn("gemma_classification", FULL_REPORT_FIELDS)

    def test_full_orchestrator_writes_reports_without_images(self):
        class FakeRuntime:
            closed = False
            def __init__(self, **kwargs): self.kwargs = kwargs; self.ood_metadata = {"verified": True}
            def predict_pair(self, cam0, cam1):
                assert cam0.shape == (1080, 1920, 3) and cam1.dtype == np.uint8
                return {"request_id": "r1", "status": "KNOWN_DRUG", "message": "ok", "drug_name": "Known Drug", "ood_status": "PASS", "ood_decision": "PASS", "pair_forward_count": 1, "total_time_ms": 5.0}
            def close(self): FakeRuntime.closed = True

        pair = SimpleNamespace(label="Known Drug", pair_id="000001", cam0=Path("a"), cam1=Path("b"))
        frame = np.zeros((1080, 1920, 3), np.uint8)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("OCR_AND_YOLO._load_pairs", return_value=([pair], [])),
                patch("pair_image_io.read_bgr", side_effect=[frame, frame.copy()]),
                patch("opencv_occupancy.PairOccupancyDetector", side_effect=AssertionError("OpenCV gate must remain disabled")),
                patch("opencv_validation.validate_pair", side_effect=AssertionError("OpenCV validation must remain disabled")),
                patch("realtime_inference.RealtimeInferenceRuntime", FakeRuntime),
            ):
                run_full_pipeline(args_for(root))
            names = {path.name for path in (root / "reports").iterdir()}
            self.assertEqual(names, {
                "full_pipeline_results.jsonl", "full_pipeline_results.csv",
                "full_pipeline_summary.json", "full_pipeline_report.html",
                "rejected_images",
            })
            summary = json.loads((root / "reports" / "full_pipeline_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["scheduled_pairs"], 1)
            self.assertEqual(summary["processed_pairs"], 1)
            self.assertEqual(summary["opencv_blocked_count"], 0)
            self.assertEqual(summary["ood_blocked_non_drug_count"], 0)
            self.assertEqual(summary["known_drug_count"], 1)
            self.assertEqual(summary["unknown_drug_count"], 0)
            html_report = (root / "reports" / "full_pipeline_report.html").read_text(encoding="utf-8")
            self.assertIn("藥品辨識成果與拒絕影像", html_report)
            self.assertIn("Known Drug", html_report)
            self.assertIn("100.00%", html_report)
            self.assertTrue(FakeRuntime.closed)
            self.assertFalse(any(path.suffix.lower() in {".jpg", ".png"} for path in (root / "reports").iterdir()))

    def test_ood_gate_never_initializes_full_runtime(self):
        class Detector:
            def __init__(self, _): pass
            def ready(self): return True
            def check_pair(self, *_):
                return {"cam0": {"status": "OCCUPIED"}, "cam1": {"status": "OCCUPIED"}, "status": "READY_FOR_INFERENCE", "time_ms": 1.0}

        class Gate:
            threshold = 0.7981438636779785
            def __init__(self, *_args, **_kwargs): pass
            def predict_arrays(self, *_):
                return {"ood_status": "PASS", "ood_decision": "PASS", "ood_score": 0.9, "ood_threshold": self.threshold, "pair_forward_count": 1}
            def compatibility_metadata(self): return {"verified": True}

        pair = SimpleNamespace(label="Known", pair_id="000001", cam0=Path("a"), cam1=Path("b"))
        frame = np.zeros((1080, 1920, 3), np.uint8); frame[:, ::2] = 100
        fake_ood_module = types.ModuleType("ood_filter")
        fake_ood_module.CosineKNN1OODFilter = Gate
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("OCR_AND_YOLO._load_pairs", return_value=([pair], [])),
                patch("pair_image_io.read_bgr", side_effect=[frame, frame.copy()]),
                patch("opencv_occupancy.PairOccupancyDetector", side_effect=AssertionError("OpenCV gate must remain disabled")),
                patch("opencv_validation.validate_pair", side_effect=AssertionError("OpenCV validation must remain disabled")),
                patch.dict(sys.modules, {"ood_filter": fake_ood_module}),
                patch("realtime_inference.RealtimeInferenceRuntime", side_effect=AssertionError("must not initialize runtime")),
            ):
                run_ood_pipeline(args_for(root))
            report = json.loads((root / "reports" / "ood_gate_summary.json").read_text(encoding="utf-8"))
            self.assertEqual(report["counts"]["CONTINUE"], 1)

    def test_html_contains_per_drug_percentages_and_all_rejected_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "reports"
            output.mkdir()
            images = []
            for name in ("a0.jpg", "a1.jpg", "b0.jpg", "b1.jpg"):
                path = root / name
                path.write_bytes(b"test-image")
                images.append(path)
            rows = [
                {
                    "group_index": 1, "expected_type": "KNOWN_DRUG", "expected_class": "Drug A",
                    "group_id": "Drug A/000001", "cam0": str(images[0]), "cam1": str(images[1]),
                    "correct": False, "ood_decision": "REJECT", "ood_score": 0.7,
                    "ocr_status": "SKIPPED", "pair_yolo_top1": "Drug A", "pair_yolo_confidence": 1.0,
                    "final_status": "NON_DRUG",
                },
                {
                    "group_index": 2, "expected_type": "KNOWN_DRUG", "expected_class": "Drug B",
                    "group_id": "Drug B/000001", "cam0": str(images[2]), "cam1": str(images[3]),
                    "correct": False, "ood_decision": "PASS", "ood_score": 0.9,
                    "ocr_status": "UNKNOWN", "pair_yolo_top1": "Drug B", "pair_yolo_confidence": 0.4,
                    "final_status": "UNRECOGNIZED",
                },
            ]
            report = _write_full_html_report(output, rows, {"test_dir": str(root)})
            content = report.read_text(encoding="utf-8")
            self.assertIn("OOD 被 REJECT", content)
            self.assertIn("OCR+YOLO 判不出來", content)
            self.assertNotIn('class="cards"', content)
            self.assertIn("0.00%", content)
            self.assertEqual(len(list((output / "rejected_images").iterdir())), 4)


if __name__ == "__main__":
    unittest.main()
