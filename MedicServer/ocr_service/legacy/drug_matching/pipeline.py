import time
from numbers import Real
from pathlib import Path

import ocr
from ocr_diagnostics import capture, span, exception_details
from .matcher import build_observation
from .identifiers import attach_database_results

TIMING_FIELDS = ["image_load_time_ms", "preprocess_time_ms", "ocr_time_ms",
                 "barcode_time_ms", "normalization_time_ms", "database_query_time_ms",
                 "matching_compute_time_ms", "decision_time_ms", "total_inference_time_ms"]

SUCCESS_STATUSES = {"MATCHED", "EXACT_ID", "NAME_ONLY_UNIQUE"}


def _ms(ns): return round(ns / 1e6, 2)


def should_adopt_angle_fallback(baseline_match, fallback_match):
    """Only a newly successful database decision may replace a failed one."""
    return (
        baseline_match.get("status") not in SUCCESS_STATUSES
        and fallback_match.get("status") in SUCCESS_STATUSES
        and float(fallback_match.get("match_score") or 0.0)
        > float(baseline_match.get("match_score") or 0.0)
    )


def _observation_signature(observation):
    """Return a stable identity for OCR evidence already sent to matching."""
    texts = {
        str(item.get("normalized") or item.get("text") or "").strip().casefold()
        for item in observation.get("text_evidence", [])
        if str(item.get("normalized") or item.get("text") or "").strip()
    }
    barcodes = {
        str(value).strip().casefold()
        for value in observation.get("barcodes", [])
        if str(value).strip()
    }
    return tuple(sorted(texts)), tuple(sorted(barcodes))


def _has_confirmed_identifier_absence(matched):
    """True only for a reliable barcode/license that the DB cannot resolve."""
    if str(matched.get("status", "")).upper() not in {"UNKNOWN", "CONFLICT"}:
        return False
    sources = matched.get("identifier_sources") or []
    not_found = any(
        source.get("type") in {"BARCODE", "LICENSE"}
        and str(source.get("status", "")).endswith("DB_NOT_FOUND")
        for source in sources
    )
    has_match = any(source.get("database_match") for source in sources)
    return not_found and not has_match


def _infer_pair_paths(paths, engines, matcher):
    total_started = time.perf_counter_ns()
    load_started = time.perf_counter_ns()
    frames = []
    for path in paths:
        with span("image_load", path):
            frames.append(ocr.read_image(Path(path))[0] if path else None)
    load_ms = _ms(time.perf_counter_ns() - load_started)
    return infer_pair_frames(frames, paths, engines, matcher, total_started, load_ms)


