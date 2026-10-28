from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional

# ============================================================
# 此檔案只載入 PyTorch / Pair-YOLO。
# 絕對不 import ocr / paddle / paddleocr。
# ============================================================
from drug_matching.strength_parser import name_line_has_matching_strength

if TYPE_CHECKING:
    from function.pair_function import PairYoloPredictor

try:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
except Exception:
    Workbook = None
    Font = None
    get_column_letter = None

CURRENT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_DIR = CURRENT_DIR / "ocr_reports" / "hybrid_ocr_yolo"
DEFAULT_OCR_RESULTS = DEFAULT_OUTPUT_DIR / "ocr_stage_results.jsonl"
DEFAULT_CHECKPOINT = CURRENT_DIR / "pair_classify" / "best_pair.pt"
DEFAULT_BASE_MODEL = (
    CURRENT_DIR / "train-17" / "weights" / "best.pt"
)

EXACT_STATUSES = {"EXACT_ID"}

# The pair classifier was trained with one historical folder label that does
# not use the canonical ``drug_products.folder_name`` stored by the OCR
# database. Keep the trained class ID unchanged and translate the public YOLO
# class name to the database folder_name before fusion.
#
# Example: the Mesyrel blister contains the manufacturer name "Lotus", so the
# historical YOLO dataset called the class Lotus while the OCR database calls
# the drug Mesyrel.
YOLO_TO_OCR_CLASS_ALIASES = {
    "lotus": "Mesyrel",
}

# A strength may be written as ``4mg``, ``4 mg`` or simply ``100`` in a
# class name. Numbers embedded in a word (for example, vitamin B12) are not
# treated as a strength.
DOSAGE_TOKEN_RE = re.compile(
    r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*(mg|mcg|ug|g|ml|iu|%)?(?![a-z0-9])",
    re.IGNORECASE,
)

YOLO_VALIDATED_DOSAGE_BASES = {
    "jardiance",
    "otsukaabilify",
    "rexulti",
}
YOLO_DOSAGE_THRESHOLD = 0.85
YOLO_DOSAGE_MARGIN = 0.80


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def normalize_name(value: Any) -> str:
    text = (
        str(value or "")
        .strip()
        .lower()
        .replace("毫克", "mg")
        .replace("公絲", "mg")
    )
    text = re.sub(r"[\s_\-./\\]+", "", text)
    return re.sub(r"[()\[\]{}'\"`]+", "", text)


def drug_name_and_dosages(value: Any):
    """Return a normalized drug-name portion and its explicit strengths."""
    text = str(value or "").strip().lower().replace("μg", "ug").replace("µg", "ug")
    dosages = tuple(
        f"{match.group(1)}{(match.group(2) or '').lower()}"
        for match in DOSAGE_TOKEN_RE.finditer(text)
    )
    name_without_dosages = DOSAGE_TOKEN_RE.sub(" ", text)
    return normalize_name(name_without_dosages), dosages


def same_drug_different_dosage(left: Any, right: Any) -> bool:
    """Whether two labels have the same drug name but different strengths."""
    left_name, left_dosages = drug_name_and_dosages(left)
    right_name, right_dosages = drug_name_and_dosages(right)
    return bool(
        left_name
        and left_name == right_name
        and left_dosages
        and right_dosages
        and left_dosages != right_dosages
    )


