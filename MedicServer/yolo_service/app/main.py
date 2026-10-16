from __future__ import annotations

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from function.pair_function import PairYoloPredictor

MAX_BYTES = 25 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = os.getenv("YOLO_DEVICE", "cpu")
    device = configured if configured != "auto" else ("cuda:0" if torch.cuda.is_available() else "cpu")
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"YOLO_DEVICE={device}, but CUDA is unavailable in this image/runtime")
    app.state.predictor = PairYoloPredictor(
        checkpoint_path=os.getenv("PAIR_CHECKPOINT", "/models/best_pair.pt"),
        base_model_path=os.getenv("YOLO_BASE_MODEL", "/models/yolo_best.pt"),
        device=device, verbose=True,
    )
    app.state.device = device
    app.state.lock = asyncio.Lock()
    yield


app = FastAPI(title="Medic paired-YOLO worker", version="1.0.0", lifespan=lifespan)


async def read_image(upload: UploadFile, label: str) -> bytes:
    data = await upload.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, f"{label} is empty or too large")
    return data


@app.get("/health")
async def health():
    return {"status": "ready", "model_loaded": hasattr(app.state, "predictor"), "device": getattr(app.state, "device", None)}


@app.post("/internal/v1/classify")
async def classify(front_image: UploadFile = File(...), back_image: UploadFile = File(...)):
    front, back = await asyncio.gather(read_image(front_image, "front_image"), read_image(back_image, "back_image"))
    with tempfile.TemporaryDirectory(prefix="medic-yolo-") as directory:
        first = Path(directory) / "cam0.jpg"
        second = Path(directory) / "cam1.jpg"
        first.write_bytes(front)
        second.write_bytes(back)
        async with app.state.lock:
            result = await asyncio.to_thread(app.state.predictor.predict, first, second, 5)
    return {**result, "input_order": ["front", "back"], "device": app.state.device}

