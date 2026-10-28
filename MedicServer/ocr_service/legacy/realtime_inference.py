from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import queue
import sys
import time
import uuid
from multiprocessing import shared_memory
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parent


def array_hash(array: np.ndarray) -> str:
    return hashlib.sha256(memoryview(np.ascontiguousarray(array))).hexdigest()


class SharedFrameBundle:
    """Own two lossless ndarray shared-memory blocks for one request."""

    def __init__(self, request_id: str, frames: dict[int, np.ndarray]):
        self.request_id = request_id
        self.blocks: list[shared_memory.SharedMemory] = []
        self.descriptors: list[dict[str, Any]] = []
        try:
            for camera_id in (0, 1):
                frame = frames[camera_id]
                if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
                    raise ValueError(f"Camera{camera_id} must be uint8 HxWx3 BGR")
                contiguous = np.ascontiguousarray(frame)
                block = shared_memory.SharedMemory(create=True, size=contiguous.nbytes)
                target = np.ndarray(contiguous.shape, dtype=contiguous.dtype, buffer=block.buf)
                target[:] = contiguous
                self.blocks.append(block)
                self.descriptors.append({
                    "request_id": request_id,
                    "camera_id": camera_id,
                    "shm_name": block.name,
                    "shape": list(contiguous.shape),
                    "dtype": contiguous.dtype.str,
                    "color_format": "BGR",
                    "nbytes": contiguous.nbytes,
                    "sha256": array_hash(contiguous),
                })
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        for block in self.blocks:
            try:
                block.close()
            except Exception:
                pass
            try:
                block.unlink()
            except (FileNotFoundError, Exception):
                pass
        self.blocks.clear()

    def __enter__(self) -> "SharedFrameBundle":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def attach_frame(descriptor: dict[str, Any]) -> tuple[np.ndarray, shared_memory.SharedMemory]:
    if descriptor.get("color_format") != "BGR":
        raise ValueError("Shared frame color format must be BGR")
    block = shared_memory.SharedMemory(name=descriptor["shm_name"], create=False)
    shape = tuple(int(x) for x in descriptor["shape"])
    dtype = np.dtype(descriptor["dtype"])
    expected = int(np.prod(shape)) * dtype.itemsize
    if expected != int(descriptor["nbytes"]) or expected > block.size:
        block.close()
        raise ValueError("Shared frame size metadata is invalid")
    frame = np.ndarray(shape, dtype=dtype, buffer=block.buf)
    frame.flags.writeable = False
    if array_hash(frame) != descriptor["sha256"]:
        block.close()
        raise RuntimeError("Shared frame hash mismatch")
    return frame, block


def _open_pair(descriptors: list[dict[str, Any]], request_id: str):
    if len(descriptors) != 2:
        raise ValueError("Exactly two shared frames are required")
    if any(item.get("request_id") != request_id for item in descriptors):
        raise RuntimeError("Shared frames belong to a different request")
    by_camera = {int(item["camera_id"]): item for item in descriptors}
    if set(by_camera) != {0, 1}:
        raise ValueError("Shared frames must contain Camera0 and Camera1")
    frames, blocks = {}, []
    try:
        for camera_id in (0, 1):
            frame, block = attach_frame(by_camera[camera_id])
            frames[camera_id] = frame
            blocks.append(block)
        return frames, blocks
    except Exception:
        for block in blocks:
            block.close()
        raise


