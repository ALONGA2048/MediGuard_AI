#!/usr/bin/env python3
"""MediLens Raspberry Pi hardware service.

Hardware currently expected:
- Camera 1: /dev/video0 (Full HD source + low-bandwidth positioning stream)
- Camera 2: /dev/video2 (Full HD paired capture)
- WS2812B: GPIO18, indexes 0..64

LED indexes 16..31 are reserved at a configured fixed RGB value. Normal light
commands, shutdown, and failure cleanup never alter that reserved value.
"""

from __future__ import annotations

import atexit
import hmac
import json
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
from flask import Flask, Response, jsonify, request, send_file, stream_with_context
from rpi_ws281x import Color, PixelStrip


CURRENT_DIR = Path(__file__).resolve().parent
CAPTURE_DIR = Path(os.getenv("MEDILENS_CAPTURE_DIR", str(CURRENT_DIR / "captures")))
BACKEND_UPLOAD_URL = os.getenv("MEDILENS_BACKEND_UPLOAD_URL", "").strip()
BACKEND_UPLOAD_TOKEN = os.getenv("MEDILENS_BACKEND_UPLOAD_TOKEN", "").strip()

# Network: website/server 210.240.160.148 -> Raspberry Pi 210.240.160.159:5000
LISTEN_HOST = os.getenv("MEDILENS_LISTEN_HOST", "0.0.0.0")
LISTEN_PORT = int(os.getenv("MEDILENS_LISTEN_PORT", "5000"))
WEBSITE_ORIGINS = {
    origin.strip()
    for origin in os.getenv(
        "MEDILENS_WEBSITE_ORIGINS",
        os.getenv(
            "MEDILENS_WEBSITE_ORIGIN",
            "http://210.240.160.148:3000,http://210.240.160.148:3001",
        ),
    ).split(",")
    if origin.strip()
}
DEVICE_TOKEN = os.getenv("MEDILENS_DEVICE_TOKEN", "")

CAMERA_1_INDEX = int(os.getenv("MEDILENS_CAMERA_1", "0"))
CAMERA_2_INDEX = int(os.getenv("MEDILENS_CAMERA_2", "2"))
CAMERA_1_FOCUS = float(os.getenv("MEDILENS_CAMERA_1_FOCUS", "340"))
CAMERA_2_FOCUS = float(os.getenv("MEDILENS_CAMERA_2_FOCUS", "0"))
PREVIEW_WIDTH = int(os.getenv("MEDILENS_PREVIEW_WIDTH", "960"))
PREVIEW_HEIGHT = int(os.getenv("MEDILENS_PREVIEW_HEIGHT", "540"))
PREVIEW_FPS = int(os.getenv("MEDILENS_PREVIEW_FPS", "5"))
STREAM_JPEG_QUALITY = int(os.getenv("MEDILENS_PREVIEW_JPEG_QUALITY", "75"))
CAPTURE_WIDTH = int(os.getenv("MEDILENS_CAPTURE_WIDTH", "1920"))
CAPTURE_HEIGHT = int(os.getenv("MEDILENS_CAPTURE_HEIGHT", "1080"))
CAPTURE_FPS = int(os.getenv("MEDILENS_CAPTURE_FPS", "30"))
CAPTURE_SETTLE_SECONDS = 1.0
CAPTURE_JPEG_QUALITY = 100
FIXED_LIGHT_MODE = "white"
FIXED_LIGHT_BRIGHTNESS = 85

# Highest requested index is 64, so the strip has 65 addressable pixels.
LED_COUNT = 65
LED_PIN = 18
LED_FREQ_HZ = 800_000
LED_DMA = 10
LED_INVERT = False
LED_CHANNEL = 0
LED_DRIVER_BRIGHTNESS = 255


def _parse_rgb(value: str) -> tuple[int, int, int]:
    parts = tuple(int(part.strip()) for part in value.split(","))
    if len(parts) != 3 or any(part < 0 or part > 255 for part in parts):
        raise ValueError("MEDILENS_RESERVED_LED_RGB must be R,G,B with values 0..255")
    return parts