def has_strong_ocr_evidence(candidate: Dict[str, Any]) -> bool:
    """Require multiple independent OCR signals before overriding YOLO."""
    if not candidate or candidate.get("hard_conflict") or candidate.get("conflicts"):
        return False

    best_evidence = candidate.get("best_evidence") or {}
    name_kind = str(
        (best_evidence.get("drug_name_en") or {}).get("kind") or ""
    ).lower()
    name_evidence = best_evidence.get("drug_name_en") or {}
    database_values = candidate.get("database_values") or {}
    ingredient_score = safe_float(candidate.get("ingredient_score"))
    chinese_name_score = safe_float(candidate.get("chinese_name_score"))
    dose_matches = str(candidate.get("dose_status") or "").lower() == "match"

    # Older cached OCR-stage results may still label ``Concor 5`` versus
    # database name ``Concor`` as a mere substring and leave the dose unknown.
    # Recognize the same guarded exact-name-plus-strength pattern during fusion
    # so reports can be regenerated without rerunning the expensive OCR stage.
    name_strength_match = name_line_has_matching_strength(
        name_evidence.get("evidence"),
        name_evidence.get("database_value"),
        database_values.get("strength"),
    )
    if name_kind == "contains" and name_strength_match:
        name_kind = "exact"
        dose_matches = True

    # An exact English drug name needs at least one independent corroborating
    # signal. A substring name is accepted only when Chinese name, ingredient,
    # and dosage all corroborate it.
    exact_name_with_support = name_kind == "exact" and (
        ingredient_score >= 30.0
        or chinese_name_score >= 35.0
        or dose_matches
    )
    contained_name_with_full_support = name_kind == "contains" and (
        chinese_name_score >= 35.0
        and ingredient_score >= 30.0
        and dose_matches
    )
    return exact_name_with_support or contained_name_with_full_support


def confirmed_ocr_decision(
    base: Dict[str, Any],
    ocr_name: str,
    yolo: Dict[str, Any],
    veto_threshold: float,
    source_prefix: str,
    ocr_candidate: Optional[Dict[str, Any]] = None,
):
    """Fuse a confirmed OCR result with YOLO using a high-confidence veto."""
    raw_yolo_name = str(yolo.get("prediction") or "")
    yolo_name = canonicalize_yolo_class_name(raw_yolo_name)
    if yolo_name != raw_yolo_name:
        yolo = {
            **yolo,
            "raw_prediction": yolo.get("raw_prediction") or raw_yolo_name,
            "prediction": yolo_name,
        }
    yolo_confidence = safe_float(yolo.get("confidence"))

    # Let a validated dose-specific YOLO class resolve the dosage only when
    # OCR did not actually detect a strength. An explicit OCR dosage conflict
    # remains unknown.
    if same_drug_different_dosage(ocr_name, yolo_name):
        ocr_candidate = ocr_candidate or {}
        dose_evidence = (
            ocr_candidate.get("best_evidence", {}).get("dose") or {}
        )
        ocr_detected_dosage = bool(dose_evidence.get("detected")) or (
            str(ocr_candidate.get("dose_status") or "").lower() == "match"
        )
        dosage_base = drug_name_and_dosages(yolo_name)[0]
        yolo_candidates = yolo.get("candidates") or []
        yolo_top2_confidence = (
            safe_float(yolo_candidates[1].get("confidence"))
            if len(yolo_candidates) >= 2
            else 0.0
        )
        yolo_margin = yolo_confidence - yolo_top2_confidence

        if (
            not ocr_detected_dosage
            and dosage_base in YOLO_VALIDATED_DOSAGE_BASES
            and yolo_confidence >= YOLO_DOSAGE_THRESHOLD
            and yolo_margin >= YOLO_DOSAGE_MARGIN
        ):
            return {
                **base,
                "yolo_result": yolo,
                "final_prediction": yolo_name,
                "final_confidence": yolo_confidence,
                "decision_source": "YOLO_DOSAGE_RESOLUTION",
                "decision_reason": (
                    "OCR did not detect a dosage; validated dose-specific YOLO "
                    f"resolved the same-drug dosage with margin {yolo_margin:.3f}."
                ),
            }

        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": "unknown",
            "final_confidence": yolo_confidence,
            "decision_source": "UNKNOWN_DOSAGE_CONFLICT",
            "decision_reason": (
                "OCR and YOLO identified the same drug with different dosages, "
                "but the guarded YOLO dosage-resolution requirements were not met."
            ),
        }

    # Product identity is the canonical database folder_name.  Different
    # products are never merged merely because their ingredient and strength
    # are equal. The one historical YOLO label alias is canonicalized above.
    agree = folder_names_match(ocr_name, yolo_name)
    if agree:
        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": ocr_name,
            "final_confidence": yolo_confidence,
            "decision_source": f"{source_prefix}_YOLO_AGREEMENT",
            "decision_reason": "Confirmed OCR result agrees with YOLO.",
        }

    strong_ocr = has_strong_ocr_evidence(ocr_candidate or {})
    if strong_ocr:
        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": ocr_name,
            "final_confidence": yolo_confidence,
            "decision_source": f"{source_prefix}_STRONG_EVIDENCE",
            "decision_reason": (
                "Confirmed OCR result accepted despite YOLO conflict because "
                "multiple independent OCR fields provide strong evidence."
            ),
        }

    name_kind = str(
        (((ocr_candidate or {}).get("best_evidence") or {}).get("drug_name_en") or {}).get("kind")
        or ""
    ).lower()
    if name_kind == "contains":
        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": "unknown",
            "final_confidence": yolo_confidence,
            "decision_source": "UNKNOWN_WEAK_SUBSTRING",
            "decision_reason": (
                "A partial-name substring without full independent OCR support "
                "cannot confirm identity when Pair-YOLO disagrees."
            ),
        }

    # The comparison is intentionally strict: exactly 0.95 cannot veto OCR.
    if yolo_confidence > veto_threshold:
        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": "unknown",
            "final_confidence": yolo_confidence,
            "decision_source": "UNKNOWN_YOLO_HIGH_CONFIDENCE_VETO",
            "decision_reason": (
                "Confirmed OCR result conflicts with YOLO above the veto "
                f"threshold {veto_threshold:.2f}."
            ),
        }

    return {
        **base,
        "yolo_result": yolo,
        "final_prediction": ocr_name,
        "final_confidence": yolo_confidence,
        "decision_source": f"{source_prefix}_YOLO_BELOW_VETO",
        "decision_reason": (
            "Confirmed OCR result accepted because conflicting YOLO confidence "
            f"did not exceed {veto_threshold:.2f}."
        ),
    }


