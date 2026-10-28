"""Exercise the real HTTP endpoint with model/database boundaries mocked."""
import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "ocr_service"), str(ROOT / "ocr_service/legacy")]
from app import main
from test_fusion import yolo_evidence


class VerificationAPITests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.upload_patch = patch.object(main, "UPLOAD_ROOT", Path(self.directory.name))
        self.upload_patch.start()
        self.addCleanup(self.upload_patch.stop)
        main.app.state.inference_lock = asyncio.Lock()
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        image = io.BytesIO()
        Image.new("RGB", (8, 8), "white").save(image, format="PNG")
        self.files = {side: ("image.png", image.getvalue(), "image/png")
                      for side in ["front_image", "back_image"]}
        self.calls = []
        self.storage_patch = patch.multiple(main.storage,
            resolve_expected=lambda *_: (None, None), create_job=lambda *_: None,
            complete_job=lambda *args: self.calls.append(("stored", args)),
            result_document=lambda *_: Path(self.directory.name) / "result.json",
            fail_job=lambda *_: self.calls.append(("failed", None)))
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)

    def test_pair_ood_runs_once_before_ocr_and_result_is_persisted(self):
        order = []
        async def pair(*_):
            order.append("pair_ood")
            return yolo_evidence()
        def ocr(*_):
            order.append("ocr")
            return {"status": "EXACT_ID", "drug": {"folder_name": "Concor 5mg"}}
        with patch.object(main, "run_yolo", side_effect=pair) as worker, patch.object(main, "run_ocr", side_effect=ocr):
            response = self.client.post("/api/v1/verifications", files=self.files)
        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(order, ["pair_ood", "ocr"])
        self.assertEqual(worker.call_count, 1)
        data = response.json()
        self.assertEqual(data["outcome"], "IDENTIFIED")
        self.assertEqual(data["fused_result"]["ood_gate_final_decision"], "PASS")
        self.assertEqual(self.calls[0][0], "stored")
        self.assertEqual(self.calls[0][1][4]["pair_forward_count"], 1)

    def test_ood_failure_stops_before_ocr_and_marks_job_failed(self):
        for worker_result in [{"error": "offline"}, yolo_evidence(pair_forward_count=2)]:
            with self.subTest(result=worker_result), patch.object(main, "run_yolo", new=AsyncMock(return_value=worker_result)), patch.object(main, "run_ocr") as ocr:
                response = self.client.post("/api/v1/verifications", files=self.files)
                self.assertEqual(response.status_code, 500)
                ocr.assert_not_called()
                self.assertEqual(self.calls[-1][0], "failed")

    def test_ood_reject_still_runs_ocr_for_consensus_then_returns_review(self):
        with patch.object(main, "run_yolo", new=AsyncMock(return_value=yolo_evidence(
                ood_score=0.5, ood_decision="REJECT", ood_status="REJECT"))), patch.object(
                main, "run_ocr", return_value={"status": "UNKNOWN"}) as ocr:
            response = self.client.post("/api/v1/verifications", files=self.files)
        self.assertEqual(response.status_code, 201, response.text)
        ocr.assert_called_once()
        self.assertEqual(response.json()["outcome"], "NEEDS_REVIEW")
        self.assertEqual(response.json()["fused_result"]["recognition_status"], "NON_DRUG")

    def test_ocr_database_failure_marks_failed(self):
        with patch.object(main, "run_yolo", new=AsyncMock(return_value=yolo_evidence())), patch.object(
                main, "run_ocr", return_value={"status": "UNKNOWN", "database_error": True}):
            response = self.client.post("/api/v1/verifications", files=self.files)
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.calls[-1][0], "failed")

    def test_unknown_expected_id_remains_422(self):
        with patch.object(main.storage, "resolve_expected", side_effect=ValueError("Unknown expected_drug_id")), patch.object(main, "run_yolo") as worker:
            response = self.client.post("/api/v1/verifications", files=self.files, data={"expected_drug_id": "999"})
        self.assertEqual(response.status_code, 422)
        worker.assert_not_called()


if __name__ == "__main__":
    unittest.main()
