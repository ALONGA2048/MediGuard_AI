from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from . import storage
from .fusion import fuse_results, validate_ood_result, verification_outcome

UPLOAD_ROOT = Path(os.getenv("UPLOAD_ROOT", "/data/uploads"))
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_MB", "20")) * 1024 * 1024
CONTENT_EXTENSIONS = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/tiff": ".tiff", "image/bmp": ".bmp"}
MAX_IMAGE_PIXELS = 40_000_000


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured_device = os.getenv("OCR_DEVICE", "cpu").strip().lower()
    use_gpu = configured_device != "cpu"
    os.environ["PADDLE_OCR_USE_GPU"] = "1" if use_gpu else "0"
    if use_gpu:
        os.environ["CUDA_VISIBLE_DEVICES"] = configured_device

    import paddle

    cuda_compiled = bool(paddle.device.is_compiled_with_cuda())
    cuda_devices = int(paddle.device.cuda.device_count()) if cuda_compiled else 0
    if use_gpu and (not cuda_compiled or cuda_devices < 1):
        raise RuntimeError(
            "OCR_DEVICE requests GPU, but Paddle cannot see a CUDA device "
            f"(cuda_compiled={cuda_compiled}, cuda_devices={cuda_devices})"
        )
    import ocr
    from drug_matching import DrugMatcher, DrugRepository
    repository = DrugRepository()
    app.state.ocr = ocr
    app.state.repository = repository
    app.state.matcher = DrugMatcher(repository)
    app.state.engines = ocr.load_ocr_engines()
    app.state.ocr_device = f"cuda:{configured_device}" if use_gpu else "cpu"
    app.state.paddle_cuda = cuda_compiled
    app.state.cuda_devices = cuda_devices
    app.state.inference_lock = asyncio.Lock()
    try:
        yield
    finally:
        repository.close()


