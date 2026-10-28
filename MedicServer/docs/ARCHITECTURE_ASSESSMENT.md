# pythonOCR assessment and container design

Historical assessment of the initial Server migration. The active production flow was updated on 2026-10-24 from `drug-project`; see [OOD_MIGRATION.md](OOD_MIGRATION.md) for current ordering, models, consensus and GPU deployment. Statements below about skipped YOLO, model paths and inactive settings describe the earlier implementation.

## Existing pipeline

The reviewed implementation is a two-stage batch pipeline:

1. `OCR_AND_YOLO.py` starts `OCR_STAGE.py`, waits for it to exit, then starts `YOLO_STAGE.py`. The process split avoids simultaneously retaining Paddle and PyTorch GPU allocations.
2. `ocr.py` performs package ROI extraction, deskew/orientation selection, Chinese and English PaddleOCR passes, barcode/QR decoding, and an expensive angle fallback only after an unsuccessful database decision.
3. `drug_matching/` normalizes names, strengths, dosage forms, manufacturers, licenses and barcodes. `DrugRepository` loads PostgreSQL candidates and weights; `DrugMatcher` returns exact-ID, unique-name, matched, ambiguous, conflict, or unknown states.
4. `function/pair_function.py` loads the ordered paired model. Both images share a YOLO classifier; cam0/cam1 features are concatenated and passed through a learned fusion head. Camera order is part of the checkpoint contract.
5. `YOLO_STAGE.py` applies conservative fusion: exact barcode/license wins without YOLO; weak OCR requires YOLO >= 0.95; ambiguous OCR allows YOLO only within OCR candidates; strong OCR normally wins unless a guarded high-confidence conflict or dosage conflict requires review.

## Repository inventory

The source folder contains approximately 42,994 virtual-environment files (about 8.0GB), 3,476 test image files (about 3.4GB), 1,366 historical OCR report files (about 551MB), a 455MB local Paddle wheel, two trained model files, 21 primary Python source/test files, and generated reports/previews. `docs/pythonOCR-file-inventory.csv` is the complete metadata inventory captured during this migration.

Only runtime code and the two required weights were copied. The venv, test corpus, caches, generated reports, Word QA material and training artifacts are not Docker build inputs.

## Findings

- Good: OCR/database matching and paired visual classification are already separated conceptually; exact identifiers and dosage conflicts receive conservative treatment; query values are parameterized; diagnostic timing and evidence are rich.
- Good: the 119 database products match the checkpoint's 119 classes.
- The newest stored batch report contains 1,738 pairs: 1,734 correct, zero wrong and four unknown at the 0.95 threshold (99.77% accepted/correct over that internal corpus). This is useful regression evidence, but it is not an independent or prospective clinical validation set and must not be presented as real-world accuracy.
- Risk fixed here: the legacy repository had a plaintext default PostgreSQL password. The server copy now requires `PGPASSWORD`.
- Configuration defect avoided here: `YOLO_STAGE.py` has a direct-run default base-model path under `runs/classify/train-17`, while the actual weight is under `train-17/weights`; the batch launcher happens to override it. Docker uses an explicit `/models/yolo_best.pt` path.
- Dead configuration: `ocr_supported_yolo_threshold` is parsed and reported by the batch program but is not used by `hybrid_decision`. It was deliberately not exposed as an active server setting.
- Reproducibility gap: the checked virtual environment does not contain pytest even though four pytest-style regression files exist. The new pure fusion tests use the standard library and run without adding a test framework.
- Dependency hygiene gap: the checked environment contains three OpenCV distributions simultaneously (`opencv-python`, `opencv-contrib-python`, and `opencv-python-headless`). The OCR image installs only the headless runtime.
- Container compatibility fix: PaddleOCR 2.7.3 parses `ir_optim` but hard-codes `switch_ir_optim(True)` during predictor creation. The OCR image applies an exact, fail-closed source patch and both engines request `ir_optim=False`, preventing the observed `SelfAttentionFusePass` illegal-instruction restart loop on the deployment CPU.
- Risk contained: model objects are global and not guaranteed thread-safe. Each worker uses one process and serializes inference with a lock.
- Risk contained: uploaded filenames are never used as storage paths; content type, size and decodability are validated, and files receive UUID-scoped names.
- Operational limitation: the original environment uses Windows CUDA-specific wheels. The portable Docker baseline is CPU. GPU deployment requires tested NVIDIA base images and matching Paddle/PyTorch CUDA builds.
- Operational limitation: PaddleOCR 2.x downloads models on first boot. Its cache is bind-mounted under `MedicServer/data/paddle` for repeatable restarts.
- Product limitation: this is identification/validation support, not autonomous clinical authorization. Unknown/conflicting results remain `NEEDS_REVIEW`.

## New three-container boundary

`ocr` is the public orchestrator and owns input validation, OCR, database matching, result fusion and persistence. `yolo` is internal-only and owns PyTorch/Ultralytics plus the paired checkpoint. `database` owns both the imported medicine catalog and new immutable verification evidence. Persistent bind mounts keep all mutable data under `MedicServer/data`.

The copied OCR and paired-YOLO runtime files were hash-identical to their source at migration time, except `DrugRepository`, where only the hard-coded password fallback was intentionally removed. Model and seed hashes are recorded in `models/SHA256SUMS`.