CONTROLLED_LED_RANGES = (
    range(0, 16),     # 0..15
    range(32, 49),    # 32..48
    range(49, 65),    # 49..64
)
CONTROLLED_LED_INDEXES = tuple(index for led_range in CONTROLLED_LED_RANGES for index in led_range)
RESERVED_LED_INDEXES = tuple(range(16, 32))
RESERVED_LED_RGB = _parse_rgb(os.getenv("MEDILENS_RESERVED_LED_RGB", "0,0,0"))

LIGHT_COLORS: dict[str, tuple[int, int, int]] = {
    "white": (255, 255, 255),
    "warm": (255, 164, 82),
    # A WS2812B is not a true UV source. This is only a violet visual mode.
    "uv": (105, 35, 255),
}

app = Flask(__name__)
camera_lock = threading.RLock()
capture_lock = threading.Lock()
led_lock = threading.RLock()
verification_state_lock = threading.RLock()
CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

strip = PixelStrip(
    LED_COUNT,
    LED_PIN,
    LED_FREQ_HZ,
    LED_DMA,
    LED_INVERT,
    LED_DRIVER_BRIGHTNESS,
    LED_CHANNEL,
)
strip.begin()

# WS2812B pixels cannot be read back. Seed the library's shadow buffer with the
# fixed middle-zone color so every later strip.show() keeps 16..31 consistent.
for reserved_index in RESERVED_LED_INDEXES:
    strip.setPixelColor(reserved_index, Color(*RESERVED_LED_RGB))

light_state: dict[str, Any] = {"enabled": False, "mode": "off", "brightness": 0}


def _scaled_color(mode: str, brightness: int) -> Color:
    if mode not in LIGHT_COLORS:
        raise ValueError(f"Unsupported light mode: {mode}")
    brightness = max(0, min(100, int(brightness)))
    scale = brightness / 100.0
    red, green, blue = LIGHT_COLORS[mode]
    return Color(round(red * scale), round(green * scale), round(blue * scale))


def set_controlled_lights(mode: str, brightness: int = 80) -> dict[str, Any]:
    """Set only allowed LED indexes. Reserved indexes 16..31 remain untouched."""
    normalized_mode = mode.strip().lower()
    if normalized_mode == "off" or int(brightness) <= 0:
        return turn_controlled_lights_off()

    brightness = max(1, min(100, int(brightness)))
    color = _scaled_color(normalized_mode, brightness)
    with led_lock:
        for index in CONTROLLED_LED_INDEXES:
            strip.setPixelColor(index, color)
        strip.show()
        light_state.update(enabled=True, mode=normalized_mode, brightness=brightness)
    print(f"[LED] {normalized_mode.upper()} {brightness}% indexes={CONTROLLED_LED_INDEXES}")
    return dict(light_state)


def requested_light_settings(payload: dict[str, Any]) -> tuple[str, int]:
    mode = str(payload.get("lightMode") or FIXED_LIGHT_MODE).strip().lower()
    if mode not in LIGHT_COLORS:
        raise ValueError(f"Unsupported light mode: {mode}")
    try:
        brightness = int(payload.get("brightness", FIXED_LIGHT_BRIGHTNESS))
    except (TypeError, ValueError) as error:
        raise ValueError("brightness must be an integer from 1 to 100") from error
    return mode, max(1, min(100, brightness))


def turn_controlled_lights_off() -> dict[str, Any]:
    """Turn off controlled LEDs without modifying the reserved middle 16 LEDs."""
    with led_lock:
        for index in CONTROLLED_LED_INDEXES:
            strip.setPixelColor(index, Color(0, 0, 0))
        strip.show()
        light_state.update(enabled=False, mode="off", brightness=0)
    print("[LED] OFF controlled indexes only; 16..31 preserved")
    return dict(light_state)


def open_camera(index: int, width: int, height: int, fps: int | None = None):
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    if not cap.isOpened():
        return cap
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps is not None:
        cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    print(f"[Camera] /dev/video{index}: {actual_width}x{actual_height} @ {actual_fps:.1f} FPS")
    return cap


