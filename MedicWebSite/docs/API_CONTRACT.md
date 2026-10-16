# MediLens integration contract

The UI currently uses local demonstration data. These versioned endpoints reserve the integration boundary for the production services.

## Web API

- `GET /api/v1/health` — service readiness.
- `GET /api/v1/drugs?q=...` — TFDA-indexed drug search.
- `POST /api/v1/prescriptions/import` — multipart prescription upload; responds with an asynchronous OCR job.
- `GET /api/v1/devices/{deviceId}/status` — server-side proxy to the Pi status endpoint.
- `POST /api/v1/devices/{deviceId}/preview/start` — turn on the selected light and start the low-resolution Camera 1 positioning stream.
- `POST /api/v1/devices/{deviceId}/preview/stop` — stop Camera 1 and turn off controlled lights.
- `GET /api/v1/devices/{deviceId}/preview/stream?camera=1|2` — authenticated server-side MJPEG proxy for the selected camera. Camera 1 is used when the query parameter is omitted.
- `POST /api/v1/devices/{deviceId}/commands` — authenticated server-side proxy. Hardware commands are `set_light`, `capture`, and `shutdown_lights`; inference is intentionally not performed on the Pi.

The tester interface may pass `lightMode` (`white`, `warm`, or visual `uv`), `brightness` (`1..100`), and `sendToServer: false` in a capture payload. When `sendToServer` is false, the Pi saves and returns both images but does not create a MedicServer upload job. The full recognition interface continues to use fixed white light at 85% and leaves `sendToServer` enabled.
- `GET /api/v1/devices/{deviceId}/captures/{captureId}/camera/{cameraId}` — protected proxy for a saved Camera 1 or Camera 2 JPEG.
- `GET /api/v1/devices/{deviceId}/captures/{captureId}/verification` — protected proxy for the Pi's persisted MedicServer job state and final result.

## MedicServer verification API

- Base URL on the current LAN: `http://210.240.160.148:8000`.
- `POST /api/v1/verifications` — multipart form upload. Camera 1 must use field `front_image`; Camera 2 must use `back_image`. Optional fields are `expected_drug_id` and `expected_name`.
- `GET /api/v1/verifications/{verification_id}` — retrieve a stored verification directly from MedicServer.
- MedicServer currently returns the completed verification synchronously with HTTP 201. The Pi performs this request on a background thread so the website can display the photos and a processing state immediately.
- Result outcomes are `MATCH`, `MISMATCH`, `NEEDS_REVIEW`, and `IDENTIFIED`. `NEEDS_REVIEW` must remain visible for human confirmation.

## Raspberry Pi transport

The initial LAN integration uses an authenticated HTTP proxy: browser → website host `210.240.160.148` → Pi `210.240.160.159:5000`. The browser never receives the device token or addresses the Pi command API directly. MQTT remains the recommended later option when the device must cross NAT or an untrusted network.

- Commands: `medilens/devices/{deviceId}/commands`
- Command results: `medilens/devices/{deviceId}/events`
- Heartbeat: `medilens/devices/{deviceId}/status`

Every command has a unique `commandId`, a 30-second expiry, and idempotent handling. The Pi must turn all lights off after capture, on timeout, and on process shutdown.

## Production TODO

1. Add session authentication and role/device authorization.
2. Replace mock storage with PostgreSQL/D1 and encrypted object storage.
3. Connect the TFDA sync job and retain source/update metadata.
4. Add an explicit human-confirmation action for `NEEDS_REVIEW` and `MISMATCH` results.
5. Add audit logs, rate limits, file validation, and device-key rotation.