app = FastAPI(title="Medic OCR + Pair-YOLO/OOD Verification API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "*").split(","), allow_methods=["GET", "POST"], allow_headers=["*"])


async def save_upload(upload: UploadFile, side: str, directory: Path) -> tuple[Path, dict[str, Any]]:
    content_type = (upload.content_type or "").lower()
    if content_type not in CONTENT_EXTENSIONS:
        raise HTTPException(415, f"{side} must be JPEG, PNG, WEBP, TIFF, or BMP")
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{side} is empty or exceeds {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{side}{CONTENT_EXTENSIONS[content_type]}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    try:
        with Image.open(temporary) as image:
            image.verify()
        with Image.open(temporary) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise OSError(f"image exceeds {MAX_IMAGE_PIXELS} pixels")
    except (UnidentifiedImageError, OSError) as error:
        temporary.unlink(missing_ok=True)
        raise HTTPException(422, f"{side} is not a valid image") from error
    temporary.replace(target)
    return target, {"side": side, "original_filename": Path(upload.filename or f"{side}.image").name,
                    "content_type": content_type, "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                    "storage_path": str(target)}


def run_ocr(app_: FastAPI, front: Path, back: Path, verification_id: UUID) -> dict[str, Any]:
    from drug_matching.pipeline import infer_pair_paths
    return infer_pair_paths([front, back], app_.state.engines, app_.state.matcher,
                            context={"verification_id": str(verification_id), "input_sides": ["front", "back"]})


async def run_yolo(front: Path, back: Path) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            with front.open("rb") as first, back.open("rb") as second:
                response = await client.post(
                    f"{os.getenv('YOLO_URL', 'http://yolo:8001')}/internal/v1/classify",
                    files={"front_image": (front.name, first, "application/octet-stream"),
                           "back_image": (back.name, second, "application/octet-stream")},
                )
        response.raise_for_status()
        return response.json()
    except Exception as error:
        raise RuntimeError(f"Pair-YOLO/OOD inference failed: {type(error).__name__}: {error}") from error


@app.get("/api/v1/health")
async def health():
    try:
        database_ok = await asyncio.to_thread(storage.ping)
    except Exception:
        database_ok = False
    return {"status": "ready" if database_ok else "degraded", "database": database_ok,
            "ocr_loaded": hasattr(app.state, "engines"),
            "ocr_device": getattr(app.state, "ocr_device", None),
            "paddle_cuda": getattr(app.state, "paddle_cuda", False),
            "cuda_devices": getattr(app.state, "cuda_devices", 0),
            "version": app.version}


@app.post("/api/v1/verifications", status_code=201)
async def verify_pair(
    front_image: UploadFile = File(...), back_image: UploadFile = File(...),
    expected_drug_id: int | None = Form(None), expected_name: str | None = Form(None),
):
    verification_id = uuid4()
    pair_directory = UPLOAD_ROOT / str(verification_id)
    front, front_meta = await save_upload(front_image, "front", pair_directory)
    back, back_meta = await save_upload(back_image, "back", pair_directory)
    try:
        expected_drug_id, expected_name = await asyncio.to_thread(storage.resolve_expected, expected_drug_id, expected_name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    try:
        await asyncio.to_thread(storage.create_job, verification_id, expected_drug_id, expected_name, [front_meta, back_meta])
        async with app.state.inference_lock:
            yolo_result = await run_yolo(front, back)
            validate_ood_result(yolo_result)
            ocr_result = json_safe(await asyncio.to_thread(run_ocr, app, front, back, verification_id))
        fused = fuse_results(
            ocr_result, yolo_result,
            final_threshold=float(os.getenv("FINAL_THRESHOLD", "0.95")),
            ocr_basic_score=float(os.getenv("OCR_BASIC_SCORE", "50.0")),
            ocr_tie_gap=float(os.getenv("OCR_TIE_GAP", "8.0")),
            ocr_supported_yolo_threshold=float(os.getenv("OCR_SUPPORTED_YOLO_THRESHOLD", "0.60")),
        )
        outcome = verification_outcome(str(fused.get("final_prediction") or "unknown"), expected_name)
        payload = {"verification_id": str(verification_id), "status": "COMPLETED", "outcome": outcome,
                   "expected_drug_id": expected_drug_id, "expected_name": expected_name,
                   "ocr_result": ocr_result, "yolo_result": yolo_result, "fused_result": fused}
        result_file = await asyncio.to_thread(storage.result_document, verification_id, payload)
        await asyncio.to_thread(storage.complete_job, verification_id, outcome, fused, ocr_result, yolo_result, result_file)
        return payload
    except Exception as error:
        try:
            await asyncio.to_thread(storage.fail_job, verification_id, f"{type(error).__name__}: {error}")
        except Exception:
            pass
        raise HTTPException(500, f"Verification failed: {type(error).__name__}: {error}") from error


@app.get("/api/v1/verifications")
async def verifications(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return {"items": jsonable_encoder(await asyncio.to_thread(storage.list_jobs, limit, offset)), "limit": limit, "offset": offset}


@app.get("/api/v1/verifications/{verification_id}")
async def verification(verification_id: UUID):
    item = await asyncio.to_thread(storage.get_job, verification_id)
    if not item:
        raise HTTPException(404, "Verification not found")
    for image in item["images"]:
        image["url"] = f"/api/v1/verifications/{verification_id}/images/{image['side']}"
        image.pop("storage_path", None)
    return jsonable_encoder(item)


@app.get("/api/v1/verifications/{verification_id}/images/{side}")
async def verification_image(verification_id: UUID, side: str):
    if side not in {"front", "back"}:
        raise HTTPException(404, "Image side not found")
    item = await asyncio.to_thread(storage.get_job, verification_id)
    if not item:
        raise HTTPException(404, "Verification not found")
    image = next((entry for entry in item["images"] if entry["side"] == side), None)
    if not image or not Path(image["storage_path"]).is_file():
        raise HTTPException(404, "Image not found")
    return FileResponse(image["storage_path"], media_type=image["content_type"], filename=image["original_filename"])
