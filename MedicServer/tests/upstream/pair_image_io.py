from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

PAIR_RE = re.compile(r"^(?P<id>.+)_cam(?P<camera>[01])\.(?:jpg|jpeg|png|bmp)$", re.I)


@dataclass(frozen=True)
class PairRecord:
    label: str
    pair_id: str
    cam0: Path
    cam1: Path


def discover_pairs(root: Path | str, *, strict: bool = True):
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Pair directory not found: {root}")
    grouped: dict[tuple[Path, str], dict[int, Path]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        match = PAIR_RE.match(path.name)
        if not match:
            continue
        key = (path.parent, match.group("id"))
        camera = int(match.group("camera"))
        if camera in grouped.setdefault(key, {}):
            raise RuntimeError(f"Duplicate cam{camera}: {path.parent}/{match.group('id')}")
        grouped[key][camera] = path
    records, incomplete = [], []
    for (parent, pair_id), cameras in sorted(
        grouped.items(), key=lambda item: str(item[0]).casefold()
    ):
        relative_parent = parent.relative_to(root)
        label = relative_parent.parts[0] if relative_parent.parts else root.name
        relative_id = str(relative_parent / pair_id).replace("\\", "/")
        if set(cameras) != {0, 1}:
            incomplete.append({
                "pair_id": relative_id,
                "directory": str(parent),
                "missing": [f"cam{x}" for x in (0, 1) if x not in cameras],
            })
            continue
        records.append(PairRecord(label, relative_id, cameras[0], cameras[1]))
    if strict and incomplete:
        raise RuntimeError(
            f"Incomplete cam0/cam1 pairs ({len(incomplete)}): "
            + ", ".join(item["pair_id"] for item in incomplete[:10])
        )
    if not records and strict:
        raise RuntimeError(f"No complete cam0/cam1 pairs found in {root}")
    return records, incomplete


def read_bgr(path: Path | str) -> np.ndarray:
    path = Path(path)
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"Could not decode image: {path}")
    return image


__all__ = ["PairRecord", "discover_pairs", "read_bgr"]