def apply_fixed_focus(cap, camera_id: int, focus: float):
    """Apply the fixed focus values used by yolo_classification/ocrTest.py."""
    autofocus_ok = bool(cap.set(cv2.CAP_PROP_AUTOFOCUS, 0))
    focus_ok = bool(cap.set(cv2.CAP_PROP_FOCUS, focus))
    actual_focus = cap.get(cv2.CAP_PROP_FOCUS)
    print(
        f"[Focus] camera={camera_id} requested={focus:g} actual={actual_focus:g} "
        f"autofocus_off={autofocus_ok} focus_set={focus_ok}"
    )


class CameraRig:
    """Keep both Full HD cameras open and capture them as one synchronized pair."""

    def __init__(self):
        self.caps: dict[int, Any] = {}
        self.active = False
        self.preview_frames: dict[int, Any] = {}
        self.thread: threading.Thread | None = None
        self.frame_lock = threading.Lock()
        self.io_lock = threading.Lock()
        self.capture_requested = threading.Event()

    def start(self) -> bool:
        if self.active:
            return True
        opened: dict[int, Any] = {}
        camera_settings = (
            (1, CAMERA_1_INDEX, CAMERA_1_FOCUS),
            (2, CAMERA_2_INDEX, CAMERA_2_FOCUS),
        )
        for camera_id, index, focus in camera_settings:
            cap = open_camera(index, CAPTURE_WIDTH, CAPTURE_HEIGHT, CAPTURE_FPS)
            if not cap.isOpened():
                cap.release()
                for opened_cap in opened.values():
                    opened_cap.release()
                print(f"[Camera] camera={camera_id} /dev/video{index} open failed")
                return False
            apply_fixed_focus(cap, camera_id, focus)
            opened[camera_id] = cap
        self.caps = opened
        self.active = True
        self.preview_frames = {}
        self.thread = threading.Thread(target=self._reader, daemon=True, name="camera-rig-preview")
        self.thread.start()
        print("[Camera] Full HD pair started")
        return True

    def _reader(self):
        while self.active:
            if self.capture_requested.is_set():
                time.sleep(0.005)
                continue
            frames = self._grab_pair(raise_on_failure=False)
            if frames:
                with self.frame_lock:
                    self.preview_frames = frames

    def get_frame(self, camera_id: int = 1):
        with self.frame_lock:
            frame = self.preview_frames.get(camera_id)
            return None if frame is None else frame.copy()

    def _grab_pair(self, raise_on_failure: bool) -> dict[int, Any]:
        with self.io_lock:
            if not self.active or len(self.caps) != 2:
                if raise_on_failure:
                    raise RuntimeError("camera_pair_not_ready")
                return {}
            for camera_id, cap in self.caps.items():
                if not cap.grab():
                    if raise_on_failure:
                        raise RuntimeError(f"camera_{camera_id}_grab_failed")
                    return {}
            frames: dict[int, Any] = {}
            for camera_id, cap in self.caps.items():
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    if raise_on_failure:
                        raise RuntimeError(f"camera_{camera_id}_retrieve_failed")
                    return {}
                frames[camera_id] = frame
            return frames

    def capture_pair(self) -> tuple[Any, Any]:
        # This intentionally matches ocrTest.py: grab every camera first, then
        # retrieve every camera, minimizing the time difference between images.
        self.capture_requested.set()
        try:
            frames = self._grab_pair(raise_on_failure=True)
        finally:
            self.capture_requested.clear()
        frame1, frame2 = frames[1], frames[2]
        print(
            f"[Capture] pair camera1={frame1.shape[1]}x{frame1.shape[0]} "
            f"camera2={frame2.shape[1]}x{frame2.shape[0]}"
        )
        return frame1, frame2

    def stop(self):
        if not self.active:
            return
        self.active = False
        if self.thread is not None:
            self.thread.join(timeout=1.5)
        with self.io_lock:
            for cap in self.caps.values():
                cap.release()
            self.caps = {}
        self.thread = None
        with self.frame_lock:
            self.preview_frames = {}
        time.sleep(0.15)
        print("[Camera] Full HD pair stopped")


camera_rig = CameraRig()


def _token_is_valid() -> bool:
    if not DEVICE_TOKEN:
        # Deliberately fail closed on non-loopback clients when no key is configured.
        return request.remote_addr in {"127.0.0.1", "::1"}
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {DEVICE_TOKEN}"
    return hmac.compare_digest(supplied, expected)


