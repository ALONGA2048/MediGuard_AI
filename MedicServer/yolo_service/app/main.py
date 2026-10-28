from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
import cv2
import numpy as np
from ood_filter import CosineKNN1OODFilter

MAX_BYTES = 25 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    configured = os.getenv("YOLO_DEVICE", "cpu")
    device = configured if configured != "auto" else ("cuda:0" if torch.cuda.is_available() else "cpu")
    if device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(f"YOLO_DEVICE={device}, but CUDA is unavailable in this image/runtime")
    app.state.gate = CosineKNN1OODFilter(
        config_path=os.getenv("OOD_CONFIG", "/app/legacy/ood_filter/config.json"),
        device=device, verbose=True,
    )
    app.state.device = device
    app.state.lock = asyncio.Lock()
    yield


app = FastAPI(title="Medic Pair-YOLO + cosine kNN1 OOD worker", version="2.0.0", lifespan=lifespan)


async def read_image(upload: UploadFile, label: str) -> bytes:
    data = await upload.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, f"{label} is empty or too large")
    return data


@app.get("/health")
async def health():
    return {"status": "ready", "model_loaded": hasattr(app.state, "gate"),
            "device": getattr(app.state, "device", None),
            "ood": app.state.gate.compatibility_metadata()}


def decode_image(data: bytes, label: str) -> np.ndarray:
    # Match drug-project's BGR array input, preserving front/cam0, back/cam1.
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.size == 0:
        raise HTTPException(422, f"{label} is not a decodable image")
    return frame


@app.post("/internal/v1/classify")
async def classify(front_image: UploadFile = File(...), back_image: UploadFile = File(...)):
    front, back = await asyncio.gather(read_image(front_image, "front_image"), read_image(back_image, "back_image"))
    first, second = await asyncio.gather(
        asyncio.to_thread(decode_image, front, "front_image"),
        asyncio.to_thread(decode_image, back, "back_image"),
    )
    async with app.state.lock:
        result = await asyncio.to_thread(app.state.gate.predict_arrays, first, second, 5)
    return {**result, "input_order": ["front", "back"], "device": app.state.device}

