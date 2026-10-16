"""Pure OCR/YOLO decision logic adapted from the validated batch pipeline."""

from __future__ import annotations

import re
from typing import Any

from drug_matching.strength_parser import name_line_has_matching_strength

EXACT_STATUSES = {"EXACT_ID"}
YOLO_TO_OCR_CLASS_ALIASES = {"lotus": "Mesyrel"}
DOSAGE_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(mg|mcg|ug|g|ml|iu|%)?(?![a-z0-9])",
    re.IGNORECASE,
)
YOLO_VALIDATED_DOSAGE_BASES = {"jardiance", "otsukaabilify", "rexulti"}
YOLO_DOSAGE_THRESHOLD = 0.85
YOLO_DOSAGE_MARGIN = 0.80


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("毫克", "mg").replace("公絲", "mg")
    text = re.sub(r"[\s_\-./\\]+", "", text)
    return re.sub(r"[()\[\]{}'\"`]+", "", text)


def canonicalize_yolo_class_name(value: Any) -> str:
    raw_name = str(value or "")
    return YOLO_TO_OCR_CLASS_ALIASES.get(normalize_name(raw_name), raw_name)


def canonicalize_yolo_result(result: dict[str, Any]) -> dict[str, Any]:
    output = dict(result or {})
    raw_prediction = str(output.get("prediction") or "")
    output["raw_prediction"] = raw_prediction
    output["prediction"] = canonicalize_yolo_class_name(raw_prediction)
    output["candidates"] = [
        {
            **candidate,
            "raw_name": str(candidate.get("name") or ""),
            "name": canonicalize_yolo_class_name(candidate.get("name")),
        }
        for candidate in output.get("candidates") or []
    ]
    return output


def folder_names_match(left: Any, right: Any) -> bool:
    left_key = normalize_name(left)
    right_key = normalize_name(canonicalize_yolo_class_name(right))
    return bool(left_key and right_key and left_key == right_key)


def drug_name_and_dosages(value: Any) -> tuple[str, tuple[str, ...]]:
    text = str(value or "").strip().lower().replace("μg", "ug").replace("µg", "ug")
    dosages = tuple(
        f"{match.group(1)}{(match.group(2) or '').lower()}"
        for match in DOSAGE_TOKEN_RE.finditer(text)
    )
    return normalize_name(DOSAGE_TOKEN_RE.sub(" ", text)), dosages


def same_drug_different_dosage(left: Any, right: Any) -> bool:
    left_name, left_doses = drug_name_and_dosages(left)
    right_name, right_doses = drug_name_and_dosages(right)
    return bool(
        left_name == right_name and left_name and left_doses and right_doses and left_doses != right_doses
    )


def candidate_name(candidate: dict[str, Any]) -> str:
    for key in ("folder_name", "class_name", "name", "resolved_name"):
        if candidate.get(key):
            return str(candidate[key])
    database_values = candidate.get("database_values") or {}
    for key in ("drug_name_en", "drug_name_zh"):
        if database_values.get(key):
            return str(database_values[key])
    return str(candidate.get("drug_id", ""))


def final_drug_name_from_result(result: dict[str, Any]) -> str:
    drug = result.get("drug") or {}
    if isinstance(drug, dict):
        for key in ("folder_name", "drug_name_en", "drug_name_zh", "name"):
            if drug.get(key):
                return str(drug[key])
    resolved_id = result.get("drug_id")
    candidates = result.get("candidates") or []
    if resolved_id is not None:
        for candidate in candidates:
            if isinstance(candidate, dict) and str(candidate.get("drug_id")) == str(resolved_id):
                return candidate_name(candidate)
        return ""
    return candidate_name(candidates[0]) if candidates else ""


