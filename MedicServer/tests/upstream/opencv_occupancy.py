from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
DEFAULT_BACKGROUND_DIR = ROOT / "camera_background"
EMPTY = "EMPTY"
OCCUPIED = "OCCUPIED"
UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class OccupancyConfig:
    processing_width: int = 640
    processing_height: int = 360
    roi_margin_ratio: float = 0.035
    intensity_threshold: int = 20
    strong_intensity_threshold: int = 45
    chroma_threshold: int = 14
    empty_changed_ratio: float = 0.0025
    empty_largest_ratio: float = 0.0008
    empty_edge_ratio: float = 0.0015
    occupied_changed_ratio: float = 0.012
    occupied_largest_ratio: float = 0.0025
    occupied_edge_ratio: float = 0.0030


def _validate_frame(frame: np.ndarray, name: str) -> None:
    if not isinstance(frame, np.ndarray):
        raise TypeError(f"{name} must be a numpy ndarray")
    if frame.dtype != np.uint8 or frame.ndim != 3 or frame.shape[2] != 3:
        raise ValueError(f"{name} must be uint8 HxWx3 BGR, got {frame.dtype} {frame.shape}")


def _load_image(path: Path) -> np.ndarray:
    if not path.is_file():
        raise FileNotFoundError(f"Background image not found: {path}")
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not decode background image: {path}")
    return image


def _largest_component_ratio(mask: np.ndarray) -> float:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return 0.0
    return max(cv2.contourArea(contour) for contour in contours) / float(mask.size)


def classify_frame(
    frame: np.ndarray,
    background: np.ndarray,
    config: OccupancyConfig = OccupancyConfig(),
) -> dict[str, Any]:
    """Classify one camera using private resized copies and background differencing."""
    _validate_frame(frame, "frame")
    _validate_frame(background, "background")
    started = time.perf_counter()
    size = (config.processing_width, config.processing_height)
    current = cv2.resize(frame, size, interpolation=cv2.INTER_AREA)
    reference = cv2.resize(background, size, interpolation=cv2.INTER_AREA)

    margin_x = int(config.processing_width * config.roi_margin_ratio)
    margin_y = int(config.processing_height * config.roi_margin_ratio)
    current = current[margin_y:-margin_y or None, margin_x:-margin_x or None]
    reference = reference[margin_y:-margin_y or None, margin_x:-margin_x or None]

    current_lab = cv2.cvtColor(current, cv2.COLOR_BGR2LAB)
    reference_lab = cv2.cvtColor(reference, cv2.COLOR_BGR2LAB)
    current_l = current_lab[:, :, 0].astype(np.float32)
    reference_l = reference_lab[:, :, 0].astype(np.float32)

    # Median global compensation prevents small exposure shifts from filling
    # the entire mask.  Chroma and changed edges retain white/reflective object
    # boundaries while ordinary soft shadows are suppressed.
    brightness_shift = float(np.median(current_l - reference_l))
    adjusted_l = np.clip(current_l - brightness_shift, 0, 255)
    intensity = np.abs(adjusted_l - reference_l)
    chroma = cv2.absdiff(current_lab[:, :, 1:3], reference_lab[:, :, 1:3])
    chroma_delta = np.max(chroma, axis=2)

    current_edges = cv2.Canny(cv2.GaussianBlur(current, (5, 5), 0), 45, 120)
    reference_edges = cv2.Canny(cv2.GaussianBlur(reference, (5, 5), 0), 45, 120)
    changed_edges = cv2.bitwise_xor(current_edges, reference_edges)
    changed_edges = cv2.dilate(changed_edges, np.ones((5, 5), np.uint8), iterations=1)

    moderate = intensity >= config.intensity_threshold
    strong = intensity >= config.strong_intensity_threshold
    colorful = chroma_delta >= config.chroma_threshold
    edge_near = changed_edges > 0
    mask = np.where(strong | colorful | (moderate & edge_near), 255, 0).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))

    changed_ratio = float(np.count_nonzero(mask) / mask.size)
    edge_ratio = float(np.count_nonzero(changed_edges) / changed_edges.size)
    largest_ratio = _largest_component_ratio(mask)

    occupied = (
        changed_ratio >= config.occupied_changed_ratio
        or (
            largest_ratio >= config.occupied_largest_ratio
            and edge_ratio >= config.occupied_edge_ratio
        )
    )
    empty = (
        changed_ratio <= config.empty_changed_ratio
        and largest_ratio <= config.empty_largest_ratio
        and edge_ratio <= config.empty_edge_ratio
    )
    status = OCCUPIED if occupied else (EMPTY if empty else UNCERTAIN)
    return {
        "status": status,
        "processing_resolution": [config.processing_width, config.processing_height],
        "brightness_shift": brightness_shift,
        "changed_ratio": changed_ratio,
        "largest_component_ratio": largest_ratio,
        "changed_edge_ratio": edge_ratio,
        "time_ms": (time.perf_counter() - started) * 1000.0,
    }