def infer_pair_frames(frames, labels, engines, matcher, total_started=None, image_load_ms=None):
    total_started = total_started or time.perf_counter_ns()
    if image_load_ms is None:
        started = time.perf_counter_ns(); frames = [f.copy() if f is not None else None for f in frames]
        image_load_ms = _ms(time.perf_counter_ns() - started)
    results, stage = [], "preprocess_ocr_barcode"
    observation = {}
    preprocessing = ocr_ms = barcode_ms = normalization_ms = 0.0
    query_ms = compute_ms = decision_ms = 0.0
    try:
        for frame, label in zip(frames, labels):
            if frame is None:
                results.append(None); continue
            with span("photo", label):
                result = ocr.recognize_photo(frame, Path(str(label)), Path("unused.png"), engines[0], engines[1], write_outputs=False)
            results.append(result)
            preprocessing += result["timing"]["preprocess_time_ms"]
            ocr_ms += result["timing"]["ocr_time_ms"]
            barcode_ms += result["timing"]["barcode_time_ms"]
        stage = "normalization"; started = time.perf_counter_ns()
        with span("normalization"):
            observation = build_observation(results)
        normalization_ms = _ms(time.perf_counter_ns() - started)
        stage = "decision"
        with span("decision"):
            matched = matcher.match(observation)
        baseline_match = matched

        # Successful pairs never pay for the expensive angle sweep. For a
        # failed database decision, retry the most text-like side first while
        # preserving the normal result and the original barcode fields.
        if (
            matched.get("status") not in SUCCESS_STATUSES
            and not _has_confirmed_identifier_absence(matched)
        ):
            seen_observations = {_observation_signature(observation)}
            ranked_indices = sorted(
                (index for index, result in enumerate(results) if result is not None),
                key=lambda index: ocr.ocr_text_quality(
                    results[index].get("captured_text", [])
                )["score"],
                reverse=True,
            )
            for index in ranked_indices:
                base_photo = results[index]
                base_photo["angle_fallback"] = {
                    "attempted": True,
                    "adopted": False,
                    "reason": "no locally better OCR candidate",
                }
                fallback_photo = ocr.recognize_photo_angle_fallback(
                    frames[index], base_photo, engines[0], engines[1]
                )
                if fallback_photo is None:
                    continue
                candidate_results = list(results)
                candidate_results[index] = fallback_photo
                candidate_observation = build_observation(candidate_results)
                signature = _observation_signature(candidate_observation)
                if signature in seen_observations:
                    base_photo["angle_fallback"] = {
                        **fallback_photo["angle_fallback"],
                        "adopted": False,
                        "reason": "duplicate OCR evidence; database match skipped",
                    }
                    continue
                seen_observations.add(signature)
                candidate_match = matcher.match(candidate_observation)
                if not should_adopt_angle_fallback(baseline_match, candidate_match):
                    base_photo["angle_fallback"] = {
                        **fallback_photo["angle_fallback"],
                        "adopted": False,
                        "reason": "database decision did not improve to a unique match",
                        "candidate_status": candidate_match.get("status"),
                        "candidate_match_score": candidate_match.get("match_score", 0.0),
                    }
                    continue

                fallback_photo["angle_fallback"]["adopted"] = True
                fallback_photo["angle_fallback"]["reason"] = (
                    "higher-quality OCR produced a unique database match"
                )
                fallback_photo["angle_fallback"]["baseline_status"] = (
                    baseline_match.get("status")
                )
                fallback_photo["angle_fallback"]["candidate_status"] = (
                    candidate_match.get("status")
                )
                fallback_photo["angle_fallback"]["candidate_match_score"] = (
                    candidate_match.get("match_score", 0.0)
                )
                results = candidate_results
                observation = candidate_observation
                matched = candidate_match
                break

        attach_database_results(results, matched)
        query_ms = matched["database_query_time_ms"]
        compute_ms = matched["matching_compute_time_ms"]
        decision_ms = matched["decision_time_ms"]
        total_wall_ms = _ms(time.perf_counter_ns() - total_started)
        timing = {"image_load_time_ms": image_load_ms, "preprocess_time_ms": round(preprocessing, 2),
                  "ocr_time_ms": round(ocr_ms, 2), "barcode_time_ms": round(barcode_ms, 2),
                  "normalization_time_ms": normalization_ms,
                  "database_query_time_ms": round(query_ms, 2),
                  "matching_compute_time_ms": round(compute_ms, 2),
                  "decision_time_ms": round(decision_ms, 2),
                  "total_inference_time_ms": max(total_wall_ms, round(decision_ms, 2))}
        return {"status": matched["status"], "drug_id": matched["drug_id"],
                # Preserve the matcher-resolved product.  In particular, an
                # EXACT_ID decision may not be the first score-ranked OCR
                # candidate, so downstream fusion must not reconstruct the
                # winner from candidates[0].
                "drug": matched.get("drug"),
                "timing": timing, "side_states": observation["side_states"],
                "candidates": matched["candidates"], "error_stage": "",
                "observation": observation, "photos": results,
                "database_candidate_count": matched.get("database_candidate_count", 0),
                "top1_top2_gap": matched.get("top1_top2_margin", 0),
                "matched_fields": matched.get("matched_fields", []),
                "reason": matched.get("reason", ""),
                "identification_method": matched.get("identification_method", ""),
                "matched_identifier": matched.get("matched_identifier", ""),
                "identifier_sources": matched.get("identifier_sources", []),
                "identifier_source": matched.get("identifier_source", "NONE"),
                "barcode_database_matches": matched.get("barcode_database_matches", []),
                "license_database_matches": matched.get("license_database_matches", []),
                "identifier_corrected": matched.get("identifier_corrected", False),
                "identifier_db_match_count": matched.get("identifier_db_match_count", 0),
                "identifier_agreement": matched.get("identifier_agreement", "NONE"),
                "secondary_conflicts": matched.get("secondary_conflicts", [])}
    except Exception as error:
        import psycopg2
        database_error = isinstance(error, psycopg2.Error)
        elapsed = _ms(time.perf_counter_ns() - total_started)
        timing = {field: 0.0 for field in TIMING_FIELDS}
        timing.update({"image_load_time_ms": image_load_ms or 0.0,
                       "preprocess_time_ms": round(preprocessing, 2),
                       "ocr_time_ms": round(ocr_ms, 2),
                       "barcode_time_ms": round(barcode_ms, 2),
                       "normalization_time_ms": round(normalization_ms, 2),
                       "database_query_time_ms": round(query_ms, 2),
                       "matching_compute_time_ms": round(compute_ms, 2),
                       "decision_time_ms": round(decision_ms, 2)})
        timing["total_inference_time_ms"] = elapsed
        return {"status": "UNKNOWN", "drug_id": None, "timing": timing,
                "side_states": ["INFORMATIVE" if r and r.get("captured_text") else ("NO_TEXT_EXPECTED" if r else "UNREADABLE") for r in results] + ["UNREADABLE"], "candidates": [], "error_stage": stage,
                **exception_details(error), "database_error": database_error, "photos": results,
                "observation": observation,
                "failure_reason": "UNKNOWN_DATABASE_ERROR" if database_error else "UNKNOWN_EXCEPTION",
                "error": f"{type(error).__name__}: {error}", "reason": "inference exception",
                "identification_method": "", "matched_identifier": "",
                "identifier_sources": [], "identifier_corrected": False,
                "identifier_source": "NONE", "barcode_database_matches": [], "license_database_matches": [],
                "identifier_db_match_count": 0, "identifier_agreement": "NONE",
                "secondary_conflicts": []}


