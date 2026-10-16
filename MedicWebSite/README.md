# MediGuard Smart Medication Platform

MedicWebSite is the user interface and device proxy layer for MediGuard AI. It provides medication management screens while keeping the Raspberry Pi shared token on the server and proxying camera, lighting, original image, and MedicServer recognition-status requests.

> The project is currently an interactive prototype. The Raspberry Pi capture and MedicServer recognition flow is implemented, but authentication, prescriptions, the medication catalog, and several management datasets still use frontend demonstrations or mock APIs. Production accounts, authorization, and persistence are not yet implemented.

## Implemented Features

- Responsive login screen, sidebar navigation, and dashboard.
- Prescription list, instant search, status filters, medication details, and JSON import.
- Mobile QR code/barcode scanning for prescription import.
- Medication search with ingredients, indications, license information, and precautions.
- Low-bandwidth Camera 1 positioning preview, red center crosshair, and synchronized high-resolution dual-camera capture.
- Same-origin website APIs that proxy the Raspberry Pi without exposing the device token to the browser.
- Original image display, processing state, and fused OCR/YOLO results after capture.
- Dual entry points from one startup command: the full site on port `3000` and a focused tester interface on port `3001`.
- Tester-only local capture mode with selectable light color/brightness and direct browser-folder saving without a MedicServer upload.
- Recognition history, device status, and system settings screens.
- `/api/v1` endpoints for health checks, medication search, prescription import, and device proxy operations.

The following areas remain prototypes:

- Login only changes frontend state; there is no production session or role-based authorization.
- Prescriptions, medications, and most management data come from local demonstration data.
- `GET /api/v1/drugs` uses a small mock catalog.
- `POST /api/v1/prescriptions/import` returns a simulated queued job without storing the file or running OCR.
- `db/schema.ts` does not yet define production application tables.

## Data Flow

```text
Browser
  └─> MedicWebSite /api/v1/devices/... (server-side proxy)
        └─> Raspberry Pi :5000
              ├─> Camera 1 preview
              ├─> Camera 1/2 capture and local storage
              └─> Background front_image/back_image upload to MedicServer :8000
                    └─> Fused OCR + YOLO result
```

The website polls the Pi's `verification.json` for the active capture every two seconds, for up to five minutes. The Raspberry Pi API token exists only in server-side website environment variables.

## Technology and Directory Layout

- React 19, Next.js 16 route conventions, Vinext, and Vite 8.
- Cloudflare Workers and Wrangler for local and production-build runtime support.
- Tailwind CSS 4, shadcn components, and Lucide icons.
- Drizzle ORM is included in the toolchain, but the production schema has not been created.

```text
app/page.tsx          Main single-page application and demonstration data
app/api/v1/           Website APIs and Raspberry Pi server-side proxy
components/ui/        Shared UI components
db/                   Drizzle entry point and schema
docs/                 Website, Raspberry Pi, and MedicServer contracts
examples/             Prescription JSON and other examples
raspberry_pi/         Flask hardware service, environment template, and systemd unit
scripts/              Development, build, Sites, and Wrangler support scripts
```

## Requirements

- Node.js `22.13.0` or later.
- npm; the project includes `package-lock.json`.
- For hardware features, the website host must be able to reach the Raspberry Pi Flask service.
- For complete recognition, the Raspberry Pi must be able to reach the MedicServer verification API.

## Local Development

```powershell
Copy-Item .env.example .env.local
npm install
npm run dev
```

Open either entry point after startup:

- `http://127.0.0.1:3000/` — full MediGuard website. The current login is a demonstration, so entering an email address and password is sufficient.
- `http://127.0.0.1:3001/` — tester interface without login, prescriptions, or medication lookup. It contains the normal recognition flow and a separate local-only capture tool.

In local-only capture mode the Raspberry Pi returns both high-resolution images to the browser with `sendToServer: false`. Chromium-based browsers opened through `localhost` can grant a selected-folder write permission. Other browsers or insecure LAN origins fall back to normal JPEG downloads because browsers do not permit arbitrary folder writes there.

Server-side settings in `.env.local`:

