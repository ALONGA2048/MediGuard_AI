from __future__ import annotations

import argparse
import csv
import html
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
DEFAULT_TEST_DIR = CURRENT_DIR / "ServerTest"
DEFAULT_OUTPUT_DIR = CURRENT_DIR / "ocr_reports" / "hybrid_ocr_yolo"
DEFAULT_CHECKPOINT = CURRENT_DIR / "pair_classify" / "best_pair.pt"
DEFAULT_BASE_MODEL = CURRENT_DIR / "train-17" / "weights" / "best.pt"
DEFAULT_BACKGROUND_DIR = CURRENT_DIR / "camera_background"
DEFAULT_OOD_CONFIG = CURRENT_DIR / "ood_filter" / "config.json"

FULL_REPORT_FIELDS = [
    "group_index", "expected_type", "expected_class", "group_id", "cam0", "cam1", "request_id",
    "cam0_capture_resolution", "cam1_capture_resolution", "opencv_processing_resolution",
    "yolo_processing_resolution", "ocr_input_resolution", "cam0_occupancy", "cam1_occupancy",
    "opencv_final_status", "opencv_time_ms", "opencv_validation_decision",
    "opencv_validation_details", "ood_status", "ood_decision", "ood_score",
    "ood_threshold", "ood_method", "ood_nearest_pair_id", "ood_nearest_label",
    "ood_time_ms", "ood_total_time_ms", "ood_error",
    "ood_gate_final_decision", "ood_override_status", "ood_override_reason",
    "ood_override_drug_name",
    "ocr_executed", "ocr_status", "ocr_time_ms", "database_status",
    "database_match_time_ms", "pair_yolo_top1", "pair_yolo_confidence",
    "pair_yolo_executed", "pair_yolo_time_ms", "pair_preprocess_time_ms",
    "pair_forward_count", "gpu_peak_vram_mb",
    "image_integrity_verified", "final_status", "final_message", "drug_name",
    "correct", "ocr_yolo_pipeline_time_ms", "total_time_ms",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch pipeline: Pair-YOLO Hidden-256 cosine kNN1 OOD -> OCR/DB -> cached YOLO decision"
    )
    parser.add_argument("--pipeline", choices=("ood", "gate", "full", "legacy"), default="full")
    parser.add_argument("--test-dir", type=Path, default=DEFAULT_TEST_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--device", default="0")
    parser.add_argument("--torch-device")
    parser.add_argument("--ocr-device")
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--ood-config", type=Path, default=DEFAULT_OOD_CONFIG)
    parser.add_argument("--ocr-timeout", type=float, default=25.0)
    parser.add_argument("--total-timeout", type=float, default=180.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--final-threshold", type=float, default=0.95)
    parser.add_argument("--ocr-supported-yolo-threshold", type=float, default=0.60)
    parser.add_argument("--ocr-basic-score", type=float, default=50.0)
    parser.add_argument("--ocr-tie-gap", type=float, default=8.0)
    return parser.parse_args()


def run_stage(command: list[str], title: str) -> None:
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")
    print(" ".join(f'\"{item}\"' if " " in item else item for item in command))
    result = subprocess.run(command, cwd=str(CURRENT_DIR))
    if result.returncode:
        raise SystemExit(f"{title} failed (return code {result.returncode})")


def run_legacy_pipeline(args: argparse.Namespace) -> None:
    """Original two-subprocess batch entrypoint, intentionally unchanged in behavior."""
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    ocr_results = output_dir / "ocr_stage_results.jsonl"
    ocr_command = [
        sys.executable, str(CURRENT_DIR / "OCR_STAGE.py"), "--test-dir", str(args.test_dir.resolve()),
        "--output-dir", str(output_dir), "--device", str(args.device), "--restart",
    ]
    if args.limit > 0:
        ocr_command += ["--limit", str(args.limit)]
    run_stage(ocr_command, "STAGE 1 / 2 - PaddleOCR + Database")
    yolo_command = [
        sys.executable, str(CURRENT_DIR / "YOLO_STAGE.py"), "--ocr-results", str(ocr_results),
        "--output-dir", str(output_dir), "--checkpoint", str(args.checkpoint.resolve()),
        "--base-model", str(args.base_model.resolve()), "--device", str(args.device),
        "--final-threshold", str(args.final_threshold),
        "--ocr-supported-yolo-threshold", str(args.ocr_supported_yolo_threshold),
        "--ocr-basic-score", str(args.ocr_basic_score), "--ocr-tie-gap", str(args.ocr_tie_gap),
    ]
    run_stage(yolo_command, "STAGE 2 / 2 - Pair-YOLO + Final Decision")


def _csv_value(value):
    if isinstance(value, (list, tuple, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def _write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({field: _csv_value(row.get(field, "SKIPPED")) for field in fields} for row in rows)


def _load_pairs(test_dir: Path, limit: int):
    from pair_image_io import discover_pairs

    pairs, incomplete = discover_pairs(test_dir, strict=False)
    if limit > 0:
        pairs = pairs[:limit]
    return pairs, incomplete


def _display_value(value, *, digits: int = 1) -> str:
    if value in (None, "", "SKIPPED"):
        return "SKIPPED"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _timing_statistics(values) -> dict:
    numeric = sorted(
        float(value) for value in values
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if not numeric:
        return {"count": 0, "mean": None, "p50": None, "p95": None, "min": None, "max": None, "total": 0.0}

    def percentile(fraction: float) -> float:
        position = (len(numeric) - 1) * fraction
        lower, upper = math.floor(position), math.ceil(position)
        if lower == upper:
            return numeric[lower]
        return numeric[lower] * (upper - position) + numeric[upper] * (position - lower)

    return {
        "count": len(numeric),
        "mean": sum(numeric) / len(numeric),
        "p50": percentile(0.50),
        "p95": percentile(0.95),
        "min": numeric[0],
        "max": numeric[-1],
        "total": sum(numeric),
    }


def _expected_type(label: str) -> str:
    normalized = str(label).strip().casefold().replace("-", "_").replace(" ", "_")
    if normalized in {"ood", "non_drug", "nondrug"}:
        return "NON_DRUG"
    if normalized in {"out", "unknown", "unknown_drug"}:
        return "UNKNOWN_DRUG"
    return "KNOWN_DRUG"


def _is_expected_result_correct(expected_class: str, result: dict) -> bool:
    expected_type = _expected_type(expected_class)
    status = str(result.get("status") or result.get("final_status") or "")
    if expected_type == "NON_DRUG":
        return status in {"NON_DRUG", "NO_DRUG"}
    if expected_type == "UNKNOWN_DRUG":
        return status == "UNKNOWN_DRUG"
    if status != "KNOWN_DRUG":
        return False
    from YOLO_STAGE import canonicalize_yolo_class_name, folder_names_match

    prediction = result.get("drug_name", "")
    return bool(folder_names_match(canonicalize_yolo_class_name(prediction), expected_class))


def _error_category(row: dict) -> str:
    """Return one actionable category for the HTML error report."""
    if row.get("image_integrity_verified") is False:
        return "IMAGE_INTEGRITY_ERROR"
    if row.get("ood_status") == "OOD_ERROR":
        return "OOD_ERROR"
    status = str(row.get("final_status") or row.get("status") or "")
    if status in {"ERROR", "TIMEOUT", "INVALID_IMAGE"}:
        return status
    if bool(row.get("correct")):
        return ""
    expected_type = str(row.get("expected_type") or _expected_type(row.get("expected_class", "")))
    if expected_type == "KNOWN_DRUG":
        if row.get("ood_decision") == "REJECT" and status in {"NON_DRUG", "NO_DRUG"}:
            return "KNOWN_DRUG_FALSE_REJECT"
        if status == "UNRECOGNIZED":
            return "KNOWN_DRUG_UNRECOGNIZED"
        if status == "KNOWN_DRUG":
            return "WRONG_DRUG"
    elif expected_type == "NON_DRUG":
        return "NON_DRUG_FALSE_PASS"
    elif expected_type == "UNKNOWN_DRUG":
        if row.get("ood_decision") == "REJECT" and status in {"NON_DRUG", "NO_DRUG"}:
            return "UNKNOWN_DRUG_FALSE_REJECT"
        return "UNKNOWN_DRUG_NOT_IDENTIFIED"
    if row.get("ood_decision") == "REJECT" and status in {"NON_DRUG", "NO_DRUG"}:
        return "OOD_REJECT"
    if status in {"NO_DRUG", "NON_DRUG", "REPOSITION", "UNKNOWN_DRUG", "UNRECOGNIZED"}:
        return status
    if not bool(row.get("correct")):
        return "WRONG_DRUG"
    return ""


def rebuild_full_reports(output_dir: Path) -> Path:
    """Rebuild CSV/summary/HTML from completed JSONL without rerunning inference."""
    output_dir = output_dir.resolve()
    jsonl_path = output_dir / "full_pipeline_results.jsonl"
    summary_path = output_dir / "full_pipeline_summary.json"
    rows = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise RuntimeError(f"No completed rows in {jsonl_path}")
    backup_path = output_dir / "full_pipeline_results.before_ground_truth_fix.jsonl"
    if not backup_path.exists():
        shutil.copy2(jsonl_path, backup_path)
    for row in rows:
        row["expected_type"] = _expected_type(row.get("expected_class", ""))
        row["correct"] = _is_expected_result_correct(row.get("expected_class", ""), row)
    with jsonl_path.open("w", encoding="utf-8", buffering=1) as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    _write_csv(output_dir / "full_pipeline_results.csv", rows, FULL_REPORT_FIELDS)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    known = [row for row in rows if row["expected_type"] == "KNOWN_DRUG"]
    non_drug = [row for row in rows if row["expected_type"] == "NON_DRUG"]
    unknown = [row for row in rows if row["expected_type"] == "UNKNOWN_DRUG"]
    errors = [row for row in rows if _error_category(row)]
    summary.setdefault("stage_timing_ms", {})["successful_known_drug_pipeline"] = _timing_statistics(
        row.get("total_time_ms") for row in rows if row.get("final_status") == "KNOWN_DRUG"
    )
    summary.update({
        "raw_ood_reject_count": sum(row.get("ood_decision") == "REJECT" for row in rows),
        "ood_override_count": sum(row.get("ood_gate_final_decision") == "OVERRIDDEN" for row in rows),
        "ood_blocked_non_drug_count": sum(
            row.get("ood_decision") == "REJECT"
            and row.get("final_status") in {"NON_DRUG", "NO_DRUG"}
            for row in rows
        ),
        "known_drug_total": len(known),
        "known_drug_correct": sum(bool(row["correct"]) for row in known),
        "known_drug_accuracy": (sum(bool(row["correct"]) for row in known) / len(known)) if known else None,
        "known_drug_false_reject": sum(
            row.get("ood_decision") == "REJECT"
            and row.get("final_status") in {"NON_DRUG", "NO_DRUG"}
            for row in known
        ),
        "non_drug_total": len(non_drug),
        "non_drug_correct_reject": sum(bool(row["correct"]) for row in non_drug),
        "non_drug_false_pass": sum(not bool(row["correct"]) for row in non_drug),
        "non_drug_rejection_rate": (sum(bool(row["correct"]) for row in non_drug) / len(non_drug)) if non_drug else None,
        "unknown_drug_total": len(unknown),
        "unknown_drug_false_reject": sum(
            row.get("ood_decision") == "REJECT"
            and row.get("final_status") in {"NON_DRUG", "NO_DRUG"}
            for row in unknown
        ),
        "correct_count": sum(bool(row["correct"]) for row in rows),
        "incorrect_or_unrecognized_count": len(errors),
        "overall_accuracy": sum(bool(row["correct"]) for row in rows) / len(rows),
        "error_category_counts": {
            category: sum(_error_category(row) == category for row in rows)
            for category in sorted({_error_category(row) for row in rows if _error_category(row)})
        },
        "pair_forward_violations": sum(int(row.get("pair_forward_count") or 0) != 1 for row in rows),
        "image_integrity_failures": sum(row.get("image_integrity_verified") is not True for row in rows),
    })
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return _write_full_html_report(output_dir, rows, summary)


def _rejection_kind(row: dict) -> str:
    """Classify only the two rejection outcomes requested for the HTML gallery."""
    final_status = str(row.get("final_status") or row.get("status") or "").upper()
    if (
        str(row.get("ood_decision") or "").upper() == "REJECT"
        and final_status in {"NON_DRUG", "NO_DRUG"}
    ):
        return "OOD_REJECT"
    if final_status == "UNRECOGNIZED":
        return "OCR_YOLO_UNRESOLVED"
    return ""


def _per_drug_results(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        if str(row.get("expected_type") or _expected_type(row.get("expected_class", ""))) != "KNOWN_DRUG":
            continue
        grouped.setdefault(str(row.get("expected_class") or "UNKNOWN_CLASS"), []).append(row)

    results: list[dict] = []
    for drug_name in sorted(grouped, key=str.casefold):
        items = grouped[drug_name]
        correct = sum(bool(item.get("correct")) for item in items)
        ood_reject = sum(_rejection_kind(item) == "OOD_REJECT" for item in items)
        unresolved = sum(_rejection_kind(item) == "OCR_YOLO_UNRESOLVED" for item in items)
        results.append({
            "drug_name": drug_name,
            "total": len(items),
            "correct": correct,
            "accuracy_percent": 100.0 * correct / len(items),
            "ood_reject": ood_reject,
            "ocr_yolo_unresolved": unresolved,
            "wrong_drug": len(items) - correct - ood_reject - unresolved,
        })
    return results


def _write_full_html_report(output_dir: Path, rows: list[dict], summary: dict) -> Path:
    """Write per-drug percentages and a gallery of every rejected pair."""
    report_path = output_dir / "full_pipeline_report.html"
    drug_results = _per_drug_results(rows)
    rejected = [(row, _rejection_kind(row)) for row in rows if _rejection_kind(row)]
    image_dir = output_dir / "rejected_images"
    image_dir.mkdir(parents=True, exist_ok=True)
    # This directory contains report-only copies. Remove stale copies so an
    # overwritten run cannot leave images from an older rejection set behind.
    for stale_image in image_dir.iterdir():
        if stale_image.is_file():
            stale_image.unlink()

    def esc(value) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        return html.escape(str(value), quote=True)

    drug_rows = []
    for item in drug_results:
        accuracy = float(item["accuracy_percent"])
        css_class = "perfect" if accuracy == 100.0 else ("warning" if accuracy >= 90.0 else "bad")
        drug_rows.append(
            f'<tr class="{css_class}">'
            f'<td>{esc(item["drug_name"])}</td><td>{item["total"]}</td><td>{item["correct"]}</td>'
            f'<td><strong>{accuracy:.2f}%</strong></td><td>{item["ood_reject"]}</td>'
            f'<td>{item["ocr_yolo_unresolved"]}</td><td>{item["wrong_drug"]}</td></tr>'
        )

    gallery_cards: list[str] = []
    for row, kind in rejected:
        image_tags: list[str] = []
        index = int(row.get("group_index") or 0)
        for camera_name in ("cam0", "cam1"):
            source_value = row.get(camera_name)
            source = Path(str(source_value)) if source_value else None
            if source and source.is_file():
                suffix = source.suffix.lower() if source.suffix else ".jpg"
                destination = image_dir / f"{index:04d}_{camera_name}{suffix}"
                shutil.copy2(source, destination)
                image_tags.append(
                    f'<figure><a href="{esc(destination.relative_to(output_dir).as_posix())}" target="_blank">'
                    f'<img src="{esc(destination.relative_to(output_dir).as_posix())}" loading="lazy" '
                    f'alt="{esc(row.get("group_id"))} {camera_name}"></a><figcaption>{camera_name}</figcaption></figure>'
                )
            else:
                image_tags.append(f'<figure class="missing">{camera_name} 影像不存在</figure>')

        label = "OOD 被 REJECT" if kind == "OOD_REJECT" else "OCR+YOLO 判不出來"
        final_status = str(row.get("final_status") or row.get("status") or "")
        if final_status == "UNRECOGNIZED":
            output_name = "unknown"
        elif final_status in {"NON_DRUG", "NO_DRUG"}:
            output_name = final_status
        else:
            output_name = row.get("drug_name") or "—"
        gallery_cards.append(
            f'<article class="reject-card {kind.lower()}">'
            f'<div class="reject-head"><span class="badge">{esc(label)}</span><strong>{esc(row.get("group_id"))}</strong></div>'
            f'<div class="reason">{esc(label)}</div>'
            f'<div class="meta">預期：{esc(row.get("expected_class"))}｜最終：{esc(row.get("final_status"))}｜輸出：{esc(output_name)}</div>'
            f'<div class="meta">OOD：{esc(row.get("ood_decision"))}（score={esc(row.get("ood_score"))}）｜OCR：{esc(row.get("ocr_status"))}｜YOLO：{esc(row.get("pair_yolo_top1"))}（{esc(row.get("pair_yolo_confidence"))}）</div>'
            f'<div class="photos">{"".join(image_tags)}</div></article>'
        )

    generated_at = time.strftime("%Y-%m-%d %H:%M:%S %z")
    # Keep exported HTML portable: never expose or depend on the source machine's
    # absolute dataset path. Image links below are already relative to output_dir.
    test_dir_display = Path(str(summary.get("test_dir") or "")).name or "."
    document = f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>pythonOCR 藥品辨識成果與拒絕影像</title>
<style>
:root{{--bg:#f5f7fb;--card:#fff;--ink:#172033;--muted:#60708a;--line:#d9e0ea;--ok:#087f5b;--bad:#c92a2a;--accent:#2855d9}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 system-ui,"Microsoft JhengHei",sans-serif}}
main{{max-width:1500px;margin:auto;padding:24px}} h1{{margin:0 0 4px}} h2{{margin:0 0 14px}} .muted,.meta{{color:var(--muted)}}
.panel{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:14px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%;white-space:nowrap}} th,td{{border-bottom:1px solid var(--line);padding:8px 10px;text-align:left}} th{{position:sticky;top:0;background:#eef2f8;z-index:1}}
tr.perfect td:nth-child(4){{color:var(--ok)}} tr.warning td:nth-child(4),tr.bad td:nth-child(4){{color:var(--bad)}}
input{{padding:9px;border:1px solid var(--line);border-radius:6px;margin-bottom:12px;min-width:280px}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(440px,1fr));gap:14px}} .reject-card{{border:1px solid var(--line);border-left:5px solid var(--bad);border-radius:9px;padding:12px;background:#fff}}
.reject-head{{display:flex;gap:10px;align-items:center;flex-wrap:wrap}} .badge{{background:#ffe3e3;color:#a51111;border-radius:999px;padding:3px 8px;font-weight:750}} .reason{{font-size:17px;font-weight:750;margin:8px 0}}
.photos{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:10px}} figure{{margin:0}} img{{display:block;width:100%;height:230px;object-fit:contain;background:#111;border-radius:6px}} figcaption{{text-align:center;color:var(--muted);margin-top:3px}}
.empty{{padding:28px;text-align:center;color:var(--ok);font-weight:750}} @media(max-width:700px){{.gallery{{grid-template-columns:1fr}}.photos{{grid-template-columns:1fr}}}}
@media print{{body{{background:#fff}} .panel,.reject-card{{break-inside:avoid}} input{{display:none}}}}
</style></head><body><main>
<h1>pythonOCR 藥品辨識成果與拒絕影像</h1>
<div class="muted">產生時間：{esc(generated_at)}｜資料集：{esc(test_dir_display)}｜流程：OOD → OCR + Database → 快取 YOLO 決策（OpenCV gate 已停用）</div>
<section class="panel"><h2>每種藥品辨識成果</h2><input id="drugSearch" placeholder="搜尋藥品..." oninput="filterDrugs(this.value)">
<table id="drugTable"><thead><tr><th>藥品</th><th>測試組數</th><th>正確</th><th>辨識率</th><th>OOD 被 REJECT</th><th>OCR+YOLO 判不出來</th><th>錯誤藥名</th></tr></thead><tbody>{''.join(drug_rows)}</tbody></table></section>
<section class="panel"><h2>所有被拒絕／無法判定的照片</h2><div class="muted">「OOD 被 REJECT」表示 OOD 分數低於門檻；「OCR+YOLO 判不出來」表示 OOD 已通過，但原系統最終仍無法確認。</div>
<div class="gallery">{''.join(gallery_cards) if gallery_cards else '<div class="empty">沒有被拒絕或無法判定的影像</div>'}</div></section>
<script>function filterDrugs(q){{q=q.toLowerCase();document.querySelectorAll('#drugTable tbody tr').forEach(r=>r.hidden=!r.innerText.toLowerCase().includes(q));}}</script>
</main></body></html>"""
    report_path.write_text(document, encoding="utf-8")
    return report_path


def _print_full_stage_result(index: int, total: int, pair, result: dict) -> None:
    """Print every gate separately so a batch run is diagnosable without opening CSV."""
    print(f"\n[{index}/{total}] {pair.label}/{pair.pair_id}", flush=True)
    print("  OpenCV gate       : DISABLED", flush=True)
    print(
        "  Cosine kNN1 OOD  : "
        f"status={_display_value(result.get('ood_status'))}, "
        f"score={_display_value(result.get('ood_score'), digits=6)}, "
        f"threshold={_display_value(result.get('ood_threshold'), digits=6)}, "
        f"nearest={_display_value(result.get('ood_nearest_label'))}, "
        f"{_display_value(result.get('ood_time_ms'), digits=3)} ms",
        flush=True,
    )
    if result.get("ood_error"):
        print(f"  OOD error         : {result['ood_error']}", flush=True)
    if result.get("ood_decision") == "REJECT":
        print(
            "  OOD consensus     : "
            f"{_display_value(result.get('ood_gate_final_decision'))} | "
            f"{_display_value(result.get('ood_override_reason'))}",
            flush=True,
        )
    print(
        "  OCR / Database    : "
        f"executed={bool(result.get('ocr_executed'))}, "
        f"ocr={_display_value(result.get('ocr_status'))}, "
        f"database={_display_value(result.get('database_status'))}, "
        f"{_display_value(result.get('ocr_time_ms'))} ms",
        flush=True,
    )
    print(
        "  Pair YOLO         : "
        f"executed={bool(result.get('pair_yolo_executed'))}, "
        f"top1={_display_value(result.get('pair_yolo_top1'))}, "
        f"confidence={_display_value(result.get('pair_yolo_confidence'), digits=6)}, "
        f"forward_count={_display_value(result.get('pair_forward_count'))}, "
        f"{_display_value(result.get('pair_yolo_time_ms'))} ms",
        flush=True,
    )
    print(
        "  Final             : "
        f"{_display_value(result.get('status'))} | "
        f"{_display_value(result.get('drug_name'))} | "
        f"{_display_value(result.get('total_time_ms'))} ms",
        flush=True,
    )


def run_ood_pipeline(args: argparse.Namespace) -> None:
    """One-forward Pair-YOLO/cosine-kNN1 diagnostics without OCR."""
    from ood_filter import CosineKNN1OODFilter
    from pair_image_io import read_bgr
    from realtime_inference import array_hash

    test_dir = args.test_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs, incomplete = _load_pairs(test_dir, args.limit)
    torch_device = args.torch_device or (f"cuda:{args.device}" if str(args.device).isdigit() else str(args.device))
    gate = CosineKNN1OODFilter(args.ood_config.resolve(), device=torch_device)
    rows: list[dict] = []
    details_path = output_dir / "ood_gate_details.jsonl"
    print(f"OOD gate pairs: {len(pairs)}; threshold: {gate.threshold}")
    with details_path.open("w", encoding="utf-8", buffering=1) as details:
        for index, pair in enumerate(pairs, 1):
            started = time.perf_counter()
            cam0, cam1 = read_bgr(pair.cam0), read_bgr(pair.cam1)
            before = [array_hash(cam0), array_hash(cam1)]
            try:
                ood = gate.predict_arrays(cam0, cam1)
                status = "NON_DRUG" if ood["ood_decision"] == "REJECT" else "CONTINUE"
            except Exception as exc:
                ood = {"ood_status": "OOD_ERROR", "ood_decision": "OOD_ERROR", "ood_error": f"{type(exc).__name__}: {exc}"}
                status = "OOD_ERROR"
            record = {
                "group_index": index, "expected_class": pair.label, "group_id": pair.pair_id,
                "cam0": str(pair.cam0), "cam1": str(pair.cam1),
                "opencv_validation_decision": "DISABLED",
                "opencv_final_status": "DISABLED",
                **ood,
                "image_integrity_verified": before == [array_hash(cam0), array_hash(cam1)],
                "final_status": status, "total_time_ms": (time.perf_counter() - started) * 1000.0,
            }
            details.write(json.dumps(record, ensure_ascii=False) + "\n")
            rows.append(record)
            print(f"[{index}/{len(pairs)}] {pair.pair_id} -> {status} / {record.get('ood_score', 'SKIPPED')}", flush=True)
    _write_csv(output_dir / "ood_gate_summary.csv", rows, FULL_REPORT_FIELDS)
    summary = {
        "pipeline": "ood", "total_pairs": len(pairs), "incomplete_pairs": incomplete,
        "compatibility": gate.compatibility_metadata(),
        "counts": {name: sum(row["final_status"] == name for row in rows) for name in sorted({row["final_status"] for row in rows})},
    }
    (output_dir / "ood_gate_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


def run_full_pipeline(args: argparse.Namespace) -> None:
    from pair_image_io import read_bgr
    from realtime_inference import RealtimeInferenceRuntime

    test_dir = args.test_dir.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs, incomplete = _load_pairs(test_dir, args.limit)
    torch_device = args.torch_device or (f"cuda:{args.device}" if str(args.device).isdigit() else str(args.device))
    ocr_device = args.ocr_device or str(args.device)
    runtime = RealtimeInferenceRuntime(
        ood_config=args.ood_config,
        torch_device=torch_device, ocr_device=ocr_device,
        ocr_timeout_seconds=args.ocr_timeout, total_timeout_seconds=args.total_timeout,
        final_threshold=args.final_threshold,
        ocr_supported_yolo_threshold=args.ocr_supported_yolo_threshold,
        ocr_basic_score=args.ocr_basic_score, ocr_tie_gap=args.ocr_tie_gap,
    )
    rows: list[dict] = []
    jsonl_path = output_dir / "full_pipeline_results.jsonl"
    started_all = time.perf_counter()
    try:
        with jsonl_path.open("w", encoding="utf-8", buffering=1) as stream:
            for index, pair in enumerate(pairs, 1):
                cam0, cam1 = read_bgr(pair.cam0), read_bgr(pair.cam1)
                result = runtime.predict_pair(cam0, cam1)
                expected_type = _expected_type(pair.label)
                correct = _is_expected_result_correct(pair.label, result)
                stage_times = [
                    value for value in (result.get("ocr_time_ms"), result.get("pair_yolo_time_ms"))
                    if isinstance(value, (int, float))
                ]
                record = {
                    "group_index": index, "expected_type": expected_type,
                    "expected_class": pair.label, "group_id": pair.pair_id,
                    "cam0": str(pair.cam0), "cam1": str(pair.cam1), **result,
                    "final_status": result.get("status"), "final_message": result.get("message", ""),
                    "correct": correct, "ocr_yolo_pipeline_time_ms": sum(stage_times) if stage_times else None,
                }
                stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                rows.append(record)
                _print_full_stage_result(index, len(pairs), pair, result)
    finally:
        runtime.close()
    _write_csv(output_dir / "full_pipeline_results.csv", rows, FULL_REPORT_FIELDS)
    ocr_yolo_times = [float(row["ocr_yolo_pipeline_time_ms"]) for row in rows if isinstance(row.get("ocr_yolo_pipeline_time_ms"), (int, float))]
    elapsed_seconds = time.perf_counter() - started_all
    opencv_blocked_count = sum(
        row.get("opencv_validation_decision") == "INVALID_IMAGE"
        or row.get("opencv_final_status") in {"NO_DRUG", "REPOSITION", "RETRY_OR_REPOSITION"}
        for row in rows
    )
    raw_ood_reject_count = sum(row.get("ood_decision") == "REJECT" for row in rows)
    ood_override_count = sum(row.get("ood_gate_final_decision") == "OVERRIDDEN" for row in rows)
    ood_blocked_count = sum(
        row.get("ood_decision") == "REJECT"
        and row.get("final_status") in {"NON_DRUG", "NO_DRUG"}
        for row in rows
    )
    gate_passed_to_ocr_count = sum(bool(row.get("ocr_executed")) for row in rows)
    final_counts = {
        name: sum(row.get("final_status") == name for row in rows)
        for name in sorted({str(row.get("final_status")) for row in rows})
    }
    ood_status_counts = {
        name: sum(str(row.get("ood_status") or "SKIPPED") == name for row in rows)
        for name in sorted({str(row.get("ood_status") or "SKIPPED") for row in rows})
    }
    opencv_validation_times = [
        (row.get("opencv_validation_details") or {}).get("time_ms")
        if isinstance(row.get("opencv_validation_details"), dict) else None
        for row in rows
    ]
    opencv_total_times = [
        validation_ms + occupancy_ms
        if isinstance(validation_ms, (int, float)) and isinstance(occupancy_ms, (int, float)) else None
        for validation_ms, occupancy_ms in zip(opencv_validation_times, (row.get("opencv_time_ms") for row in rows))
    ]
    stage_timing_ms = {
        "opencv_validation": _timing_statistics(opencv_validation_times),
        "opencv_occupancy": _timing_statistics(row.get("opencv_time_ms") for row in rows),
        "opencv_total": _timing_statistics(opencv_total_times),
        "ood_cosine_knn1": _timing_statistics(row.get("ood_time_ms") for row in rows),
        "pair_preprocess": _timing_statistics(row.get("pair_preprocess_time_ms") for row in rows),
        "ocr_worker_including_database": _timing_statistics(
            row.get("ocr_time_ms") for row in rows if row.get("ocr_executed")
        ),
        "database_match_subset_of_ocr": _timing_statistics(
            row.get("database_match_time_ms") for row in rows if row.get("ocr_executed")
        ),
        "pair_yolo": _timing_statistics(
            row.get("pair_yolo_time_ms") for row in rows if row.get("pair_yolo_executed")
        ),
        "successful_known_drug_pipeline": _timing_statistics(
            row.get("total_time_ms") for row in rows if row.get("final_status") == "KNOWN_DRUG"
        ),
        "whole_pipeline": _timing_statistics(row.get("total_time_ms") for row in rows),
    }
    summary = {
        "pipeline": "full",
        "test_dir": str(test_dir),
        "scheduled_pairs": len(pairs),
        "processed_pairs": len(rows),
        "total_pairs": len(pairs),
        "incomplete_pairs": incomplete,
        "opencv_blocked_count": opencv_blocked_count,
        "raw_ood_reject_count": raw_ood_reject_count,
        "ood_override_count": ood_override_count,
        "ood_blocked_non_drug_count": ood_blocked_count,
        "gate_passed_to_ocr_count": gate_passed_to_ocr_count,
        "known_drug_count": final_counts.get("KNOWN_DRUG", 0),
        "unknown_drug_count": final_counts.get("UNKNOWN_DRUG", 0),
        "unrecognized_count": final_counts.get("UNRECOGNIZED", 0),
        "error_count": final_counts.get("ERROR", 0),
        "timeout_count": final_counts.get("TIMEOUT", 0),
        "ood_status_counts": ood_status_counts,
        "ood_error_count": ood_status_counts.get("OOD_ERROR", 0),
        "ood_compatibility": runtime.ood_metadata,
        "final_status_counts": final_counts,
        "stage_timing_ms": stage_timing_ms,
        "counts": final_counts,
        "count_definitions": {
            "opencv_blocked_count": "OpenCV gate is disabled; cosine kNN1 OOD is the only non-drug gate",
            "raw_ood_reject_count": "Cosine kNN1 score is below threshold before consensus override",
            "ood_override_count": "Raw OOD reject was rescued because OCR/database and high-confidence Pair-YOLO named the same drug",
            "ood_blocked_non_drug_count": "Raw OOD reject remained NON_DRUG after OCR/YOLO consensus check",
            "gate_passed_to_ocr_count": "OCR + database executed; raw OOD rejects require the same-drug consensus check",
            "unknown_drug_count": "Final system status is UNKNOWN_DRUG; this requires reliable OCR/barcode/license evidence of a drug not found in the database",
            "unrecognized_count": "Evidence was insufficient to name or confirm an unknown drug",
        },
        "known_drug_accuracy": (
            sum(bool(row["correct"]) for row in rows if row["expected_type"] == "KNOWN_DRUG")
            / sum(row["expected_type"] == "KNOWN_DRUG" for row in rows)
        ) if any(row["expected_type"] == "KNOWN_DRUG" for row in rows) else None,
        "correct_count": sum(bool(row["correct"]) for row in rows),
        "incorrect_or_unrecognized_count": sum(not bool(row["correct"]) for row in rows),
        "error_category_counts": {
            category: sum(_error_category(row) == category for row in rows)
            for category in sorted({_error_category(row) for row in rows if _error_category(row)})
        },
        "average_total_time_ms": (sum(float(row["total_time_ms"]) for row in rows) / len(rows)) if rows else None,
        "average_ocr_yolo_pipeline_time_ms": sum(ocr_yolo_times) / len(ocr_yolo_times) if ocr_yolo_times else None,
        "pair_forward_count": sum(int(row.get("pair_forward_count") or 0) for row in rows),
        "gpu_peak_vram_mb": max((float(row["gpu_peak_vram_mb"]) for row in rows if isinstance(row.get("gpu_peak_vram_mb"), (int, float))), default=None),
        "timing_note": "Pair-YOLO logits and Hidden-256 are produced by the same single forward before OCR",
        "elapsed_seconds": elapsed_seconds,
        "elapsed_hh_mm_ss": time.strftime("%H:%M:%S", time.gmtime(elapsed_seconds)),
    }
    (output_dir / "full_pipeline_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    html_report = _write_full_html_report(output_dir, rows, summary)
    print("\n" + "=" * 80)
    print("FULL PIPELINE SUMMARY")
    print("=" * 80)
    print(f"Scheduled / processed       : {len(pairs)} / {len(rows)}")
    print("OpenCV gate                 : DISABLED")
    print(f"Raw OOD rejects             : {raw_ood_reject_count}")
    print(f"OOD consensus overrides     : {ood_override_count}")
    print(f"OOD blocked as NON_DRUG     : {ood_blocked_count}")
    print(f"Passed gates into OCR       : {gate_passed_to_ocr_count}")
    print(f"Final KNOWN_DRUG            : {final_counts.get('KNOWN_DRUG', 0)}")
    print(f"Final UNKNOWN_DRUG          : {final_counts.get('UNKNOWN_DRUG', 0)}")
    print(f"Final UNRECOGNIZED          : {final_counts.get('UNRECOGNIZED', 0)}")
    print(f"Final ERROR / TIMEOUT       : {final_counts.get('ERROR', 0)} / {final_counts.get('TIMEOUT', 0)}")
    print(f"OOD status counts            : {json.dumps(ood_status_counts, ensure_ascii=False)}")
    print("Stage timing mean / P50 / P95 (ms):")
    for stage, stats in stage_timing_ms.items():
        if stats["count"]:
            print(
                f"  {stage:<31} "
                f"{stats['mean']:.1f} / {stats['p50']:.1f} / {stats['p95']:.1f} "
                f"(n={stats['count']})"
            )
    print(f"Elapsed time                : {summary['elapsed_hh_mm_ss']} ({elapsed_seconds:.1f} seconds)")
    print(f"Summary JSON                : {output_dir / 'full_pipeline_summary.json'}")
    print(f"HTML report                 : {html_report}")


def main() -> None:
    args = parse_args()
    if args.pipeline == "legacy":
        run_legacy_pipeline(args)
    elif args.pipeline in {"ood", "gate"}:
        run_ood_pipeline(args)
    else:
        run_full_pipeline(args)


if __name__ == "__main__":
    import multiprocessing as mp

    mp.freeze_support()
    main()
