import re
import time
from ocr_diagnostics import span

from .license_extractor import extract_licenses
from .normalization import normalize_text, similarity
from .strength_parser import (
    dose_equivalent,
    name_line_has_matching_strength,
    strengths,
)
from .identifiers import decoded_evidence, normalize_barcode


BARCODE_SCORE = 100.0
NAME_EXACT_SCORE = 40.0
NAME_CONTAINS_SCORE = 38.0
NAME_FUZZY_HIGH_SCORE = 35.0
NAME_FUZZY_MID_SCORE = 30.0
NAME_FUZZY_LOW_SCORE = 20.0
SHORT_PREFIX_SCORE = 20.0
CHINESE_NAME_SCORE = 35.0
INGREDIENT_HIGH_SCORE = 30.0
INGREDIENT_LOW_SCORE = 20.0
DOSE_MATCH_SCORE = 20.0
DOSE_MISMATCH_PENALTY = -5.0
DOSAGE_FORM_SCORE = 15.0
MANUFACTURER_SCORE = 10.0
SCORE_THRESHOLD = 50.0
MIN_MATCHED_FIELDS = 2
MIN_TOP_GAP = 8.0
MIN_GENERIC_TOKEN_LENGTH = 4


FORM_RE = re.compile(
    r"\b(?:effervescent|tablet|tab|capsule|cap|granules?|enteric|film.?coated|"
    r"xr|er|sr|cr|mr|s\.?c\.?)\b|錠|膠囊|顆粒", re.I
)
MANUFACTURER_RE = re.compile(r"pharma|laborator|company|co\.?\s*ltd|製藥|股份有限公司", re.I)


def build_observation(image_results):
    texts, barcodes, qrcodes, confidences, evidence = [], set(), set(), [], []
    side_states = []
    barcode_evidence = []
    for camera, result in enumerate(image_results):
        if result is None:
            side_states.append("MISSING_IMAGE")
            continue
        captured = result.get("captured_text", [])
        useful = [item for item in captured if str(item.get("text", "")).strip()]
        side_states.append("INFORMATIVE" if useful else "NO_TEXT_EXPECTED")
        for item in useful:
            raw = str(item.get("raw", item.get("text", ""))).strip()
            entry = {
                "raw": raw,
                "normalized": item.get("normalized") or normalize_text(raw),
                "confidence": float(item.get("confidence", 0)),
                "camera": camera,
                "source": "OCR_NUMBER" if re.fullmatch(r"[0-9\s]+", raw) else "PACKAGE_TEXT_OCR",
            }
            evidence.append(entry)
            texts.append(raw)
            confidences.append(entry["confidence"])
        for item in decoded_evidence(result.get("barcode_details", [])):
            clean = item['normalized_value']
            barcodes.add(clean)
            barcode_evidence.append({**item, "camera": camera})
            if 'qr' in item['format'].lower():
                qrcodes.add(clean)

    unique_texts = list(dict.fromkeys(texts))
    english = [text for text in unique_texts if re.search(r"[A-Za-z]", text)]
    chinese = [text for text in unique_texts if re.search(r"[\u3400-\u9fff]", text)]
    detected_strengths = sorted(set().union(*(strengths(text) for text in unique_texts)) if unique_texts else set())
    dosage_forms = [text for text in unique_texts if FORM_RE.search(text)]
    ingredients = [text for text in unique_texts if re.search(r"[（(].+[）)]", text)]
    manufacturers = [text for text in unique_texts if MANUFACTURER_RE.search(text)]
    return {
        "texts": unique_texts,
        "text_evidence": evidence,
        "english": english,
        "chinese": chinese,
        "barcodes": sorted(barcodes),
        "barcode_evidence": decoded_evidence(barcode_evidence),
        "qrcodes": sorted(qrcodes),
        "drug_name_en": english,
        "drug_name_en_confidence": max(confidences, default=0.0),
        "ingredients": ingredients,
        "dosage_forms": list(dict.fromkeys(dosage_forms)),
        "manufacturers": list(dict.fromkeys(manufacturers)),
        "strengths": detected_strengths,
        "licenses": extract_licenses(unique_texts, {
            text: max(e['confidence'] for e in evidence if e['raw'] == text) for text in unique_texts}),
        "max_confidence": max(confidences, default=0.0),
        "side_states": side_states,
    }