def get_ocr_candidates(result: dict[str, Any]) -> list[dict[str, Any]]:
    output = []
    for item in result.get("candidates") or []:
        if isinstance(item, dict):
            candidate = dict(item)
            candidate["resolved_name"] = candidate_name(candidate)
            candidate["score"] = safe_float(candidate.get("score", candidate.get("match_score", 0.0)))
            output.append(candidate)
    return sorted(output, key=lambda item: item["score"], reverse=True)


def has_strong_ocr_evidence(candidate: dict[str, Any]) -> bool:
    if not candidate or candidate.get("hard_conflict") or candidate.get("conflicts"):
        return False
    best_evidence = candidate.get("best_evidence") or {}
    name_evidence = best_evidence.get("drug_name_en") or {}
    name_kind = str(name_evidence.get("kind") or "").lower()
    database_values = candidate.get("database_values") or {}
    ingredient_score = safe_float(candidate.get("ingredient_score"))
    chinese_name_score = safe_float(candidate.get("chinese_name_score"))
    dose_matches = str(candidate.get("dose_status") or "").lower() == "match"
    if name_kind == "contains" and name_line_has_matching_strength(
        name_evidence.get("evidence"), name_evidence.get("database_value"), database_values.get("strength")
    ):
        name_kind, dose_matches = "exact", True
    return (name_kind == "exact" and (ingredient_score >= 30 or chinese_name_score >= 35 or dose_matches)) or (
        name_kind == "contains" and chinese_name_score >= 35 and ingredient_score >= 30 and dose_matches
    )