@app.before_request
def authenticate_api():
    if request.path == "/api/v1/health" or request.method == "OPTIONS":
        return None
    if request.path.startswith("/api/v1/") and not _token_is_valid():
        return jsonify(success=False, error="unauthorized"), 401
    return None


@app.after_request
def add_browser_headers(response):
    # The main integration is server-to-server. These headers also permit the
    # named website origin for a future direct MJPEG preview if required.
    request_origin = request.headers.get("Origin")
    if request_origin in WEBSITE_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = request_origin
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Vary"] = "Origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.route("/api/v1/health")
def health():
    return jsonify(success=True, service="medilens-hardware", device_id="medibox-01")


@app.route("/api/v1/status")
def status():
    return jsonify(
        success=True,
        device_id="medibox-01",
        preview=camera_rig.active,
        light=dict(light_state),
        controlled_led_indexes=list(CONTROLLED_LED_INDEXES),
        reserved_led_indexes=list(RESERVED_LED_INDEXES),
        cameras={"camera1": CAMERA_1_INDEX, "camera2": CAMERA_2_INDEX},
        capture_resolution={"width": CAPTURE_WIDTH, "height": CAPTURE_HEIGHT},
        capture_fps=CAPTURE_FPS,
        jpeg_quality=CAPTURE_JPEG_QUALITY,
        focus={"camera1": CAMERA_1_FOCUS, "camera2": CAMERA_2_FOCUS},
    )


@app.route("/api/v1/preview/start", methods=["POST"])
def preview_start():
    if capture_lock.locked():
        return jsonify(success=False, error="capture_busy"), 409
    payload = request.get_json(silent=True) or {}
    try:
        light_mode, brightness = requested_light_settings(payload)
    except ValueError as error:
        return jsonify(success=False, error=str(error)), 400
    with camera_lock:
        set_controlled_lights(light_mode, brightness)
        time.sleep(0.2)
        if not camera_rig.start():
            turn_controlled_lights_off()
            return jsonify(success=False, error="camera_pair_open_failed"), 500
    return jsonify(success=True, preview=True, light=dict(light_state))


@app.route("/api/v1/preview/stop", methods=["POST"])
def preview_stop():
    with camera_lock:
        camera_rig.stop()
        turn_controlled_lights_off()
    return jsonify(success=True, preview=False, light=dict(light_state))


def generate_preview_stream(camera_id: int):
    delay = 1.0 / max(PREVIEW_FPS, 1)
    while camera_rig.active:
        frame = camera_rig.get_frame(camera_id)
        if frame is None:
            time.sleep(0.05)
            continue
        preview_frame = cv2.resize(frame, (PREVIEW_WIDTH, PREVIEW_HEIGHT), interpolation=cv2.INTER_AREA)
        ok, buffer = cv2.imencode(".jpg", preview_frame, [cv2.IMWRITE_JPEG_QUALITY, STREAM_JPEG_QUALITY])
        if ok:
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
        time.sleep(delay)


@app.route("/api/v1/preview/stream")
def preview_stream():
    if not camera_rig.active:
        return jsonify(success=False, error="preview_off"), 409
    try:
        camera_id = int(request.args.get("camera", "1"))
    except ValueError:
        return jsonify(success=False, error="invalid_camera_id"), 400
    if camera_id not in {1, 2}:
        return jsonify(success=False, error="invalid_camera_id"), 400
    return Response(
        stream_with_context(generate_preview_stream(camera_id)),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


def _save_frame(capture_path: Path, camera_id: int, frame) -> dict[str, Any]:
    image_path = capture_path / f"camera{camera_id}.jpg"
    saved = cv2.imwrite(str(image_path), frame, [cv2.IMWRITE_JPEG_QUALITY, CAPTURE_JPEG_QUALITY])
    if not saved:
        raise RuntimeError(f"camera_{camera_id}_image_save_failed")
    height, width = frame.shape[:2]
    return {
        "cameraId": camera_id,
        "width": width,
        "height": height,
        "mimeType": "image/jpeg",
        "url": f"/api/v1/captures/{capture_path.name}/camera/{camera_id}",
    }


def _verification_state_path(capture_id: str) -> Path:
    return CAPTURE_DIR / capture_id / "verification.json"


def write_verification_state(capture_id: str, state: dict[str, Any]) -> dict[str, Any]:
    document = {
        "captureId": capture_id,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        **state,
    }
    target = _verification_state_path(capture_id)
    temporary = target.with_suffix(".json.tmp")
    with verification_state_lock:
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)
    return document


