# MedicWebSite integration contract

Base URL is configured server-side, for example `MEDIC_SERVER_URL=http://127.0.0.1:8000`. The browser should call a same-origin `MedicWebSite` proxy route so the internal service address does not leak into client code.

## `POST /api/v1/verifications`

Content type: `multipart/form-data`.

| Field | Required | Meaning |
| --- | --- | --- |
| `front_image` | yes | Front/cam0 image: JPEG, PNG, WEBP, TIFF, or BMP; default maximum 20MB |
| `back_image` | yes | Back/cam1 image with the same constraints |
| `expected_drug_id` | no | Existing `drug_products.drug_id`; takes precedence over `expected_name` |
| `expected_name` | no | Expected canonical folder/product name |

The endpoint is synchronous because the current UI begins one identification at a time. Successful response is HTTP 201:

```json
{
  "verification_id": "uuid",
  "status": "COMPLETED",
  "outcome": "MATCH",
  "expected_drug_id": 42,
  "expected_name": "Concor 5mg",
  "ocr_result": { "status": "MATCHED" },
  "yolo_result": { "prediction": "Concor 5mg", "confidence": 0.98 },
  "fused_result": {
    "final_prediction": "Concor 5mg",
    "final_confidence": 0.98,
    "decision_source": "OCR_PRIMARY_YOLO_AGREEMENT",
    "decision_reason": "Confirmed OCR agrees with YOLO."
  }
}
```

`outcome` values:

- `MATCH`: identified class equals the supplied expected drug.
- `MISMATCH`: a reliable class was identified, but it differs from the expected drug.
- `NEEDS_REVIEW`: evidence was insufficient or OCR/YOLO conflict policy returned unknown.
- `IDENTIFIED`: a reliable class was identified without an expected drug.

The UI must not turn `NEEDS_REVIEW` into an automatic match. Keep the decision source, candidates and both images visible to a human reviewer.

## OOD pipeline (v2)

Every request runs Pair-YOLO/OOD before OCR, including exact identifier matches. The existing request fields, HTTP 201 response envelope and `outcome` values remain supported.

`yolo_result` additionally contains `ood_status`, `ood_decision` (`PASS`/`REJECT`), `ood_score`, `ood_threshold` (`0.7981438636779785`), `ood_method` (`cosine_knn1`), `ood_nearest_pair_id`, `ood_nearest_label`, timing fields and `pair_forward_count` (`1`). Classification and OOD share that single forward.

`fused_result` retains `final_prediction`, `final_confidence`, `decision_source`, `decision_reason` and adds:

| Field | Values / meaning |
| --- | --- |
| `recognition_status` | `KNOWN_DRUG`, `NON_DRUG`, `UNKNOWN_DRUG`, `UNRECOGNIZED` |
| `ood_gate_final_decision` | `PASS`, `REJECT`, `OVERRIDDEN` |
| `ood_override_status` | `NOT_APPLICABLE`, `NOT_OVERRIDDEN`, `OVERRIDDEN_BY_OCR_YOLO_AGREEMENT` |
| `ood_reject_override` | On raw OOD rejection: OCR/YOLO names, confidence, override threshold, allowed flag and reason |

`score < threshold` is a raw OOD rejection; equality passes. A raw rejection still runs OCR/database. It can be overridden only when OCR status is `EXACT_ID`, `MATCHED` or `NAME_ONLY_UNIQUE`, its canonical product agrees with Pair-YOLO, and YOLO confidence is at least `FINAL_THRESHOLD` (default `0.95`). Otherwise the final name is `unknown`, recognition status is `NON_DRUG` and outcome is `NEEDS_REVIEW`.

On OOD pass, a reliable barcode/license absent from the catalog produces `UNKNOWN_DRUG`/`NEEDS_REVIEW`, even when YOLO is confident. Remaining cases use upstream `YOLO_STAGE.hybrid_decision` with cached classification. Missing/invalid OOD evidence, worker errors and OCR/database errors fail the job with HTTP 500; they cannot fall back to an exact OCR match or a YOLO-only match. OOD fields persist inside the existing JSONB result columns and result JSON file; no database migration is required.

## History

`GET /api/v1/verifications?limit=50&offset=0` returns newest-first summaries. `GET /api/v1/verifications/{id}` returns the stored job, image metadata, and complete JSON result. Each image metadata object includes a same-service `url`.

## Errors

- 413: image exceeds configured limit.
- 415: unsupported media type.
- 422: invalid image or unknown `expected_drug_id`.
- 500: inference or persistence failure; if the job row exists, it is marked `FAILED`.

