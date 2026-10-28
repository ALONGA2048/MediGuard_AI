"""HTTP adapter for drug-project's production consensus rules.

The upstream modules are copied verbatim into legacy; fusion reuses the
cached classification without loading Torch/Paddle or another model forward.
"""
from __future__ import annotations

import math
from typing import Any

from YOLO_STAGE import folder_names_match, hybrid_decision, normalize_name
from realtime_inference import _is_confirmed_unknown, _ood_reject_consensus_override


def validate_ood_result(result: dict[str, Any] | None) -> None:
    """Fail closed if the worker failed or omitted calibrated OOD evidence."""
    if not result or result.get("error") or result.get("ood_error"):
        raise ValueError("Pair-YOLO/OOD worker is unavailable or reported an error")
    decision = result.get("ood_decision")
    if decision not in {"PASS", "REJECT"} or result.get("ood_status") != decision:
        raise ValueError("Missing or inconsistent OOD decision")
    if result.get("pair_forward_count") != 1:
        raise ValueError("Pair-YOLO forward count must equal one")
    try:
        score = float(result["ood_score"])
        threshold = float(result["ood_threshold"])
        confidence = float(result["confidence"])
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("Missing numeric OOD/classifier evidence") from error
    if not all(math.isfinite(value) for value in (score, threshold, confidence)):
        raise ValueError("Non-finite OOD/classifier evidence")
    if not 0.0 <= confidence <= 1.0 or not str(result.get("prediction") or "").strip():
        raise ValueError("Invalid Pair-YOLO prediction")
    if result.get("ood_method") != "cosine_knn1":
        raise ValueError("Unexpected OOD method")
    if decision != ("REJECT" if score < threshold else "PASS"):
        raise ValueError("OOD decision disagrees with calibrated score")


def fuse_results(
    ocr_result: dict[str, Any], yolo_result: dict[str, Any] | None,
    final_threshold: float = 0.95, ocr_basic_score: float = 50.0,
    ocr_tie_gap: float = 8.0, ocr_supported_yolo_threshold: float = 0.60,
) -> dict[str, Any]:
    validate_ood_result(yolo_result)
    if ocr_result.get("exception_type") or ocr_result.get("database_error") or str(ocr_result.get("status", "")).upper() == "ERROR":
        raise ValueError("OCR/database inference failed")
    evidence = {key: value for key, value in yolo_result.items() if key.startswith("ood_")}
    evidence.update({"pair_forward_count": 1, "ood_gate_final_decision": "PASS",
                     "ood_override_status": "NOT_APPLICABLE"})
    if yolo_result["ood_decision"] == "REJECT":
        override = _ood_reject_consensus_override(ocr_result, yolo_result, final_threshold)
        return {
            **evidence, "ood_gate_final_decision": "OVERRIDDEN" if override["allowed"] else "REJECT",
            "ood_override_status": override["status"], "ood_override_reason": override["reason"],
            "ood_override_drug_name": override.get("drug_name", ""), "ood_reject_override": override,
            "yolo_result": yolo_result, "ocr_candidates": ocr_result.get("candidates") or [],
            "recognition_status": "KNOWN_DRUG" if override["allowed"] else "NON_DRUG",
            "final_prediction": override["drug_name"] if override["allowed"] else "unknown",
            "final_confidence": float(yolo_result["confidence"]) if override["allowed"] else 0.0,
            "decision_source": override["status"] if override["allowed"] else "OOD_REJECT",
            "decision_reason": override["reason"],
        }
    if _is_confirmed_unknown(ocr_result):
        return {**evidence, "recognition_status": "UNKNOWN_DRUG", "final_prediction": "unknown",
                "final_confidence": 0.0, "decision_source": "UNKNOWN_DRUG",
                "decision_reason": "Decoded barcode/license is absent from the drug database.",
                "yolo_result": yolo_result, "ocr_candidates": ocr_result.get("candidates") or []}
    decision = hybrid_decision(
        ocr_result=ocr_result, predictor=None, cam0_path=None, cam1_path=None,
        final_threshold=final_threshold, ocr_supported_yolo_threshold=ocr_supported_yolo_threshold,
        ocr_basic_score=ocr_basic_score, ocr_tie_gap=ocr_tie_gap,
        precomputed_yolo_result=yolo_result,
    )
    return {**decision, **evidence,
            "recognition_status": "UNRECOGNIZED" if normalize_name(decision.get("final_prediction")) == "unknown" else "KNOWN_DRUG"}


def verification_outcome(final_prediction: str, expected_name: str | None) -> str:
    if normalize_name(final_prediction) in {"", "unknown"}:
        return "NEEDS_REVIEW"
    if expected_name:
        return "MATCH" if folder_names_match(final_prediction, expected_name) else "MISMATCH"
    return "IDENTIFIED"