def confirmed_ocr_decision(
    base: dict[str, Any], ocr_name: str, yolo: dict[str, Any], veto_threshold: float,
    source_prefix: str, ocr_candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    yolo = canonicalize_yolo_result(yolo)
    yolo_name = str(yolo.get("prediction") or "")
    confidence = safe_float(yolo.get("confidence"))
    if same_drug_different_dosage(ocr_name, yolo_name):
        candidate = ocr_candidate or {}
        dose_evidence = (candidate.get("best_evidence", {}).get("dose") or {})
        detected = bool(dose_evidence.get("detected")) or str(candidate.get("dose_status") or "").lower() == "match"
        yolo_candidates = yolo.get("candidates") or []
        top2 = safe_float(yolo_candidates[1].get("confidence")) if len(yolo_candidates) >= 2 else 0.0
        margin = confidence - top2
        if not detected and drug_name_and_dosages(yolo_name)[0] in YOLO_VALIDATED_DOSAGE_BASES and confidence >= YOLO_DOSAGE_THRESHOLD and margin >= YOLO_DOSAGE_MARGIN:
            return {**base, "yolo_result": yolo, "final_prediction": yolo_name, "final_confidence": confidence,
                    "decision_source": "YOLO_DOSAGE_RESOLUTION", "decision_reason": "YOLO safely resolved a dosage not detected by OCR."}
        return {**base, "yolo_result": yolo, "final_prediction": "unknown", "final_confidence": confidence,
                "decision_source": "UNKNOWN_DOSAGE_CONFLICT", "decision_reason": "OCR and YOLO disagree on dosage."}
    if folder_names_match(ocr_name, yolo_name):
        return {**base, "yolo_result": yolo, "final_prediction": ocr_name, "final_confidence": confidence,
                "decision_source": f"{source_prefix}_YOLO_AGREEMENT", "decision_reason": "Confirmed OCR agrees with YOLO."}
    if has_strong_ocr_evidence(ocr_candidate or {}):
        return {**base, "yolo_result": yolo, "final_prediction": ocr_name, "final_confidence": confidence,
                "decision_source": f"{source_prefix}_STRONG_EVIDENCE", "decision_reason": "Multiple independent OCR fields override the YOLO conflict."}
    if confidence > veto_threshold:
        return {**base, "yolo_result": yolo, "final_prediction": "unknown", "final_confidence": confidence,
                "decision_source": "UNKNOWN_YOLO_HIGH_CONFIDENCE_VETO", "decision_reason": "High-confidence YOLO conflicts with OCR."}
    return {**base, "yolo_result": yolo, "final_prediction": ocr_name, "final_confidence": confidence,
            "decision_source": f"{source_prefix}_YOLO_BELOW_VETO", "decision_reason": "OCR accepted; conflicting YOLO is below veto threshold."}


def fuse_results(
    ocr_result: dict[str, Any], yolo_result: dict[str, Any] | None,
    final_threshold: float = 0.95, ocr_basic_score: float = 50.0, ocr_tie_gap: float = 8.0,
) -> dict[str, Any]:
    status = str(ocr_result.get("status") or "").upper()
    candidates = get_ocr_candidates(ocr_result)
    base = {"ocr_candidates": candidates, "yolo_result": yolo_result}
    if status in EXACT_STATUSES:
        return {**base, "final_prediction": final_drug_name_from_result(ocr_result) or "unknown",
                "final_confidence": 1.0, "decision_source": "OCR_EXACT_ID",
                "decision_reason": "Exact verified barcode or license match; YOLO skipped."}
    if not yolo_result or yolo_result.get("error"):
        return {**base, "final_prediction": "unknown", "final_confidence": 0.0,
                "decision_source": "UNKNOWN_YOLO_UNAVAILABLE", "decision_reason": "YOLO result is required but unavailable."}
    yolo = canonicalize_yolo_result(yolo_result)
    top1 = candidates[0]["score"] if candidates else 0.0
    if status == "NAME_ONLY_UNIQUE" and candidates:
        name = final_drug_name_from_result(ocr_result) or candidate_name(candidates[0])
        return confirmed_ocr_decision(base, name, yolo, final_threshold, "OCR_NAME_ONLY", candidates[0])
    tied = [item for item in candidates if top1 - item["score"] < ocr_tie_gap][:3]
    ambiguous = status in {"AMBIGUOUS", "CONFLICT"} or len(tied) >= 2
    if not candidates or top1 <= 0 or top1 < ocr_basic_score or status in {"UNKNOWN", "ERROR"}:
        accepted = safe_float(yolo.get("confidence")) >= final_threshold
        return {**base, "yolo_result": yolo, "final_prediction": yolo.get("prediction") if accepted else "unknown",
                "final_confidence": safe_float(yolo.get("confidence")), "decision_source": "YOLO_PRIMARY" if accepted else "UNKNOWN",
                "decision_reason": "OCR insufficient; YOLO primary." if accepted else "Both signals are below the acceptance policy."}
    if ambiguous:
        allowed = tied if len(tied) >= 2 else candidates[:3]
        allowed_by_name = {normalize_name(candidate_name(item)): item for item in allowed}
        match = next((item for item in yolo.get("candidates") or [] if normalize_name(item.get("name")) in allowed_by_name), None)
        if match and safe_float(match.get("confidence")) >= final_threshold:
            return {**base, "yolo_result": yolo, "final_prediction": match.get("name"),
                    "final_confidence": safe_float(match.get("confidence")), "decision_source": "YOLO_TIE_BREAK",
                    "decision_reason": "YOLO resolved an ambiguous OCR candidate set."}
        return {**base, "yolo_result": yolo, "final_prediction": "unknown",
                "final_confidence": safe_float(yolo.get("confidence")), "decision_source": "UNKNOWN",
                "decision_reason": "OCR is ambiguous and YOLO could not safely resolve it."}
    name = final_drug_name_from_result(ocr_result) or candidate_name(candidates[0])
    return confirmed_ocr_decision(base, name, yolo, final_threshold, "OCR_PRIMARY", candidates[0])


def verification_outcome(final_prediction: str, expected_name: str | None) -> str:
    if normalize_name(final_prediction) in {"", "unknown"}:
        return "NEEDS_REVIEW"
    if expected_name:
        return "MATCH" if folder_names_match(final_prediction, expected_name) else "MISMATCH"
    return "IDENTIFIED"