def _compact_ocr_result(result: dict[str, Any]) -> dict[str, Any]:
    excluded = {"photos", "diagnostics", "observation"}

    def safe(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [safe(item) for item in value]
        if isinstance(value, np.ndarray):
            return value.tolist()
        if isinstance(value, np.generic):
            return value.item()
        return str(value)

    return safe({key: value for key, value in result.items() if key not in excluded})


def ocr_worker_main(input_queue, output_queue, settings: dict[str, Any]) -> None:
    try:
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        if str(settings["device"]).lower() == "cpu":
            os.environ["PADDLE_OCR_USE_GPU"] = "0"
        else:
            os.environ["PADDLE_OCR_USE_GPU"] = "1"
            os.environ["CUDA_VISIBLE_DEVICES"] = str(settings["device"])
        import ocr
        from drug_matching import DrugMatcher, DrugRepository
        from drug_matching.pipeline import infer_pair_frames

        repository = DrugRepository()
        matcher = DrugMatcher(repository)
        engines = ocr.load_ocr_engines()
        output_queue.put({"type": "READY", "worker": "OCR"})
    except Exception as exc:
        output_queue.put({"type": "STARTUP_ERROR", "worker": "OCR", "message": f"{type(exc).__name__}: {exc}"})
        return
    try:
        while True:
            task = input_queue.get()
            if task is None:
                return
            request_id = str(task.get("request_id"))
            blocks = []
            started = time.perf_counter()
            try:
                frames, blocks = _open_pair(task["frames"], request_id)
                result = infer_pair_frames(
                    [frames[0], frames[1]],
                    [Path("camera0_memory.bgr"), Path("camera1_memory.bgr")],
                    engines,
                    matcher,
                    image_load_ms=0.0,
                )
                response = {
                    "type": "RESULT", "worker": "OCR", "request_id": request_id, "status": "OK",
                    "ocr_result": _compact_ocr_result(result),
                    "ocr_input_hashes": [array_hash(frames[index]) for index in (0, 1)],
                    "ocr_input_shapes": [list(frames[index].shape) for index in (0, 1)],
                    "ocr_input_dtypes": [str(frames[index].dtype) for index in (0, 1)],
                    "ocr_input_color": "BGR",
                    "worker_time_ms": (time.perf_counter() - started) * 1000.0,
                }
            except Exception as exc:
                response = {"type": "RESULT", "worker": "OCR", "request_id": request_id, "status": "ERROR", "message": f"{type(exc).__name__}: {exc}", "worker_time_ms": (time.perf_counter() - started) * 1000.0}
            finally:
                for block in blocks:
                    block.close()
            output_queue.put(response)
    finally:
        try:
            repository.close()
        except Exception:
            pass


def pair_ood_worker_main(input_queue, output_queue, settings: dict[str, Any]) -> None:
    try:
        import torch
        from ood_filter import CosineKNN1OODFilter

        predictor = CosineKNN1OODFilter(
            config_path=settings["config"],
            device=settings["device"],
        )
        output_queue.put({
            "type": "READY", "worker": "PAIR_OOD",
            "metadata": predictor.compatibility_metadata(),
        })
    except Exception as exc:
        output_queue.put({"type": "STARTUP_ERROR", "worker": "PAIR_OOD", "message": f"{type(exc).__name__}: {exc}"})
        return
    while True:
        task = input_queue.get()
        if task is None:
            return
        request_id = str(task.get("request_id"))
        blocks = []
        try:
            frames, blocks = _open_pair(task["frames"], request_id)
            result = predictor.predict_arrays(frames[0], frames[1])
            if predictor.device.type == "cuda":
                result["gpu_peak_vram_mb"] = float(torch.cuda.max_memory_allocated(predictor.device) / (1024 ** 2))
            else:
                result["gpu_peak_vram_mb"] = None
            result.update({"type": "RESULT", "worker": "PAIR_OOD", "request_id": request_id, "status": "OK"})
        except Exception as exc:
            result = {
                "type": "RESULT", "worker": "PAIR_OOD", "request_id": request_id,
                "status": "OOD_ERROR", "ood_status": "OOD_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
            }
        finally:
            for block in blocks:
                block.close()
        output_queue.put(result)


def _is_confirmed_unknown(ocr_result: dict[str, Any]) -> bool:
    if str(ocr_result.get("status", "")).upper() not in {"UNKNOWN", "CONFLICT"}:
        return False
    sources = ocr_result.get("identifier_sources") or []
    not_found = [source for source in sources if str(source.get("status", "")).endswith("DB_NOT_FOUND") and source.get("type") in {"BARCODE", "LICENSE"}]
    matched = [source for source in sources if source.get("database_match")]
    return bool(not_found) and not matched


def _ood_reject_consensus_override(
    ocr_result: dict[str, Any],
    yolo_result: dict[str, Any],
    yolo_threshold: float,
) -> dict[str, Any]:
    """Allow an OOD reject override only for exact OCR/DB and YOLO agreement.

    OOD and Pair-YOLO share one visual forward, so a high YOLO confidence alone
    is not an independent reason to bypass OOD.  The bypass requires the OCR
    database decision to name the same canonical product as Pair-YOLO.
    """
    from YOLO_STAGE import final_drug_name_from_result, folder_names_match

    ocr_status = str(ocr_result.get("status") or "UNKNOWN").upper()
    ocr_name = final_drug_name_from_result(ocr_result)
    yolo_name = str(yolo_result.get("prediction") or "")
    try:
        yolo_confidence = float(yolo_result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        yolo_confidence = 0.0

    result = {
        "allowed": False,
        "status": "NOT_OVERRIDDEN",
        "ocr_status": ocr_status,
        "ocr_name": ocr_name,
        "yolo_name": yolo_name,
        "yolo_confidence": yolo_confidence,
        "threshold": float(yolo_threshold),
    }
    if ocr_status not in {"EXACT_ID", "MATCHED", "NAME_ONLY_UNIQUE"}:
        result["reason"] = "OCR/database did not confirm one known drug."
        return result
    if not ocr_name:
        result["reason"] = "OCR/database confirmed status has no canonical drug name."
        return result
    if yolo_confidence < float(yolo_threshold):
        result["reason"] = "Pair-YOLO confidence is below the override threshold."
        return result
    if not folder_names_match(ocr_name, yolo_name):
        result["reason"] = "OCR/database and Pair-YOLO identify different drugs."
        return result

    result.update({
        "allowed": True,
        "status": "OVERRIDDEN_BY_OCR_YOLO_AGREEMENT",
        "drug_name": ocr_name,
        "reason": "OCR/database and high-confidence Pair-YOLO identify the same drug.",
    })
    return result


class RealtimeInferenceRuntime:
    """One Pair-YOLO/OOD forward, OCR/database, then guarded consensus."""

    def __init__(
        self,
        background_dir: Path | str = ROOT / "camera_background",
        ood_config: Path | str = ROOT / "ood_filter" / "config.json",
        torch_device: str = "cuda:0",
        ocr_device: str = "0",
        ocr_timeout_seconds: float = 25.0,
        total_timeout_seconds: float = 180.0,
        final_threshold: float = 0.95,
        ocr_supported_yolo_threshold: float = 0.60,
        ocr_basic_score: float = 50.0,
        ocr_tie_gap: float = 8.0,
        startup_timeout_seconds: float = 180.0,
    ) -> None:
        # ``background_dir`` remains in the signature for launcher/API
        # compatibility. OpenCV validation and occupancy gating are disabled:
        # cosine kNN1 OOD is the only non-drug gate.
        self.background_dir = Path(background_dir)
        self.ocr_timeout_seconds = float(ocr_timeout_seconds)
        self.total_timeout_seconds = float(total_timeout_seconds)
        self.final_threshold = float(final_threshold)
        self.ocr_supported_yolo_threshold = float(ocr_supported_yolo_threshold)
        self.ocr_basic_score = float(ocr_basic_score)
        self.ocr_tie_gap = float(ocr_tie_gap)
        self.startup_timeout_seconds = float(startup_timeout_seconds)
        self.context = mp.get_context("spawn")
        self.ocr_settings = {"device": ocr_device}
        self.yolo_settings = {
            "config": str(Path(ood_config).resolve()),
            "device": torch_device,
        }
        self.ood_metadata: dict[str, Any] = {}
        self.ocr_process = self.ocr_input = self.ocr_output = None
        self.yolo_process = self.yolo_input = self.yolo_output = None
        try:
            self.start()
        except Exception:
            self.close()
            raise

    def _start_worker(self, target, settings, name):
        input_queue = self.context.Queue(maxsize=1)
        output_queue = self.context.Queue(maxsize=1)
        process = self.context.Process(target=target, args=(input_queue, output_queue, settings), name=name)
        process.start()
        try:
            ready = output_queue.get(timeout=self.startup_timeout_seconds)
        except queue.Empty:
            process.terminate()
            process.join(5)
            raise TimeoutError(f"{name} startup timed out")
        if ready.get("type") != "READY":
            process.join(5)
            raise RuntimeError(ready.get("message", f"{name} failed to initialize"))
        return process, input_queue, output_queue, ready

    def start(self) -> None:
        if self.yolo_process is None:
            self.yolo_process, self.yolo_input, self.yolo_output, ready = self._start_worker(
                pair_ood_worker_main, self.yolo_settings, "Pair-OOD-Worker"
            )
            self.ood_metadata = ready.get("metadata") or {}
        if self.ocr_process is None:
            self.ocr_process, self.ocr_input, self.ocr_output, _ = self._start_worker(ocr_worker_main, self.ocr_settings, "PaddleOCR-Worker")

    def _ensure_yolo(self) -> None:
        if self.yolo_process is None:
            self.yolo_process, self.yolo_input, self.yolo_output, ready = self._start_worker(
                pair_ood_worker_main, self.yolo_settings, "Pair-OOD-Worker"
            )
            self.ood_metadata = ready.get("metadata") or {}

    @staticmethod
    def _stop_worker(process, input_queue) -> None:
        if process is None:
            return
        if process.is_alive():
            try:
                input_queue.put_nowait(None)
            except Exception:
                pass
            process.join(5)
        if process.is_alive():
            process.terminate()
            process.join(5)

    def close(self) -> None:
        self._stop_worker(self.yolo_process, self.yolo_input)
        self._stop_worker(self.ocr_process, self.ocr_input)
        self.yolo_process = self.yolo_input = self.yolo_output = None
        self.ocr_process = self.ocr_input = self.ocr_output = None

    def _get_result(self, process, output_queue, request_id: str, timeout: float, worker: str):
        try:
            result = output_queue.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(f"{worker} timed out after {timeout:.1f}s")
        if result.get("request_id") != request_id:
            raise RuntimeError(f"{worker} returned a mismatched request_id")
        if not process.is_alive() and result.get("status") != "OK":
            raise RuntimeError(f"{worker} exited unexpectedly")
        return result

    def _restart_ocr_after_timeout(self) -> None:
        self._stop_worker(self.ocr_process, self.ocr_input)
        self.ocr_process = self.ocr_input = self.ocr_output = None

    def _remaining(self, started: float) -> float:
        return self.total_timeout_seconds - (time.perf_counter() - started)

    def predict_pair(self, cam0_original: np.ndarray, cam1_original: np.ndarray) -> dict[str, Any]:
        total_started = time.perf_counter()
        request_id = uuid.uuid4().hex
        original_hashes = [array_hash(cam0_original), array_hash(cam1_original)]
        base: dict[str, Any] = {
            "request_id": request_id,
            "cam0_capture_resolution": [cam0_original.shape[1], cam0_original.shape[0]],
            "cam1_capture_resolution": [cam1_original.shape[1], cam1_original.shape[0]],
            "opencv_processing_resolution": "DISABLED",
            "yolo_processing_resolution": "SKIPPED",
            "ocr_input_resolution": "SKIPPED",
            "cam0_occupancy": "DISABLED", "cam1_occupancy": "DISABLED",
            "opencv_final_status": "DISABLED", "opencv_time_ms": "DISABLED",
            "opencv_validation_decision": "DISABLED", "opencv_validation_details": "DISABLED",
            "ood_status": "SKIPPED", "ood_decision": "SKIPPED",
            "ood_score": "SKIPPED", "ood_threshold": "SKIPPED",
            "ood_method": "cosine_knn1", "ood_nearest_pair_id": "SKIPPED",
            "ood_nearest_label": "SKIPPED", "ood_time_ms": "SKIPPED",
            "ood_total_time_ms": "SKIPPED", "ood_error": None,
            "ood_gate_final_decision": "SKIPPED",
            "ood_override_status": "NOT_APPLICABLE",
            "ood_override_reason": "", "ood_override_drug_name": "",
            "ocr_executed": False, "ocr_status": "SKIPPED", "ocr_time_ms": "SKIPPED",
            "database_status": "SKIPPED", "database_match_time_ms": "SKIPPED",
            "pair_yolo_top1": "SKIPPED", "pair_yolo_confidence": "SKIPPED",
            "pair_yolo_executed": False, "pair_yolo_time_ms": "SKIPPED",
            "pair_preprocess_time_ms": "SKIPPED", "pair_forward_count": 0,
            "gpu_peak_vram_mb": "SKIPPED", "image_integrity_verified": False,
        }
        try:
            with SharedFrameBundle(request_id, {0: cam0_original, 1: cam1_original}) as bundle:
                task = {"request_id": request_id, "frames": bundle.descriptors}
                if self._remaining(total_started) <= 0:
                    return self._finish(base, "TIMEOUT", "OOD 開始前已超過總時間預算", total_started)
                self._ensure_yolo()
                self.yolo_input.put(task)
                yolo = self._get_result(
                    self.yolo_process, self.yolo_output, request_id,
                    self._remaining(total_started), "Pair-OOD",
                )
                if yolo.get("status") != "OK":
                    base.update({
                        "ood_status": "OOD_ERROR", "ood_decision": "OOD_ERROR",
                        "ood_error": yolo.get("message", "Pair-OOD worker error"),
                    })
                    return self._finish(base, "OOD_ERROR", base["ood_error"], total_started)
                base.update({
                    "yolo_processing_resolution": yolo.get("processing_resolution", [640, 640]),
                    "pair_yolo_top1": yolo.get("prediction", "SKIPPED"),
                    "pair_yolo_confidence": yolo.get("confidence", "SKIPPED"),
                    "pair_yolo_executed": True,
                    "pair_yolo_time_ms": yolo.get("pair_forward_time_ms", yolo.get("time_ms", "SKIPPED")),
                    "pair_preprocess_time_ms": (
                        yolo.get("ood_total_time_ms", 0.0)
                        - yolo.get("pair_forward_time_ms", 0.0)
                        - yolo.get("ood_time_ms", 0.0)
                        if all(isinstance(yolo.get(key), (int, float)) for key in ("ood_total_time_ms", "pair_forward_time_ms", "ood_time_ms"))
                        else "SKIPPED"
                    ),
                    "pair_forward_count": int(yolo.get("pair_forward_count", 1)),
                    "ood_status": yolo.get("ood_status", "OOD_ERROR"),
                    "ood_decision": yolo.get("ood_decision", "OOD_ERROR"),
                    "ood_score": yolo.get("ood_score", "SKIPPED"),
                    "ood_threshold": yolo.get("ood_threshold", "SKIPPED"),
                    "ood_method": yolo.get("ood_method", "cosine_knn1"),
                    "ood_nearest_pair_id": yolo.get("ood_nearest_pair_id", "SKIPPED"),
                    "ood_nearest_label": yolo.get("ood_nearest_label", "SKIPPED"),
                    "ood_time_ms": yolo.get("ood_time_ms", "SKIPPED"),
                    "ood_total_time_ms": yolo.get("ood_total_time_ms", "SKIPPED"),
                    "ood_error": yolo.get("ood_error"),
                    "gpu_peak_vram_mb": yolo.get("gpu_peak_vram_mb", "SKIPPED"),
                })
                if base["pair_forward_count"] != 1:
                    base.update({"ood_status": "OOD_ERROR", "ood_decision": "OOD_ERROR", "ood_error": "Pair forward count was not exactly one"})
                    return self._finish(base, "OOD_ERROR", base["ood_error"], total_started)
                raw_ood_decision = str(yolo.get("ood_decision") or "").upper()
                if raw_ood_decision not in {"PASS", "REJECT"}:
                    base.update({"ood_status": "OOD_ERROR", "ood_decision": "OOD_ERROR", "ood_error": "Invalid OOD decision"})
                    return self._finish(base, "OOD_ERROR", base["ood_error"], total_started)
                base["ood_gate_final_decision"] = (
                    "PENDING_OCR_YOLO_CONSENSUS" if raw_ood_decision == "REJECT" else "PASS"
                )

                base["ocr_executed"] = True
                if self.ocr_process is None:
                    self.start()
                self.ocr_input.put(task)
                try:
                    remaining = self._remaining(total_started)
                    if remaining <= 0:
                        raise TimeoutError("Total inference budget exhausted before OCR")
                    ocr_response = self._get_result(self.ocr_process, self.ocr_output, request_id, min(self.ocr_timeout_seconds, remaining), "OCR")
                except TimeoutError as exc:
                    self._restart_ocr_after_timeout()
                    base["ocr_status"] = "TIMEOUT"
                    return self._finish(base, "TIMEOUT", str(exc), total_started)
                if ocr_response.get("status") == "ERROR":
                    base["ocr_status"] = "ERROR"
                    return self._finish(base, "ERROR", ocr_response.get("message", "OCR worker error"), total_started)
                if ocr_response.get("ocr_input_hashes") != original_hashes:
                    return self._finish(base, "ERROR", "OCR received pixels different from camera capture", total_started)
                ocr_result = ocr_response["ocr_result"]
                base.update({
                    "ocr_input_resolution": [[shape[1], shape[0]] for shape in ocr_response["ocr_input_shapes"]],
                    "ocr_status": ocr_result.get("status", "UNKNOWN"),
                    "ocr_time_ms": ocr_response.get("worker_time_ms", "SKIPPED"),
                    "database_status": ocr_result.get("status", "UNKNOWN"),
                    "database_match_time_ms": (ocr_result.get("timing") or {}).get("database_query_time_ms", "SKIPPED"),
                })
                if ocr_result.get("exception_type") or ocr_result.get("database_error"):
                    return self._finish(base, "ERROR", ocr_result.get("error", "OCR/database error"), total_started)

                if raw_ood_decision == "REJECT":
                    override = _ood_reject_consensus_override(
                        ocr_result, yolo, self.final_threshold
                    )
                    base.update({
                        "ood_gate_final_decision": (
                            "OVERRIDDEN" if override["allowed"] else "REJECT"
                        ),
                        "ood_override_status": override["status"],
                        "ood_override_reason": override["reason"],
                        "ood_override_drug_name": override.get("drug_name", ""),
                        "decision": {"ood_reject_override": override},
                    })
                    if override["allowed"]:
                        name = str(override["drug_name"])
                        base["drug_name"] = name
                        return self._finish(
                            base, "KNOWN_DRUG",
                            f"辨識成功\n藥品名稱：{name}", total_started,
                        )
                    return self._finish(base, "NON_DRUG", "非藥品", total_started)

                if _is_confirmed_unknown(ocr_result):
                    return self._finish(base, "UNKNOWN_DRUG", "未收錄藥品", total_started)

                from YOLO_STAGE import EXACT_STATUSES, final_drug_name_from_result, hybrid_decision

                if str(ocr_result.get("status", "")).upper() in EXACT_STATUSES:
                    name = final_drug_name_from_result(ocr_result)
                    if name:
                        base["drug_name"] = name
                        return self._finish(base, "KNOWN_DRUG", f"辨識成功\n藥品名稱：{name}", total_started)

                decision = hybrid_decision(
                    ocr_result=ocr_result, predictor=None, cam0_path=None, cam1_path=None,
                    final_threshold=self.final_threshold,
                    ocr_supported_yolo_threshold=self.ocr_supported_yolo_threshold,
                    ocr_basic_score=self.ocr_basic_score,
                    ocr_tie_gap=self.ocr_tie_gap,
                    precomputed_yolo_result=yolo,
                )
                base["decision"] = decision
                prediction = str(decision.get("final_prediction") or "unknown")
                if prediction.casefold() == "unknown":
                    return self._finish(base, "UNRECOGNIZED", "無法確認", total_started)
                base["drug_name"] = prediction
                return self._finish(base, "KNOWN_DRUG", f"辨識成功\n藥品名稱：{prediction}", total_started)
        except Exception as exc:
            return self._finish(base, "ERROR", f"{type(exc).__name__}: {exc}", total_started)
        finally:
            base["image_integrity_verified"] = original_hashes == [array_hash(cam0_original), array_hash(cam1_original)]
            if not base["image_integrity_verified"]:
                base.update({"status": "ERROR", "message": "Original camera frame was modified"})

    @staticmethod
    def _finish(result: dict[str, Any], status: str, message: str, started: float) -> dict[str, Any]:
        result.update({"status": status, "message": message, "total_time_ms": (time.perf_counter() - started) * 1000.0})
        return result


__all__ = [
    "RealtimeInferenceRuntime", "SharedFrameBundle", "array_hash", "attach_frame",
    "ocr_worker_main", "pair_ood_worker_main",
]
