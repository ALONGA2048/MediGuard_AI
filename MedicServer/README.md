# MedicServer

[繁體中文](README.zh-TW.md) | **English**

MedicServer is the medication recognition backend for MediGuard AI. It accepts front/back images, runs one Pair-YOLO forward with a calibrated cosine kNN1 OOD gate, then PaddleOCR/barcode/database recognition and guarded consensus. It stores the complete evidence and final result. The implementation is synchronized with `drug-project` commit `9987e9347360a326cbde4c905ba918001eb28f5c`.

See [the flow comparison and migration notes](docs/OOD_MIGRATION.md) and [the complete source inventory](docs/drug-project-file-inventory.csv).

## Features and Service Architecture

Docker Compose creates three services:

| Service | External Address | Purpose |
| --- | --- | --- |
| `ocr` | `http://localhost:8000` | Public FastAPI service for file validation, OCR/barcode recognition, YOLO requests, result fusion, and persistence |
| `yolo` | Docker network only, `:8001` | Loads the 119-class Pair-YOLO and 1046 × 256 OOD bank; returns classification and OOD from one forward, with `front -> cam0` and `back -> cam1` |
| `database` | `localhost:55432` | PostgreSQL 18; imports the medication catalog and verification schema when an empty database is first initialized |

Main capabilities:

- Accepts front and back images in JPEG, PNG, WEBP, TIFF, or BMP format, with a default per-file limit of 20 MB.
- Combines OCR candidates, barcode results, and YOLO confidence scores into a final decision.
- Returns `MATCH`, `MISMATCH`, or `NEEDS_REVIEW` when an expected medication is supplied.
- Returns `IDENTIFIED` or `NEEDS_REVIEW` when no expected medication is supplied.
- Provides endpoints for verification history, individual results, and original images.
- Stores data in PostgreSQL, local JSON result files, and original image directories.

## Directory Layout

```text
database/init/       PostgreSQL seed data and verification schema
models/              Paired-YOLO and base YOLO weights with SHA-256 checksums
ocr_service/         Public API, OCR, result fusion, and persistence logic
yolo_service/        Internal paired-YOLO inference service
                    legacy/ood_filter/ contains the calibrated config and bank
tests/               Fusion decision unit tests that do not load the models
data/postgres/       PostgreSQL data directory
data/uploads/        Original front and back images for each verification
data/results/        Complete JSON result for each verification
data/paddle/         PaddleOCR model cache created on first startup
```

## Requirements

- Docker Desktop or Docker Engine.
- Docker Compose v2, invoked as `docker compose`.
- Network access during the first image build and the first PaddleOCR model download.
- GPU mode additionally requires an NVIDIA GPU, compatible drivers, and a working Docker GPU runtime.

## CPU Quick Start

```powershell
Copy-Item .env.example .env
# Edit .env and replace POSTGRES_PASSWORD before use
docker compose up -d --build
docker compose ps
curl.exe http://localhost:8000/api/v1/health
```

Swagger UI is available at `http://localhost:8000/docs`. To follow the service logs:

```powershell
docker compose logs -f ocr yolo database
```

On the first startup, the OCR service downloads PaddleOCR models into `data/paddle/`, so it may take longer for the health check to become ready. The CPU image applies a version-content-checked compatibility patch to PaddleOCR 2.7.3 and disables MKL-DNN to avoid `SIGILL / exit 132` on some Docker or virtualized CPUs.

## Environment Configuration

Use `.env.example` as the configuration template:

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_DB` | `medicine_ocr` | Database name |
| `POSTGRES_USER` | `medic` | Database user |
| `POSTGRES_PASSWORD` | Example value | Replace with a long random password before use |
| `POSTGRES_PORT` | `55432` | PostgreSQL port published on the host |
| `OCR_BIND_HOST` | `0.0.0.0` | OCR API bind interface; use `127.0.0.1` for local-only access |
| `OCR_PORT` | `8000` | OCR API host port |
| `OCR_DEVICE` | `cpu` | OCR device for the standard Compose stack |
| `YOLO_DEVICE` | `cpu` | YOLO inference device |
| `MAX_UPLOAD_MB` | `20` | Maximum size of each uploaded image |
| `FINAL_THRESHOLD` | `0.95` | Fusion decision threshold |
| `OCR_BASIC_SCORE` | `50.0` | Basic OCR score threshold |
| `OCR_TIE_GAP` | `8.0` | OCR candidate tie-gap threshold |
| `OCR_SUPPORTED_YOLO_THRESHOLD` | `0.60` | Passed to the upstream hybrid decision function |
| `YOLO_GPU_DEVICE` | `cuda:0` | Pair-YOLO/OOD device in GPU Compose mode |
| `OCR_GPU_DEVICE` | `0` | PaddleOCR device in GPU Compose mode |

After changing environment values, rebuild and restart with `docker compose up -d --build`.

## Verification API

Submit an image pair:

```powershell
curl.exe -X POST http://localhost:8000/api/v1/verifications `
  -F "front_image=@C:\path\front.jpg" `
  -F "back_image=@C:\path\back.jpg" `
  -F "expected_name=Concor 5mg"