def infer_pair_paths(paths, engines, matcher, context=None):
    """Production pipeline with bounded, serializable per-group diagnostics."""
    trace = {"events": [], "warnings": [], **(context or {}),
             "image_paths": [str(p) if p else None for p in paths]}
    started = time.perf_counter_ns()
    with capture(trace):
        try:
            result = _infer_pair_paths(paths, engines, matcher)
        except Exception as error:
            result = {"status": "UNKNOWN", "drug_id": None, "side_states": [],
                      "candidates": [], "error_stage": trace.get("error_stage", "image_load"),
                      "reason": "inference exception", **exception_details(error),
                      "timing": {key: 0.0 for key in TIMING_FIELDS}}
            result["timing"]["total_inference_time_ms"] = _ms(time.perf_counter_ns() - started)
    if result.get("error_stage"):
        result["error_stage"] = trace.get("error_stage", result["error_stage"])
    reason = ""
    if result.get("exception_type"):
        reason = "UNKNOWN_DATABASE_ERROR" if result.get("database_error") else "UNKNOWN_EXCEPTION"
    elif result["status"] == "UNKNOWN":
        observation = result.get("observation", {})
        if not observation.get("texts") and not observation.get("barcodes"):
            raw_lines = [line for event in trace["events"]
                         for page in (event.get("raw_result") or []) if page
                         for line in page if isinstance(line, (list, tuple)) and len(line) > 1
                         and isinstance(line[1], (list, tuple)) and len(line[1]) > 1]
            raw_confidences = [line[1][1] for line in raw_lines
                               if str(line[1][0]).strip() and isinstance(line[1][1], Real)]
            low_confidence = bool(raw_confidences) and max(raw_confidences) < ocr.OCR_OUTPUT_MIN_CONFIDENCE
            reason = "UNKNOWN_LOW_OCR_CONFIDENCE" if low_confidence else "UNKNOWN_NO_OCR_TEXT"
        elif not result.get("database_candidate_count"):
            reason = "UNKNOWN_NO_DB_CANDIDATE"
        elif observation.get("max_confidence", 0) < ocr.OCR_OUTPUT_MIN_CONFIDENCE:
            reason = "UNKNOWN_LOW_OCR_CONFIDENCE"
        else:
            reason = "UNKNOWN_SCORE_TOO_LOW"
    elif result["status"] not in {"MATCHED", "EXACT_ID", "NAME_ONLY_UNIQUE"}:
        reason = result["status"]
    if result.get("exception_type"):
        events = trace["events"]
        for field, prefixes in (("ocr_time_ms", ("English OCR", "Chinese OCR")),
                                ("preprocess_time_ms", ("preprocess",)),
                                ("image_load_time_ms", ("image_load",)),
                                ("barcode_time_ms", ("barcode_qr",)),
                                ("database_query_time_ms", ("database_",)),
                                ("normalization_time_ms", ("normalization",)),
                                ("matching_compute_time_ms", ("field_matching",)),
                                ("decision_time_ms", ("decision",))):
            result["timing"][field] = round(sum(e.get("elapsed_ms", 0) for e in events if e["stage"].startswith(prefixes)), 2)
    candidates = result.get("candidates", [])
    result["top1_candidate"] = candidates[0] if candidates else None
    result["top2_candidate"] = candidates[1] if len(candidates) > 1 else None
    result.setdefault("database_candidate_count", None)
    result.setdefault("top1_top2_gap", None)
    result.setdefault("matched_fields", [])
    result["normalized_ocr_text"] = [e["normalized"] for e in result.get("observation", {}).get("text_evidence", [])]
    result["failure_reason"] = reason
    result["diagnostics"] = trace
    for warning in trace["warnings"]:
        warning["failure_reason"] = "UNKNOWN_BARCODE_FAILED" if warning["stage"].startswith(("barcode", "qr")) else "UNKNOWN_EXCEPTION"
    result.update({key: trace.get(key) for key in ("group_index", "drug_name", "group_id", "image_paths")})
    return result
