# MediGuard AI

MediGuard AI is a smart medication identification prototype that combines a web interface, Raspberry Pi dual-camera and lighting controls, and an OCR/YOLO medication recognition backend in one workspace.

> This project is currently a development prototype. The hardware capture and recognition flow can be integrated end to end, but website authentication, prescriptions, medication data, and several management screens still use demonstration data. Do not treat it as a production medical system.

## Project Structure

| Directory | Purpose | Main Technologies | Documentation |
| --- | --- | --- | --- |
| `MedicServer/` | Accepts front and back medication images, combines PaddleOCR, barcode, and paired-YOLO results, and stores the outcome | FastAPI, PostgreSQL, Docker Compose | [MedicServer README](MedicServer/README.md) |
| `MedicWebSite/` | Provides the user interface and proxies Raspberry Pi controls, images, and recognition status | React 19, Next.js 16 APIs, Vinext, Vite, Cloudflare Workers | [MedicWebSite README](MedicWebSite/README.md) |

The recognition data flow is:

```text
Browser
  └─> MedicWebSite (same-origin API; device token stays on the server)
        └─> Raspberry Pi (lighting, Camera 1 preview, Camera 1/2 capture)
              └─> MedicServer (front_image + back_image)
                    ├─> PaddleOCR and barcode recognition
                    ├─> paired-YOLO classification
                    └─> PostgreSQL + JSON results + original images
```

Camera 1 maps to `front_image`, and Camera 2 maps to `back_image`. The Raspberry Pi uploads both images in the background, while the website polls the fused MedicServer result through the Pi proxy.

## Main Features

- Front/back medication recognition using OCR, barcodes, and a 119-class paired-YOLO model.
- Optional expected-medication verification with `MATCH`, `MISMATCH`, or `NEEDS_REVIEW`; requests without an expected medication return `IDENTIFIED` or `NEEDS_REVIEW`.
- Persistent original images, complete JSON results, and PostgreSQL verification records.
- Website screens for prescriptions, medication lookup, recognition history, device status, and system settings.
- Server-side proxy for Raspberry Pi lighting, preview, dual-camera capture, saved images, and recognition status APIs.
- Mobile QR code/barcode scanning and desktop JSON prescription import.

## Requirements

- Docker Desktop or Docker Engine with Docker Compose v2.
- Node.js `22.13.0` or later and npm.
- The complete hardware flow also requires a Raspberry Pi, two cameras, and a WS2812B LED strip. The website demonstration can be viewed without this hardware.
- PaddleOCR GPU mode additionally requires an NVIDIA GPU, a working WSL2/Docker GPU runtime, and compatible drivers.

## Quick Start

Run the following commands from the directory containing this README.

### 1. Start the Recognition Backend

```powershell
Set-Location .\MedicServer
Copy-Item .env.example .env
# Edit .env and replace POSTGRES_PASSWORD with a long random password
docker compose up -d --build
curl.exe http://localhost:8000/api/v1/health
```

Default service addresses:

- OCR/verification API: `http://localhost:8000`
- Swagger UI: `http://localhost:8000/docs`
- PostgreSQL: `localhost:55432`
- YOLO worker: port `8001`, available only inside the Docker network

On the first startup, PaddleOCR downloads its models into `MedicServer/data/paddle/`, so initialization takes longer than subsequent starts.

### 2. Start the Website

Open another PowerShell window:

```powershell
Set-Location .\MedicWebSite
Copy-Item .env.example .env.local
# To use hardware features, set the Raspberry Pi address and shared token in .env.local
npm install
npm run dev
```

The website command opens two LAN-accessible entry points:

- `http://127.0.0.1:3000/` — the full MediGuard website.
- `http://127.0.0.1:3001/` — the tester interface for recognition and local-only hardware capture.

Authentication on port 3000 is currently a frontend demonstration. Port 3001 intentionally has no login, prescription, or medication-catalog screens.

### 3. Connect the Raspberry Pi (Optional)

The Raspberry Pi must run `MedicWebSite/raspberry_pi/hardware.py` and satisfy these requirements:

1. The Pi's `MEDILENS_DEVICE_TOKEN` must exactly match the website host's `RASPBERRY_PI_DEVICE_TOKEN`.
2. The Pi's `MEDILENS_BACKEND_UPLOAD_URL` must point to `http://<backend-host>:8000/api/v1/verifications`.
3. MedicServer must use `OCR_BIND_HOST=0.0.0.0`, and the host firewall must allow the Pi to access TCP port 8000.

See the [Raspberry Pi deployment guide](MedicWebSite/raspberry_pi/DEPLOY.md) for installation, camera, LED strip, and systemd configuration. The `210.240.160.x` addresses in the documentation are examples from the current LAN and must be replaced when deploying to another network.

## Build and Verification

Website:

```powershell
Set-Location .\MedicWebSite
npm run lint
node node_modules\typescript\bin\tsc --noEmit
npm run build
npm start
```

`npm run build` creates the production build. `npm start` launches the built application through the local Wrangler runtime on `127.0.0.1`.

Backend images and unit tests:

```powershell
Set-Location .\MedicServer
docker compose build
python -m unittest discover -s tests -v
```

The unit tests cover fusion decisions without loading the large models. A full service check should also start the Compose stack, check the health endpoint, and submit a front/back image pair.

## GPU Mode

After confirming that containers can access the NVIDIA GPU, start the PaddleOCR GPU override:

```powershell
Set-Location .\MedicServer
docker run --rm --gpus all nvidia/cuda:11.2.2-base-ubuntu20.04 nvidia-smi
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
curl.exe http://localhost:8000/api/v1/health
```

The health response should report `ocr_device: "cuda:0"`, `paddle_cuda: true`, and at least one `cuda_devices` entry. The GPU override currently applies only to the OCR container; YOLO continues to use the standard Compose configuration.

## Shutdown and Data Safety

```powershell
Set-Location .\MedicServer
docker compose down
```

Do not add `-v` and do not delete `MedicServer/data/` unless data loss is intended. That directory stores PostgreSQL data, original images, the PaddleOCR model cache, and recognition results. Stop the website development server with `Ctrl+C` in its terminal.

## Additional Documentation

- [MedicServer API contract](MedicServer/docs/API_CONTRACT.md)
- [Website and hardware API contract](MedicWebSite/docs/API_CONTRACT.md)
- [Raspberry Pi deployment guide](MedicWebSite/raspberry_pi/DEPLOY.md)
- [Prescription JSON example](MedicWebSite/examples/sample-prescription.json)