```

Both `expected_name` and `expected_drug_id` are optional. When both are provided, `expected_drug_id` takes precedence.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Check OCR, YOLO, database, and compute-device status |
| `POST` | `/api/v1/verifications` | Upload front and back images and synchronously receive a recognition result |
| `GET` | `/api/v1/verifications?limit=50&offset=0` | List verification summaries from newest to oldest |
| `GET` | `/api/v1/verifications/{verification_id}` | Retrieve a complete result and image metadata |
| `GET` | `/api/v1/verifications/{verification_id}/images/front` | Retrieve the original front image |
| `GET` | `/api/v1/verifications/{verification_id}/images/back` | Retrieve the original back image |

See the [API contract](docs/API_CONTRACT.md) for complete fields, responses, and error codes. `NEEDS_REVIEW` indicates insufficient or conflicting evidence and must not be automatically treated as a successful match.

## LAN Access

Even with `OCR_BIND_HOST=0.0.0.0`, the host firewall must allow the Raspberry Pi to access TCP port 8000. The following Windows example is scoped to the current `210.240.160.0/24` network. Run it from an administrator PowerShell and change `RemoteAddress` when deploying on a different network:

```powershell
New-NetFirewallRule -DisplayName "MedicServer OCR API (LAN 8000)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress 210.240.160.0/24 -Profile Any
```

Test connectivity from the Raspberry Pi:

```bash
curl http://210.240.160.159:8000/api/v1/health
```

Then configure the Pi's `MEDILENS_BACKEND_UPLOAD_URL` as:

```text
http://210.240.160.159:8000/api/v1/verifications
```

The IP address above is an example from the current environment. Replace it with the actual backend host address.

## Pair-YOLO/OOD and PaddleOCR GPU Mode

The GPU override uses PaddlePaddle 2.6.2, CUDA 11.2, and cuDNN 8.2. On Windows, first confirm that Docker Desktop uses the WSL2 backend and that a container can see the NVIDIA GPU:

```powershell
docker run --rm --gpus all nvidia/cuda:11.2.2-base-ubuntu20.04 nvidia-smi
```

Build and start both GPU inference services (Pair-YOLO uses PyTorch 2.7.1 / CUDA 11.8 wheels):

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.gpu.yml logs -f ocr
curl.exe http://localhost:8000/api/v1/health
```

The public health response should contain `ocr_device: "cuda:0"`, `paddle_cuda: true`, and at least one `cuda_devices` entry. Use `OCR_GPU_DEVICE` and `YOLO_GPU_DEVICE` to select each container's visible GPU index. The YOLO worker's `/health` includes device, calibrated threshold, artifact hashes and bank dimensions. Both services reserve an NVIDIA GPU in this override. For GPU OCR with CPU YOLO, leave out the `yolo` override or use a separate local override with the CPU Dockerfile and device.

Return to CPU mode:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml down
docker compose up -d --build
```

## Testing and Maintenance

Run the fusion and HTTP integration tests without loading the models (HTTP model/database boundaries are mocked):

```powershell
python -m pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
python tests/run_upstream_core.py
python tools/verify_deployment.py
```

These checks require the CPU service dependencies plus `PyYAML` for the offline deployment checker. Core regressions do not load Torch, PaddleOCR models, or a database. The full original suite is retained in `tests/upstream/`; OCR, image and batch tests additionally need their runtime dependencies. No Docker/GPU runtime test is implied by the offline checks.

Check that the models and seed data have not been replaced unexpectedly:

```powershell
Get-FileHash .\models\best_pair.pt -Algorithm SHA256
Get-FileHash .\models\yolo_best.pt -Algorithm SHA256
Get-Content .\models\SHA256SUMS
```

Stop the services:

```powershell
docker compose down
```

Do not add `-v` and do not delete `data/` unless data loss is intended. Doing so may remove PostgreSQL data, uploaded images, results, or the model cache. Files under `database/init/*.sql` run only when an empty PostgreSQL data directory is initialized; editing them does not automatically migrate an existing database.