| Variable | Purpose |
| --- | --- |
| `RASPBERRY_PI_BASE_URL` | Raspberry Pi hardware service address, for example `http://210.240.160.159:5000` |
| `RASPBERRY_PI_DEVICE_TOKEN` | A long random value that exactly matches the Pi's `MEDILENS_DEVICE_TOKEN` |
| `MEDIGUARD_ALLOWED_DEV_ORIGINS` | Comma-separated LAN hostnames or IP addresses allowed to load Vinext development assets, for example `210.240.160.148` |

Without a configured token, the demonstration screens remain available, but device proxy endpoints return `503 device_token_not_configured`.

### Allow LAN Clients to Open the Website

`npm run dev` listens on all interfaces by default. LAN clients can open `http://<website-host-IP>:3000` and `http://<website-host-IP>:3001`, provided that the host firewall allows TCP ports 3000 and 3001. Mobile scanning and direct selected-folder writes require HTTPS or a browser-recognized localhost origin; browsers may deny these permissions on a plain HTTP LAN address.

## Complete Hardware and Recognition Setup

1. Follow the [Raspberry Pi deployment guide](raspberry_pi/DEPLOY.md) to start `hardware.py`.
2. Use the same device token in the website's `.env.local` and the Pi's `.env`.
3. Set the Pi's `MEDILENS_WEBSITE_ORIGINS` to both website origins, such as `http://210.240.160.148:3000,http://210.240.160.148:3001`.
4. Set the Pi's `MEDILENS_BACKEND_UPLOAD_URL` to MedicServer, such as `http://210.240.160.148:8000/api/v1/verifications`.
5. Check both the Pi and MedicServer health endpoints before starting positioning and capture from the website.

```bash
curl http://210.240.160.159:5000/api/v1/health
curl http://210.240.160.148:8000/api/v1/health
```

The `210.240.160.x` addresses are examples from the current LAN and must be replaced with the actual host addresses. Camera 1 is always uploaded as `front_image`, and Camera 2 is always uploaded as `back_image`.

## Commands

| Command | Purpose |
| --- | --- |
| `npm run dev` | Start the full website on `0.0.0.0:3000` and tester proxy on `0.0.0.0:3001` |
| `npm run dev:main` | Start only the full website on port `3000` |
| `npm run lint` | Run ESLint |
| `node node_modules\typescript\bin\tsc --noEmit` | Run TypeScript type checking |
| `npm run build` | Create the production build |
| `npm start` | Start the built website on port `3000` and tester proxy on port `3001` |

Run the complete validation and local production startup sequence:

```powershell
npm run lint
node node_modules\typescript\bin\tsc --noEmit
npm run build
npm start
```

`npm run build` must complete successfully before `npm start`.

## Website API

| Method | Path | Status / Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Website service health status |
| `GET` | `/api/v1/drugs?q=...` | Prototype medication search backed by a mock catalog |
| `POST` | `/api/v1/prescriptions/import` | Prototype import endpoint that returns a simulated queued job |
| `GET` | `/api/v1/devices/{deviceId}/status` | Proxy Raspberry Pi device status |
| `POST` | `/api/v1/devices/{deviceId}/preview/start` | Turn on the lights and start the Camera 1 preview |
| `POST` | `/api/v1/devices/{deviceId}/preview/stop` | Stop the preview and turn off controlled lights |
| `GET` | `/api/v1/devices/{deviceId}/preview/stream?camera=1|2` | Proxy Camera 1 or Camera 2 MJPEG preview; Camera 1 is the default |
| `POST` | `/api/v1/devices/{deviceId}/commands` | Proxy `set_light`, `capture`, and `shutdown_lights` commands |
| `GET` | `/api/v1/devices/{deviceId}/captures/{captureId}/camera/{cameraId}` | Proxy a saved Camera 1 or Camera 2 JPEG |
| `GET` | `/api/v1/devices/{deviceId}/captures/{captureId}/verification` | Proxy recognition status and results for a capture |

See the [API contract](docs/API_CONTRACT.md) for complete request/response details and security boundaries. See the [prescription example](examples/sample-prescription.json) for the desktop JSON import format.

## Next Steps

1. Add production sessions, roles, and device authorization.
2. Create user, device, prescription, medication, image, and audit tables.
3. Connect TFDA synchronization and a real prescription OCR job queue.
4. Add explicit human review and correction flows for `NEEDS_REVIEW` and `MISMATCH`.
5. Add encryption, retention periods, deletion policies, rate limits, and key rotation for prescriptions, images, and device secrets.