def combine_pair_status(cam0_status: str, cam1_status: str) -> str:
    if UNCERTAIN in {cam0_status, cam1_status}:
        return "RETRY_OR_REPOSITION"
    if cam0_status == EMPTY and cam1_status == EMPTY:
        return "NO_DRUG"
    if cam0_status == OCCUPIED and cam1_status == OCCUPIED:
        return "READY_FOR_INFERENCE"
    if {cam0_status, cam1_status} == {EMPTY, OCCUPIED}:
        return "REPOSITION"
    raise ValueError(f"Invalid occupancy states: {cam0_status}, {cam1_status}")


class PairOccupancyDetector:
    def __init__(
        self,
        background_dir: Path | str = DEFAULT_BACKGROUND_DIR,
        config: OccupancyConfig = OccupancyConfig(),
    ) -> None:
        self.background_dir = Path(background_dir).resolve()
        self.config = config

    def background_path(self, camera_id: int) -> Path:
        if camera_id not in (0, 1):
            raise ValueError("Only Camera0 and Camera1 are supported")
        return self.background_dir / f"cam{camera_id}_empty.png"

    def ready(self) -> bool:
        return all(self.background_path(camera_id).is_file() for camera_id in (0, 1))

    def calibrate(self, cam0: np.ndarray, cam1: np.ndarray) -> dict[str, Any]:
        """Persist only explicit B-key empty-background calibration frames."""
        _validate_frame(cam0, "cam0")
        _validate_frame(cam1, "cam1")
        self.background_dir.mkdir(parents=True, exist_ok=True)
        written = []
        for camera_id, frame in enumerate((cam0, cam1)):
            ok, encoded = cv2.imencode(".png", frame)
            if not ok:
                raise RuntimeError(f"Could not encode Camera{camera_id} background")
            destination = self.background_path(camera_id)
            temporary = destination.with_suffix(".tmp.png")
            temporary.write_bytes(encoded.tobytes())
            os.replace(temporary, destination)
            written.append(str(destination))
        return {"status": "CALIBRATED", "paths": written}

    def check_pair(self, cam0: np.ndarray, cam1: np.ndarray) -> dict[str, Any]:
        started = time.perf_counter()
        before = (cam0.copy(), cam1.copy())
        result0 = classify_frame(cam0, _load_image(self.background_path(0)), self.config)
        result1 = classify_frame(cam1, _load_image(self.background_path(1)), self.config)
        if not np.array_equal(before[0], cam0) or not np.array_equal(before[1], cam1):
            raise RuntimeError("Occupancy detector modified an original frame")
        final = combine_pair_status(result0["status"], result1["status"])
        return {
            "cam0": result0,
            "cam1": result1,
            "status": final,
            "time_ms": (time.perf_counter() - started) * 1000.0,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Independent two-camera occupancy test")
    parser.add_argument("--cam0", type=Path, required=True)
    parser.add_argument("--cam1", type=Path, required=True)
    parser.add_argument("--background-dir", type=Path, default=DEFAULT_BACKGROUND_DIR)
    parser.add_argument("--calibrate", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    detector = PairOccupancyDetector(args.background_dir)
    cam0, cam1 = _load_image(args.cam0.resolve()), _load_image(args.cam1.resolve())
    result = detector.calibrate(cam0, cam1) if args.calibrate else detector.check_pair(cam0, cam1)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