def _best_text_match(texts, candidates, minimum_length=MIN_GENERIC_TOKEN_LENGTH):
    best = {"similarity": 0.0, "evidence": None, "database_value": None, "kind": "none"}
    for text in texts:
        observed = normalize_text(text)
        if len(observed) < minimum_length:
            continue
        for candidate in candidates:
            database = normalize_text(candidate)
            if len(database) < minimum_length:
                continue
            if observed == database:
                score, kind = 100.0, "exact"
            elif database in observed or observed in database:
                score, kind = 100.0, "contains"
            else:
                score, kind = similarity(observed, database), "fuzzy"
            if score > best["similarity"]:
                best = {"similarity": score, "evidence": text,
                        "database_value": candidate, "kind": kind}
    return best


def _name_points(match):
    if match["kind"] == "exact":
        return NAME_EXACT_SCORE
    if match["kind"] == "contains":
        return NAME_CONTAINS_SCORE
    value = match["similarity"]
    if value >= 90:
        return NAME_FUZZY_HIGH_SCORE
    if value >= 80:
        return NAME_FUZZY_MID_SCORE
    if value >= 70:
        return NAME_FUZZY_LOW_SCORE
    return 0.0


def _prefer_specific_longer_names(scored):
    """Penalize a short product-name prefix when OCR supports a longer name.

    This only applies when two database names share the same OCR evidence and
    the observed text contains at least two meaningful characters beyond the
    shorter name. It therefore distinguishes ``Jardiance Duo`` from
    ``Jardiance`` without penalizing ordinary text such as ``Jardiance 10mg``.
    """
    for short_candidate in scored:
        short_match = (
            short_candidate.get("best_evidence", {}).get("drug_name_en") or {}
        )
        if str(short_match.get("kind") or "").lower() != "contains":
            continue

        observed = normalize_text(short_match.get("evidence") or "")
        short_name = normalize_text(short_match.get("database_value") or "")
        if (
            not observed
            or not short_name
            or not observed.startswith(short_name)
            or len(observed) < len(short_name) + 2
        ):
            continue

        longer_supported = False
        for long_candidate in scored:
            if long_candidate is short_candidate:
                continue
            long_match = (
                long_candidate.get("best_evidence", {}).get("drug_name_en") or {}
            )
            long_observed = normalize_text(long_match.get("evidence") or "")
            long_name = normalize_text(long_match.get("database_value") or "")
            if (
                long_observed == observed
                and len(long_name) > len(short_name)
                and long_name.startswith(short_name)
                and (long_name.startswith(observed) or observed.startswith(long_name))
            ):
                longer_supported = True
                break

        if not longer_supported:
            continue

        old_score = float(short_candidate.get("name_score") or 0.0)
        new_score = min(old_score, SHORT_PREFIX_SCORE)
        penalty = old_score - new_score
        if penalty <= 0:
            continue

        short_candidate["name_score"] = new_score
        short_candidate["score"] -= penalty
        short_candidate["match_score"] -= penalty
        short_candidate["evidence_points"] -= penalty
        short_candidate["name_specificity_penalty"] = penalty

    return scored


def _digit_edit_distance(left, right):
    previous = list(range(len(right) + 1))
    for index, char in enumerate(left, 1):
        current = [index]
        for offset, other in enumerate(right, 1):
            current.append(min(current[-1] + 1, previous[offset] + 1,
                               previous[offset - 1] + (char != other)))
        previous = current
    return previous[-1]


def _name_line_dose_hint(texts, names, candidate_dose):
    """Recover a dose only when it shares a line with an intact product name."""
    candidate_numbers = re.findall(r"\d+", str(candidate_dose or ""))
    if not candidate_numbers:
        return None
    target = candidate_numbers[0]
    if len(target) < 3:
        return None
    normalized_names = [normalize_text(value) for value in names if len(normalize_text(value)) >= 2]
    for text in texts:
        normalized = normalize_text(text)
        if not any(name in normalized for name in normalized_names):
            continue
        for digits in re.findall(r"\d{2,5}", str(text)):
            if target in digits or _digit_edit_distance(digits, target) <= 1:
                return text
    return None


