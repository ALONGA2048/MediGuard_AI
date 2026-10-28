import unittest
import numpy as np

from ood_filter.scoring import OODScoringError, cosine_knn1
from realtime_inference import RealtimeInferenceRuntime, array_hash


class OODFilterTests(unittest.TestCase):
    def score(self, feature, threshold=0.7981438636779785):
        bank = np.asarray([[1.0, 0.0] + [0.0] * 254], dtype=np.float32)
        return cosine_knn1(feature, bank, np.asarray(["known/1"]), np.asarray(["known"]), threshold)

    def test_cosine_knn1_l2_normalization_and_strict_threshold(self):
        feature = np.asarray([2.0, 0.0] + [0.0] * 254, dtype=np.float32)
        result = self.score(feature)
        self.assertAlmostEqual(result["ood_score"], 1.0, places=6)
        self.assertEqual(result["ood_decision"], "PASS")
        self.assertEqual(self.score(feature, threshold=1.0)["ood_decision"], "PASS")

    def test_invalid_feature_is_an_explicit_error(self):
        with self.assertRaises(OODScoringError):
            self.score(np.zeros(256, dtype=np.float32))
        with self.assertRaises(OODScoringError):
            self.score(np.zeros(255, dtype=np.float32))

    def test_runtime_does_not_fail_open_on_worker_error(self):
        class Queue:
            def put(self, _): pass
        runtime = RealtimeInferenceRuntime.__new__(RealtimeInferenceRuntime)
        runtime.total_timeout_seconds = 180.0
        runtime.yolo_process = runtime.yolo_output = object()
        runtime.yolo_input = Queue()
        runtime._ensure_yolo = lambda: None
        runtime._get_result = lambda *_args: {"status": "OOD_ERROR", "message": "bad bank"}
        frame = np.indices((64, 64, 3)).sum(axis=0).astype(np.uint8)
        before = array_hash(frame)
        result = runtime.predict_pair(frame, frame.copy())
        self.assertEqual(result["status"], "OOD_ERROR")
        self.assertEqual(result["ood_status"], "OOD_ERROR")
        self.assertFalse(result["ocr_executed"])
        self.assertEqual(result["opencv_final_status"], "DISABLED")
        self.assertEqual(before, array_hash(frame))


if __name__ == "__main__":
    unittest.main()