def read_verification_state(capture_id: str) -> dict[str, Any] | None:
    target = _verification_state_path(capture_id)
    if not target.is_file():
        return None
    with verification_state_lock:
        return json.loads(target.read_text(encoding="utf-8"))


def forward_capture_to_backend(capture_id: str, camera1_path: Path, camera2_path: Path):
    """Send Camera 1 as front and Camera 2 as back, then retain MedicServer's result."""
    if not BACKEND_UPLOAD_URL:
        return
    write_verification_state(capture_id, {"status": "processing"})
    try:
        import requests

        headers = {"Authorization": f"Bearer {BACKEND_UPLOAD_TOKEN}"} if BACKEND_UPLOAD_TOKEN else {}
        with camera1_path.open("rb") as camera1_file, camera2_path.open("rb") as camera2_file:
            response = requests.post(
                BACKEND_UPLOAD_URL,
                headers=headers,
                files={
                    "front_image": ("front.jpg", camera1_file, "image/jpeg"),
                    "back_image": ("back.jpg", camera2_file, "image/jpeg"),
                },
                timeout=(10, 300),
            )
        try:
            result = response.json()
        except ValueError:
            result = {"detail": response.text[:2000]}
        if not response.ok:
            raise RuntimeError(f"MedicServer HTTP {response.status_code}: {result}")
        write_verification_state(
            capture_id,
            {
                "status": "completed",
                "verificationId": result.get("verification_id"),
                "result": result,
            },
        )
        print(f"[Backend] capture {capture_id} verified as {result.get('verification_id')}")
    except Exception as error:
        write_verification_state(
            capture_id,
            {"status": "failed", "error": f"{type(error).__name__}: {error}"},
        )
        print(f"[Backend] capture {capture_id} upload failed: {error}")