class DrugMatcher:
    def __init__(self, repository):
        self.repository = repository

    def match(self, observation):
        # Enforce provenance even for callers bypassing build_observation.
        observation = dict(observation)
        verified = decoded_evidence(observation.get('barcode_evidence', []))
        observation['barcode_evidence'] = verified
        observation['barcodes'] = [item['normalized_value'] for item in verified]
        licences = []
        for entry in observation.get('licenses', []):
            raw = entry.get('raw_text', entry.get('source', ''))
            for parsed in extract_licenses([raw], {raw: entry.get('ocr_confidence')}):
                if parsed['kind'] == entry.get('kind') and parsed['number'] == entry.get('number'):
                    licences.append(parsed)
        observation['licenses'] = list({(e['kind'],e['number']):e for e in licences}.values())
        decision_started = time.perf_counter_ns()
        with span("database_exact_identifiers"):
            exact_hits, exact_query_ms = self._lookup_exact_identifiers(observation)
        with span("database_candidates"):
            products, candidate_query_ms = self.repository.fetch_candidates()
        query_ms = exact_query_ms + candidate_query_ms
        products = list({product["drug_id"]: product for product in products}.values())
        compute_started = time.perf_counter_ns()

        identifier_sources, matched_identifiers = [], []
        resolved_sets, ambiguous_sets, not_found = [], [], []
        barcode_by_value = {item['normalized_value']: item for item in verified}
        for barcode in observation.get("barcodes", []):
            ids = set(exact_hits["barcodes"].get(str(barcode), set()))
            identifier_sources.append({**barcode_by_value[barcode], "type": "BARCODE",
                                       "source": "BARCODE_DECODED", "value": barcode,
                                       "database_match": bool(ids), "drug_ids": sorted(ids),
                                       "drug_id": next(iter(ids)) if len(ids) == 1 else None,
                                       "status": "BARCODE_EXACT_MATCH" if len(ids) == 1 else
                                                 "BARCODE_AMBIGUOUS" if ids else "BARCODE_DECODED_DB_NOT_FOUND"})
            if ids:
                matched_identifiers.append(str(barcode))
                (resolved_sets if len(ids) == 1 else ambiguous_sets).append(ids)
            else:
                not_found.append(f"BARCODE:{barcode}")
        for licence in observation.get("licenses", []):
            key = (str(licence["kind"]), str(licence["number"]))
            ids = set(exact_hits["licenses"].get(key, set()))
            value = f"{key[0]}:{key[1]}"
            identifier_sources.append({"type": "LICENSE", "value": value,
                                       "source": "LICENSE_OCR", "raw_text": licence['raw_text'],
                                       "normalized_identifier": value, "ocr_confidence": licence.get('ocr_confidence'),
                                       "database_match": bool(ids),
                                       "status": "LICENSE_EXACT_MATCH" if len(ids) == 1 else
                                                 "LICENSE_AMBIGUOUS" if ids else "LICENSE_OCR_DB_NOT_FOUND",
                                       "drug_ids": sorted(ids), "source_text": licence.get("source", ""),
                                       "corrected": bool(licence.get("corrected", False))})
            if ids:
                matched_identifiers.append(value)
                (resolved_sets if len(ids) == 1 else ambiguous_sets).append(ids)
            else:
                not_found.append(f"LICENSE:{value}")

        # Only unique, exact DB hits get barcode points. Shared identifiers use
        # OCR to disambiguate; an unknown decoded value contributes zero points.
        observation['_barcode_exact_ids'] = {
            ids[0] for item in identifier_sources if item['source'] == 'BARCODE_DECODED'
            and len(ids := item['drug_ids']) == 1}
        with span("field_matching_and_scoring"):
            scored = [self._score(observation, product) for product in products]
            _prefer_specific_longer_names(scored)
        scored.sort(key=lambda item: item["score"], reverse=True)
        best = scored[0] if scored else None
        second = scored[1] if len(scored) > 1 else None
        gap = (best["score"] - second["score"]) if best and second else (best["score"] if best else 0.0)
        resolved_ids = {next(iter(ids)) for ids in resolved_sets}
        winner = None
        identification_method = ""
        identifier_agreement = "NONE"

        allowed_ids = set.intersection(*ambiguous_sets) if ambiguous_sets else None
        if len(resolved_ids) > 1 or (resolved_ids and allowed_ids is not None and not resolved_ids <= allowed_ids):
            status, reason = "CONFLICT", "complete exact identifiers point to different drug_id values"
            identifier_agreement = "CONFLICT"
        elif len(resolved_ids) == 1:
            exact_id = next(iter(resolved_ids))
            winner = next((product for product in products if product["drug_id"] == exact_id), None)
            status, reason = "EXACT_ID", "unique strong identifier exact match"
            has_barcode = any(item["type"] == "BARCODE" and item["drug_ids"] == [exact_id] for item in identifier_sources)
            has_license = any(item["type"] == "LICENSE" and item["drug_ids"] == [exact_id] for item in identifier_sources)
            identification_method = "BARCODE_AND_LICENSE_EXACT" if has_barcode and has_license else (
                "BARCODE_EXACT" if has_barcode else "LICENSE_EXACT")
            identifier_agreement = "SAME_DRUG" if len(resolved_sets) > 1 else "SINGLE"
        elif ambiguous_sets:
            identifier_agreement = 'AMBIGUOUS'
            eligible = [item for item in scored if item['drug_id'] in allowed_ids]
            lead = eligible[0] if eligible else None
            margin = lead['score'] - eligible[1]['score'] if len(eligible) > 1 else (lead['score'] if lead else 0)
            if lead and observation.get('texts') and margin >= MIN_TOP_GAP and (
                    lead['strong_evidence'] or (lead['score'] >= SCORE_THRESHOLD and len(lead['matched_fields']) >= MIN_MATCHED_FIELDS)):
                winner = next(p for p in products if p['drug_id'] == lead['drug_id'])
                status, reason = 'MATCHED', 'OCR disambiguated shared exact identifier'
                identification_method = 'OCR_DISAMBIGUATED_IDENTIFIER'
            else:
                status, reason = 'AMBIGUOUS', 'shared identifier lacks distinguishing OCR evidence'
        elif not observation.get("texts") and not observation.get("barcodes"):
            status, reason = "UNKNOWN", "no usable OCR text or barcode"
        elif best:
            strong = bool(best["strong_evidence"])
            field_count = len(best["matched_fields"])
            same_top = [item for item in scored if item["score"] == best["score"]]
            if strong and (gap >= MIN_TOP_GAP or len(same_top) == 1):
                winner = next(product for product in products if product["drug_id"] == best["drug_id"])
                only_name = set(best["matched_fields"]).issubset({"drug_name_en", "drug_name_zh"})
                status = "NAME_ONLY_UNIQUE" if only_name else "MATCHED"
                reason = "strong name evidence" if only_name else "strong evidence and top-candidate gap passed"
            elif strong and gap < MIN_TOP_GAP:
                status, reason = "AMBIGUOUS", "strong name evidence maps to tied candidates"
            elif best["score"] >= SCORE_THRESHOLD and field_count >= MIN_MATCHED_FIELDS and gap >= MIN_TOP_GAP:
                winner = next(product for product in products if product["drug_id"] == best["drug_id"])
                status, reason = "MATCHED", "multi-field positive evidence threshold passed"
            elif best["score"] >= SCORE_THRESHOLD and gap < MIN_TOP_GAP:
                status, reason = "AMBIGUOUS", "top1-top2 gap below threshold"
            else:
                status, reason = "UNKNOWN", "insufficient positive evidence"
        else:
            status, reason = "UNKNOWN", "no database candidates"
        if not_found:
            reason = "IDENTIFIER_NOT_FOUND; " + reason

        compute_ms = (time.perf_counter_ns() - compute_started) / 1e6
        decision_ms = max((time.perf_counter_ns() - decision_started) / 1e6, query_ms + compute_ms)
        all_hit_ids = set().union(*resolved_sets, *ambiguous_sets) if resolved_sets or ambiguous_sets else set()
        return {
            "status": status, "reason": reason,
            "drug_id": winner["drug_id"] if winner else None, "drug": winner,
            "database_candidate_count": len(products), "candidates": scored[:5], "match_score": best["score"] if best else 0.0,
            "evidence_points": best["score"] if best else 0.0,
            "top1_top2_margin": gap,
            "matched_fields": best["matched_fields"] if best else [],
            "missing_disambiguators": best["missing_disambiguators"] if best else [],
            "conflicts": [], "identification_method": identification_method,
            "matched_identifier": " | ".join(matched_identifiers),
            "identifier_sources": identifier_sources,
            "identifier_source": ('BARCODE_DECODED+LICENSE_OCR' if identification_method == 'BARCODE_AND_LICENSE_EXACT'
                                  else 'BARCODE_DECODED' if identification_method == 'BARCODE_EXACT'
                                  else 'LICENSE_OCR' if identification_method == 'LICENSE_EXACT'
                                  else 'PACKAGE_TEXT_OCR' if winner else 'NONE'),
            "barcode_database_matches": [item for item in identifier_sources if item['source'] == 'BARCODE_DECODED'],
            "license_database_matches": [item for item in identifier_sources if item['source'] == 'LICENSE_OCR'],
            "identifier_corrected": any(bool(item.get("corrected")) for item in observation.get("licenses", [])),
            "identifier_db_match_count": len(all_hit_ids), "identifier_agreement": identifier_agreement,
            "secondary_conflicts": [], "database_query_time_ms": query_ms,
            "matching_compute_time_ms": compute_ms, "decision_time_ms": decision_ms,
        }

    def _score(self, observation, product):
        all_texts = observation.get("texts", [])
        english = observation.get("english", [])
        chinese = observation.get("chinese", [])
        aliases = product.get("aliases", [])
        candidate_dose = product.get("strength_normalized") or ""
        english_names = [product.get("drug_name_en"), product.get("normalized_name_en")]
        english_names += [alias[0] for alias in aliases if len(alias) > 2 and alias[2] == "en"]
        chinese_names = [product.get("drug_name_zh"), product.get("normalized_name_zh")]
        chinese_names += [alias[0] for alias in aliases if len(alias) > 2 and alias[2] == "zh"]

        name_match = _best_text_match(english, [value for value in english_names if value])
        name_line_dose_hint = None
        if (
            name_match["kind"] == "contains"
            and name_line_has_matching_strength(
                name_match.get("evidence"),
                name_match.get("database_value"),
                candidate_dose,
            )
        ):
            name_line_dose_hint = name_match["evidence"]
            name_match = {
                **name_match,
                "kind": "exact",
                "strength_suffix_match": True,
            }
        name_score = _name_points(name_match)
        zh_match = _best_text_match(chinese, [value for value in chinese_names if value], minimum_length=2)
        zh_score = CHINESE_NAME_SCORE if zh_match["kind"] in ("exact", "contains") or zh_match["similarity"] >= 90 else 0.0

        ingredient_values = [item[0] for item in product.get("ingredients", []) if item and item[0]]
        ingredient_match = _best_text_match(all_texts, ingredient_values)
        ingredient_score = INGREDIENT_HIGH_SCORE if ingredient_match["similarity"] >= 88 else (
            INGREDIENT_LOW_SCORE if ingredient_match["similarity"] >= 75 else 0.0)

        detected_doses = observation.get("strengths", [])
        dose_match = bool(candidate_dose) and any(dose_equivalent(value, candidate_dose) for value in detected_doses)
        if dose_match:
            dose_status, dose_score = "match", DOSE_MATCH_SCORE
        elif detected_doses and candidate_dose:
            dose_status, dose_score = "mismatch", DOSE_MISMATCH_PENALTY
        else:
            dose_status, dose_score = "unknown", 0.0
        dose_hint = None
        if dose_status != "match":
            dose_hint = name_line_dose_hint or _name_line_dose_hint(
                all_texts,
                english_names + chinese_names,
                candidate_dose,
            )
            if dose_hint:
                dose_status, dose_score = "match", DOSE_MATCH_SCORE

        form_values = [product.get("dosage_form_en"), product.get("dosage_form_zh"), product.get("release_type")]
        form_match = _best_text_match(all_texts, [value for value in form_values if value], minimum_length=3)
        form_score = DOSAGE_FORM_SCORE if form_match["similarity"] >= 75 else 0.0
        # Package directions such as "dissolve in water before use" are strong
        # positive evidence for an effervescent product even when OCR mangles
        # the English word "Effervescent".  This never penalizes other forms.
        joined_text = " ".join(all_texts).casefold()
        effervescent_direction = (
            ("加水" in joined_text and ("溶" in joined_text or "海" in joined_text))
            or ("dissolve" in joined_text and "water" in joined_text)
        )
        if effervescent_direction and any("effervescent" in normalize_text(value) for value in form_values if value):
            form_score = DOSAGE_FORM_SCORE
            form_match = {"similarity": 100.0, "evidence": "dissolve-in-water instruction",
                          "database_value": product.get("dosage_form_en"), "kind": "semantic"}
        manufacturer_values = [product.get("manufacturer_en"), product.get("manufacturer_zh")]
        manufacturer_match = _best_text_match(all_texts, [value for value in manufacturer_values if value])
        manufacturer_score = MANUFACTURER_SCORE if manufacturer_match["similarity"] >= 80 else 0.0

        barcode_exact = product['drug_id'] in observation.get('_barcode_exact_ids', set())
        contributions = {
            "name_score": name_score, "chinese_name_score": zh_score,
            "ingredient_score": ingredient_score, "dose_score": dose_score,
            "dosage_form_score": form_score, "manufacturer_score": manufacturer_score,
            "barcode_score": BARCODE_SCORE if barcode_exact else 0.0,
        }
        score = sum(contributions.values())
        field_scores = {
            "drug_name_en": name_score, "drug_name_zh": zh_score,
            "ingredient": ingredient_score, "dose": max(0.0, dose_score),
            "dosage_form": form_score, "manufacturer": manufacturer_score,
            "barcode": BARCODE_SCORE if barcode_exact else 0.0,
        }
        matched_fields = [field for field, points in field_scores.items() if points > 0]
        strong = name_match["kind"] in ("exact", "contains") or zh_score == CHINESE_NAME_SCORE
        return {
            "drug_id": product["drug_id"], "folder_name": product.get("folder_name"),
            "score": score, "match_score": score, "matched_fields": matched_fields,
            "name_score": name_score, "chinese_name_score": zh_score,
            "ingredient_score": ingredient_score, "dose_score": dose_score,
            "dosage_form_score": form_score, "manufacturer_score": manufacturer_score,
            "barcode_score": BARCODE_SCORE if barcode_exact else 0.0, "dose_status": dose_status,
            "strong_evidence": strong or barcode_exact, "name_similarity": name_match["similarity"],
            "name_or_ingredient": bool(name_score or zh_score or ingredient_score),
            "evidence_points": score, "observed_weight": 0.0,
            "missing_disambiguators": [field for field, points in field_scores.items() if points <= 0],
            "conflicts": [], "hard_conflict": False,
            "best_evidence": {
                "drug_name_en": name_match, "drug_name_zh": zh_match,
                "ingredient": ingredient_match, "dose": {"status": dose_status,
                    "detected": detected_doses, "database_value": candidate_dose,
                    "name_line_hint": dose_hint},
                "dosage_form": form_match, "manufacturer": manufacturer_match,
            },
            "database_values": {
                "drug_name_en": product.get("drug_name_en"), "drug_name_zh": product.get("drug_name_zh"),
                "ingredients": ingredient_values, "strength": candidate_dose,
                "dosage_forms": [value for value in form_values if value],
                "manufacturers": [value for value in manufacturer_values if value],
            },
        }

    def _lookup_exact_identifiers(self, observation):
        barcodes = observation.get("barcodes", [])
        licenses = observation.get("licenses", [])
        if hasattr(self.repository, "lookup_exact_identifiers"):
            return self.repository.lookup_exact_identifiers(barcodes, licenses)
        products, query_ms = self.repository.fetch_candidates()
        barcode_hits = {str(value): {product["drug_id"] for product in products
                        if any(normalize_barcode(item[0]) == str(value) for item in product.get("barcodes", []))}
                        for value in barcodes}
        license_hits = {}
        for licence in licenses:
            key = (str(licence["kind"]), str(licence["number"]))
            license_hits[key] = {product["drug_id"] for product in products
                if str(product.get("license_number") or "") == key[1]
                and key[0] == str(product.get("license_kind") or "")}
        return {"barcodes": barcode_hits, "licenses": license_hits}, query_ms