def canonicalize_yolo_class_name(value: Any) -> str:
    raw_name = str(value or "")
    return YOLO_TO_OCR_CLASS_ALIASES.get(normalize_name(raw_name), raw_name)


def folder_names_match(ocr_folder_name: Any, yolo_class_name: Any) -> bool:
    """Compare OCR and YOLO by canonical ``drug_products.folder_name``."""
    left = normalize_name(ocr_folder_name)
    right = normalize_name(canonicalize_yolo_class_name(yolo_class_name))
    return bool(left and right and left == right)


def canonicalize_yolo_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy whose class names use the OCR database namespace."""
    output = dict(result or {})
    raw_prediction = str(output.get("prediction") or "")
    output["raw_prediction"] = raw_prediction
    output["prediction"] = canonicalize_yolo_class_name(raw_prediction)

    candidates = []
    for source in output.get("candidates") or []:
        candidate = dict(source)
        raw_name = str(candidate.get("name") or "")
        candidate["raw_name"] = raw_name
        candidate["name"] = canonicalize_yolo_class_name(raw_name)
        candidates.append(candidate)
    output["candidates"] = candidates
    return output


def predict_yolo(
    predictor: "PairYoloPredictor",
    cam0_path: Path,
    cam1_path: Path,
) -> Dict[str, Any]:
    return canonicalize_yolo_result(predictor.predict(cam0_path, cam1_path))


def candidate_name(candidate: Dict[str, Any]) -> str:
    for key in ("folder_name", "class_name", "name", "resolved_name"):
        if candidate.get(key):
            return str(candidate[key])

    db = candidate.get("database_values") or {}
    for key in ("drug_name_en", "drug_name_zh"):
        if db.get(key):
            return str(db[key])

    return str(candidate.get("drug_id", ""))


def final_drug_name_from_result(result: Dict[str, Any]) -> str:
    drug = result.get("drug") or {}
    if isinstance(drug, dict):
        for key in ("folder_name", "drug_name_en", "drug_name_zh", "name"):
            if drug.get(key):
                return str(drug[key])

    candidates = result.get("candidates") or []
    resolved_drug_id = result.get("drug_id")
    if resolved_drug_id is not None:
        # Older OCR-stage caches may not contain the resolved ``drug`` object.
        # Use only the candidate that represents the resolved drug_id; taking
        # candidates[0] can silently replace an EXACT_ID winner with an
        # unrelated score-ranked candidate.
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            if str(candidate.get("drug_id")) == str(resolved_drug_id):
                return candidate_name(candidate)

        # A resolved ID with no matching product name is incomplete data.  It
        # is safer to return unknown than to emit a confidently wrong class.
        return ""

    if candidates:
        return candidate_name(candidates[0])

    return ""


def filesystem_safe_name(name: str, max_len: int = 120) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", name).strip(" .") or "unknown"
    return name[:max_len]


def get_ocr_candidates(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    output = []
    for item in result.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        candidate["resolved_name"] = candidate_name(candidate)
        candidate["score"] = safe_float(
            candidate.get("score", candidate.get("match_score", 0.0))
        )
        output.append(candidate)

    return sorted(output, key=lambda x: x["score"], reverse=True)


def tied_ocr_candidates(
    candidates: List[Dict[str, Any]], gap: float
) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    top_score = candidates[0]["score"]
    return [c for c in candidates if top_score - c["score"] < gap][:3]


def yolo_candidate_matching(
    yolo: Dict[str, Any], allowed: Iterable[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    allowed_names = {
        normalize_name(candidate_name(c)): c for c in allowed if candidate_name(c)
    }

    for item in yolo.get("candidates", []):
        key = normalize_name(canonicalize_yolo_class_name(item.get("name")))
        if key in allowed_names:
            return {"yolo": item, "ocr": allowed_names[key]}

    return None


def hybrid_decision(
    ocr_result: Dict[str, Any],
    predictor: Optional["PairYoloPredictor"],
    cam0_path: Optional[Path],
    cam1_path: Optional[Path],
    final_threshold: float,
    ocr_supported_yolo_threshold: float,
    ocr_basic_score: float,
    ocr_tie_gap: float,
    precomputed_yolo_result: Optional[Dict[str, Any]] = None,
):
    status = str(ocr_result.get("status") or "").upper()
    candidates = get_ocr_candidates(ocr_result)
    top1 = candidates[0]["score"] if candidates else 0.0

    base = {
        "ocr_candidates": candidates,
        "yolo_result": None,
    }

    def obtain_yolo() -> Dict[str, Any]:
        if precomputed_yolo_result is not None:
            return canonicalize_yolo_result(precomputed_yolo_result)
        if predictor is None or cam0_path is None or cam1_path is None:
            raise RuntimeError(
                "Pair-YOLO evidence is required but neither a precomputed "
                "result nor path-based predictor inputs were provided"
            )
        return predict_yolo(predictor, cam0_path, cam1_path)

    # 1. 條碼 / 許可證唯一精確命中：不需要 YOLO。
    if status in EXACT_STATUSES:
        return {
            **base,
            "final_prediction": final_drug_name_from_result(ocr_result) or "unknown",
            "final_confidence": 1.0,
            "decision_source": "OCR_EXACT_ID",
            "decision_reason": "Exact verified identifier match; YOLO skipped.",
        }

    # A confirmed name is accepted unless YOLO conflicts above the veto
    # threshold. Same-drug dosage conflicts always remain unknown.
    if status == "NAME_ONLY_UNIQUE" and candidates:
        ocr_name = (
            final_drug_name_from_result(ocr_result)
            or candidate_name(candidates[0])
        )
        yolo = obtain_yolo()
        return confirmed_ocr_decision(
            base,
            ocr_name,
            yolo,
            final_threshold,
            "OCR_NAME_ONLY",
            candidates[0],
        )

    tied = tied_ocr_candidates(candidates, ocr_tie_gap)
    ambiguous = status in {"AMBIGUOUS", "CONFLICT"} or len(tied) >= 2

    # 2. OCR 沒結果 / 分數太低：恢復原系統的高信心 YOLO 主判。
    # OOD 已在此函式之前排除非藥品；這裡只在 Pair-YOLO 達到正式
    # final_threshold 時採用其藥名。低於門檻仍維持 unknown。
    if (
        not candidates
        or top1 <= 0
        or top1 < ocr_basic_score
        or status in {"UNKNOWN", "ERROR"}
    ):
        yolo = obtain_yolo()
        if yolo["confidence"] >= final_threshold:
            return {
                **base,
                "yolo_result": yolo,
                "final_prediction": yolo["prediction"],
                "final_confidence": yolo["confidence"],
                "decision_source": "YOLO_PRIMARY",
                "decision_reason": "OCR insufficient; high-confidence YOLO primary.",
            }
        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": "unknown",
            "final_confidence": yolo["confidence"],
            "decision_source": "UNKNOWN",
            "decision_reason": "OCR insufficient and Pair-YOLO is below the final threshold.",
        }

    # 3. OCR 有 2~3 個接近候選：YOLO 仲裁。
    if ambiguous:
        yolo = obtain_yolo()
        allowed = tied if len(tied) >= 2 else candidates[:3]
        match = yolo_candidate_matching(yolo, allowed)

        if match and match["yolo"]["confidence"] >= final_threshold:
            return {
                **base,
                "yolo_result": yolo,
                "final_prediction": match["yolo"]["name"],
                "final_confidence": match["yolo"]["confidence"],
                "decision_source": "YOLO_TIE_BREAK",
                "decision_reason": "OCR ambiguous; YOLO selected within OCR candidates.",
            }

        return {
            **base,
            "yolo_result": yolo,
            "final_prediction": "unknown",
            "final_confidence": yolo["confidence"],
            "decision_source": "UNKNOWN",
            "decision_reason": "OCR ambiguous and YOLO could not resolve at threshold.",
        }

    # 4. OCR 有唯一候選：OCR 主判，但由 YOLO >= 0.95 支持。
    ocr_name = final_drug_name_from_result(ocr_result) or candidate_name(candidates[0])
    ocr_name = final_drug_name_from_result(ocr_result) or candidate_name(candidates[0])
    yolo = obtain_yolo()
    return confirmed_ocr_decision(
        base,
        ocr_name,
        yolo,
        final_threshold,
        "OCR_PRIMARY",
        candidates[0],
    )


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"找不到 OCR stage 結果：{path}")

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"[警告] 跳過不完整 JSONL 第 {line_number} 行")
    return records


def write_csv(path: Path, rows: List[Dict[str, Any]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fields.append(key)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_drug_summary(rows: List[Dict[str, Any]]):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["expected_class"]].append(row)

    output = []
    for name in sorted(grouped):
        items = grouped[name]
        total = len(items)
        correct = sum(bool(x["correct"]) for x in items)
        unknown = sum(bool(x["unknown"]) for x in items)
        wrong = total - correct - unknown
        accepted = total - unknown

        output.append(
            {
                "drug_name": name,
                "total_pairs": total,
                "correct": correct,
                "wrong": wrong,
                "unknown": unknown,
                "accuracy_all": correct / total if total else 0.0,
                "unknown_rate": unknown / total if total else 0.0,
                "accepted_pairs": accepted,
                "accepted_accuracy": correct / accepted if accepted else 0.0,
            }
        )

    return output


def write_excel(path: Path, rows, drug_summary):
    if Workbook is None:
        print("[警告] 未安裝 openpyxl，略過 Excel。請執行 pip install openpyxl")
        return False

    workbook = Workbook()
    workbook.remove(workbook.active)

    def add_sheet(title, data):
        worksheet = workbook.create_sheet(
            re.sub(r"[\[\]:*?/\\]", "_", title)[:31] or "Sheet"
        )
        if not data:
            worksheet.append(["No data"])
            return

        fields = []
        seen = set()
        for row in data:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    fields.append(key)

        worksheet.append(fields)
        for cell in worksheet[1]:
            cell.font = Font(bold=True)

        for row in data:
            worksheet.append(
                [
                    dump(row.get(key))
                    if isinstance(row.get(key), (list, dict, set, tuple))
                    else row.get(key, "")
                    for key in fields
                ]
            )

        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions

        for column in worksheet.columns:
            letter = get_column_letter(column[0].column)
            width = min(
                max(max(len(str(cell.value or "")) for cell in column) + 2, 10),
                50,
            )
            worksheet.column_dimensions[letter].width = width

    add_sheet("Drug_Summary", drug_summary)
    add_sheet("All_Results", rows)
    add_sheet("Unknown", [r for r in rows if r["unknown"]])
    add_sheet("Wrong", [r for r in rows if not r["unknown"] and not r["correct"]])

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["expected_class"]].append(row)
    for name in sorted(grouped):
        add_sheet(name, grouped[name])

    workbook.save(path)
    return True


def parse_args():
    parser = argparse.ArgumentParser(description="PyTorch Pair-YOLO final stage")
    parser.add_argument("--ocr-results", type=Path, default=DEFAULT_OCR_RESULTS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--device", default="0")
    parser.add_argument("--final-threshold", type=float, default=0.95)
    parser.add_argument(
        "--ocr-supported-yolo-threshold",
        type=float,
        default=0.60,
        help=(
            "YOLO support threshold when OCR status is MATCHED or "
            "NAME_ONLY_UNIQUE and both names agree"
        ),
    )
    parser.add_argument("--ocr-basic-score", type=float, default=50.0)
    parser.add_argument("--ocr-tie-gap", type=float, default=8.0)
    return parser.parse_args()


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    # Keep PyTorch/Ultralytics out of import-time hybrid decision logic.  The
    # batch stage still imports and initializes them here in its own process.
    import torch
    from function.pair_function import PairYoloPredictor

    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    records = read_jsonl(args.ocr_results.resolve())
    if not records:
        raise RuntimeError("OCR stage 沒有任何有效結果。")

    if str(args.device).isdigit():
        device = torch.device(f"cuda:{args.device}")
    else:
        device = torch.device(str(args.device))

    if device.type == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("指定 CUDA，但 torch.cuda.is_available() == False")

    print()
    print("=" * 80)
    print("YOLO STAGE")
    print("=" * 80)
    print(f"OCR records   : {len(records)}")
    print(f"Device        : {device}")
    print(f"Final threshold: {args.final_threshold:.2f}")
    print(
        "OCR-supported YOLO threshold: "
        f"{args.ocr_supported_yolo_threshold:.2f}"
    )
    print()

    # Pair-YOLO 只在此 process 載入一次。
    predictor = PairYoloPredictor(
        args.checkpoint.resolve(),
        args.base_model.resolve(),
        device,
    )

    rows = []
    for i, record in enumerate(records, start=1):
        started = time.perf_counter()
        source_expected = str(record.get("expected_class", ""))
        expected = canonicalize_yolo_class_name(source_expected)
        group_id = str(record.get("group_id", ""))
        cam0 = Path(record["cam0"])
        cam1 = Path(record["cam1"])
        ocr_result = record.get("ocr_result") or {
            "status": "ERROR",
            "candidates": [],
            "match_score": 0.0,
        }

        try:
            decision = hybrid_decision(
                ocr_result,
                predictor,
                cam0,
                cam1,
                args.final_threshold,
                args.ocr_supported_yolo_threshold,
                args.ocr_basic_score,
                args.ocr_tie_gap,
            )

            final_prediction = decision["final_prediction"]
            unknown = normalize_name(final_prediction) == "unknown"
            correct = (
                not unknown
                and normalize_name(final_prediction) == normalize_name(expected)
            )
            yolo = decision.get("yolo_result") or {}
            ocr_candidates = decision.get("ocr_candidates") or []

            row = {
                "group_index": record.get("group_index", i),
                "source_expected_class": source_expected,
                "expected_class": expected,
                "group_id": group_id,
                "final_prediction": final_prediction,
                "final_confidence": decision["final_confidence"],
                "final_status": (
                    "UNKNOWN" if unknown else ("CORRECT" if correct else "WRONG")
                ),
                "correct": correct,
                "unknown": unknown,
                "decision_source": decision["decision_source"],
                "decision_reason": decision["decision_reason"],
                "ocr_ok": record.get("ocr_ok", True),
                "ocr_error": record.get("ocr_error", ""),
                "ocr_status": ocr_result.get("status", ""),
                "ocr_drug_id": ocr_result.get("drug_id", ""),
                "ocr_winner": final_drug_name_from_result(ocr_result),
                "ocr_match_score_points": ocr_result.get("match_score", 0.0),
                "ocr_top1_top2_margin_points": ocr_result.get(
                    "top1_top2_margin", 0.0
                ),
                "ocr_stage_time_ms": record.get("ocr_stage_time_ms", ""),
                "yolo_raw_prediction": yolo.get("raw_prediction", ""),
                "yolo_prediction": yolo.get("prediction", ""),
                "yolo_confidence": yolo.get("confidence", ""),
                "yolo_time_ms": yolo.get("time_ms", ""),
                "cam0": str(cam0),
                "cam1": str(cam1),
                "final_stage_time_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
            }

            for rank in range(1, 6):
                ocr_candidate = (
                    ocr_candidates[rank - 1]
                    if rank <= len(ocr_candidates)
                    else {}
                )
                yolo_candidates = yolo.get("candidates") or []
                yolo_candidate = (
                    yolo_candidates[rank - 1]
                    if rank <= len(yolo_candidates)
                    else {}
                )

                row[f"ocr_top{rank}_name"] = (
                    candidate_name(ocr_candidate) if ocr_candidate else ""
                )
                row[f"ocr_top{rank}_score_points"] = (
                    ocr_candidate.get("score", "") if ocr_candidate else ""
                )
                row[f"yolo_top{rank}_class"] = yolo_candidate.get("name", "")
                row[f"yolo_top{rank}_raw_class"] = yolo_candidate.get(
                    "raw_name", ""
                )
                row[f"yolo_top{rank}_confidence"] = yolo_candidate.get(
                    "confidence", ""
                )

        except Exception as exc:
            # 單一組 YOLO 出錯不停止整批。
            row = {
                "group_index": record.get("group_index", i),
                "source_expected_class": source_expected,
                "expected_class": expected,
                "group_id": group_id,
                "final_prediction": "unknown",
                "final_confidence": 0.0,
                "final_status": "UNKNOWN",
                "correct": False,
                "unknown": True,
                "decision_source": "ERROR",
                "decision_reason": f"{type(exc).__name__}: {exc}",
                "ocr_ok": record.get("ocr_ok", True),
                "ocr_error": record.get("ocr_error", ""),
                "ocr_status": ocr_result.get("status", ""),
                "cam0": str(cam0),
                "cam1": str(cam1),
                "final_stage_time_ms": round(
                    (time.perf_counter() - started) * 1000.0, 3
                ),
            }

        rows.append(row)
        display_expected = (
            f"{source_expected} -> {expected}"
            if source_expected != expected
            else expected
        )
        print(
            f"[{i}/{len(records)}] {display_expected} / {group_id} -> "
            f"{row['final_prediction']} "
            f"({safe_float(row.get('final_confidence')):.4f}) "
            f"[{row['decision_source']}]"
        )

    # ============================================================
    # Output
    # ============================================================
    write_csv(output_dir / "hybrid_pair_results.csv", rows)

    per_drug_dir = output_dir / "per_drug_csv"
    per_drug_dir.mkdir(parents=True, exist_ok=True)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["expected_class"]].append(row)
    for drug_name, items in grouped.items():
        write_csv(
            per_drug_dir / f"{filesystem_safe_name(drug_name)}.csv",
            items,
        )

    drug_summary = build_drug_summary(rows)
    write_csv(output_dir / "drug_summary.csv", drug_summary)
    write_excel(output_dir / "hybrid_results.xlsx", rows, drug_summary)

    summary = {
        "total_pairs": len(rows),
        "correct": sum(bool(r["correct"]) for r in rows),
        "wrong": sum(not r["unknown"] and not r["correct"] for r in rows),
        "unknown": sum(bool(r["unknown"]) for r in rows),
        "final_threshold": args.final_threshold,
        "ocr_supported_yolo_threshold": args.ocr_supported_yolo_threshold,
        "yolo_to_ocr_class_aliases": YOLO_TO_OCR_CLASS_ALIASES,
    }
    (output_dir / "hybrid_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("=" * 80)
    print("YOLO STAGE 完成")
    print("=" * 80)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"Excel: {output_dir / 'hybrid_results.xlsx'}")


if __name__ == "__main__":
    main()