def perform_capture(
    light_mode: str = FIXED_LIGHT_MODE,
    brightness: int = FIXED_LIGHT_BRIGHTNESS,
    send_to_server: bool = True,
) -> dict[str, Any]:
    if not capture_lock.acquire(blocking=False):
        raise RuntimeError("capture_busy")
    try:
        with camera_lock:
            set_controlled_lights(light_mode, brightness)
            try:
                if not camera_rig.active:
                    if not camera_rig.start():
                        raise RuntimeError("camera_pair_open_failed")
                    time.sleep(CAPTURE_SETTLE_SECONDS)
                frame1, frame2 = camera_rig.capture_pair()
            finally:
                camera_rig.stop()
                turn_controlled_lights_off()

        capture_id = str(uuid.uuid4())
        capture_path = CAPTURE_DIR / capture_id
        capture_path.mkdir(parents=True, exist_ok=False)
        camera1 = _save_frame(capture_path, 1, frame1)
        camera2 = _save_frame(capture_path, 2, frame2)
        captured_at = datetime.now(timezone.utc).isoformat()
        metadata = {
            "captureId": capture_id,
            "deviceId": "medibox-01",
            "capturedAt": captured_at,
            "camera1": camera1,
            "camera2": camera2,
            "lighting": {"lightMode": light_mode, "brightness": brightness},
        }
        (capture_path / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        backend_status = "skipped" if not send_to_server else "not_configured"
        if send_to_server and BACKEND_UPLOAD_URL:
            backend_status = "queued"
            write_verification_state(capture_id, {"status": "queued"})
            threading.Thread(
                target=forward_capture_to_backend,
                args=(capture_id, capture_path / "camera1.jpg", capture_path / "camera2.jpg"),
                daemon=True,
                name=f"backend-upload-{capture_id}",
            ).start()
        return {
            **metadata,
            "backendUpload": {
                "status": backend_status,
                "verificationStatusUrl": f"/api/v1/captures/{capture_id}/verification",
            },
        }
    finally:
        capture_lock.release()


@app.route("/api/v1/captures/<capture_id>/camera/<int:camera_id>")
def capture_image(capture_id: str, camera_id: int):
    if not re.fullmatch(r"[0-9a-f-]{36}", capture_id) or camera_id not in {1, 2}:
        return jsonify(success=False, error="invalid_capture_image"), 400
    image_path = CAPTURE_DIR / capture_id / f"camera{camera_id}.jpg"
    if not image_path.is_file():
        return jsonify(success=False, error="capture_image_not_found"), 404
    return send_file(image_path, mimetype="image/jpeg", conditional=True, max_age=0)


@app.route("/api/v1/captures/<capture_id>/verification")
def capture_verification(capture_id: str):
    if not re.fullmatch(r"[0-9a-f-]{36}", capture_id):
        return jsonify(success=False, error="invalid_capture_id"), 400
    capture_path = CAPTURE_DIR / capture_id
    if not capture_path.is_dir():
        return jsonify(success=False, error="capture_not_found"), 404
    state = read_verification_state(capture_id)
    if state is None:
        state = {
            "captureId": capture_id,
            "status": "not_configured" if not BACKEND_UPLOAD_URL else "queued",
        }
    return jsonify(success=True, **state)


@app.route("/api/v1/commands", methods=["POST"])
def commands():
    body = request.get_json(silent=True) or {}
    command_id = str(body.get("commandId") or uuid.uuid4())
    command_type = str(body.get("type", ""))
    payload = body.get("payload") or {}
    try:
        if command_type == "set_light":
            light_mode, brightness = requested_light_settings(payload)
            state = set_controlled_lights(light_mode, brightness)
            data: dict[str, Any] = {"light": state}
        elif command_type == "shutdown_lights":
            data = {"light": turn_controlled_lights_off()}
        elif command_type == "capture":
            light_mode, brightness = requested_light_settings(payload)
            send_to_server = payload.get("sendToServer", True) is not False
            data = perform_capture(light_mode, brightness, send_to_server)
        elif command_type == "identify":
            return jsonify(success=False, commandId=command_id, error="identification_removed_use_capture"), 410
        else:
            return jsonify(success=False, commandId=command_id, error="unsupported_command"), 400
        return jsonify(success=True, commandId=command_id, status="completed", result=data)
    except ValueError as error:
        return jsonify(success=False, commandId=command_id, status="failed", error=str(error)), 400
    except RuntimeError as error:
        status_code = 409 if str(error) == "capture_busy" else 500
        return jsonify(success=False, commandId=command_id, status="failed", error=str(error)), status_code
    except Exception as error:
        print(f"[Command] {command_type} failed: {error}")
        turn_controlled_lights_off()
        return jsonify(success=False, commandId=command_id, status="failed", error=str(error)), 500


def cleanup():
    print("[Shutdown] closing cameras and controlled LEDs")
    try:
        camera_rig.stop()
    except Exception:
        pass
    try:
        turn_controlled_lights_off()
    except Exception:
        pass


atexit.register(cleanup)


if __name__ == "__main__":
    if not DEVICE_TOKEN:
        raise SystemExit("MEDILENS_DEVICE_TOKEN is required for LAN access")
    print("=" * 68)
    print("MediLens hardware service")
    print(f"Listen: http://210.240.160.159:{LISTEN_PORT}")
    print(f"Websites: {', '.join(sorted(WEBSITE_ORIGINS))}")
    print(f"LED controlled: {CONTROLLED_LED_INDEXES}")
    print(f"LED reserved/unchanged: {RESERVED_LED_INDEXES}")
    print(f"LED reserved fixed RGB: {RESERVED_LED_RGB}")
    print(f"Capture light: {FIXED_LIGHT_MODE.upper()} {FIXED_LIGHT_BRIGHTNESS}%")
    print(f"Camera 1: /dev/video{CAMERA_1_INDEX}; Camera 2: /dev/video{CAMERA_2_INDEX}")
    print("=" * 68)
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, threaded=True, debug=False, use_reloader=False)
