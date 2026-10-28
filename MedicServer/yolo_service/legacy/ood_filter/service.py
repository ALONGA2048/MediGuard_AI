from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

from .scoring import OODScoringError, cosine_knn1

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"


class OODCompatibilityError(RuntimeError):
    """Raised when packaged OOD artifacts cannot reproduce the calibrated feature space."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_ood_config(path: Path | str = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = Path(path).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    for key in ("feature_bank", "pair_checkpoint", "base_model"):
        value = Path(str(data[key]))
        data[key] = str((base / value).resolve() if not value.is_absolute() else value.resolve())
    data["config_path"] = str(config_path)
    return data


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise OODCompatibilityError(message)


class CosineKNN1OODFilter:
    """One-forward Pair-YOLO classifier and calibrated cosine kNN1 OOD gate."""

    def __init__(
        self,
        config_path: Path | str = DEFAULT_CONFIG,
        device: str | torch.device = "cuda:0",
        *,
        verbose: bool = False,
    ) -> None:
        from function.pair_function import PairYoloPredictor

        self.config = load_ood_config(config_path)
        self.device = torch.device(device)
        self.threshold = float(self.config["threshold"])
        _require(self.config.get("method") == "cosine_knn1", "Only cosine_knn1 is supported")
        _require(self.config.get("reject_rule") == "score < threshold", "Unexpected OOD reject rule")
        if self.device.type == "cuda" and not torch.cuda.is_available():
            raise OODCompatibilityError(f"CUDA device requested but unavailable: {self.device}")

        self._verify_files_and_checkpoint()
        self.bank, self.pair_ids, self.labels = self._load_bank()
        self.predictor = PairYoloPredictor(
            checkpoint_path=self.config["pair_checkpoint"],
            base_model_path=self.config["base_model"],
            device=self.device,
            verbose=verbose,
        )
        _require(not self.predictor.yolo_model.training, "YOLO model must be in eval mode")
        _require(not self.predictor.pair_head.training, "Pair head must be in eval mode")
        _require(
            not any(p.requires_grad for p in self.predictor.yolo_model.parameters()),
            "YOLO parameters must be frozen",
        )
        _require(
            not any(p.requires_grad for p in self.predictor.pair_head.parameters()),
            "Pair-head parameters must be frozen",
        )

    def _verify_files_and_checkpoint(self) -> None:
        expected_hashes = self.config["sha256"]
        paths = {
            "feature_bank": Path(self.config["feature_bank"]),
            "pair_checkpoint": Path(self.config["pair_checkpoint"]),
            "base_model": Path(self.config["base_model"]),
        }
        for key, path in paths.items():
            _require(path.is_file(), f"Required OOD artifact is missing: {path}")
            actual = _sha256(path)
            expected = str(expected_hashes[key]).lower()
            _require(actual == expected, f"SHA-256 mismatch for {key}: {actual} != {expected}")

        checkpoint = torch.load(paths["pair_checkpoint"], map_location="cpu", weights_only=False)
        expected = self.config["expected"]
        _require(checkpoint.get("type") == expected["model_type"], "Pair checkpoint model type mismatch")
        _require(int(checkpoint.get("format_version", -1)) == int(expected["checkpoint_format"]), "Pair checkpoint format mismatch")
        _require(int(checkpoint.get("num_classes", -1)) == int(expected["num_classes"]), "Pair class count mismatch")
        _require(int(checkpoint.get("imgsz", -1)) == int(expected["image_size"]), "Pair image size mismatch")
        _require(list(checkpoint.get("camera_order", [])) == list(expected["camera_order"]), "Pair camera order mismatch")
        _require(checkpoint.get("feature_source", "logits") == expected["feature_source"], "Pair feature source mismatch")
        state = checkpoint.get("pair_head_state_dict") or {}
        input_weight = state.get("fusion.0.weight")
        classifier_weight = state.get("fusion.4.weight")
        _require(input_weight is not None and tuple(input_weight.shape) == (256, 238), "Pair fusion input/hidden shape mismatch")
        _require(classifier_weight is not None and tuple(classifier_weight.shape) == (119, 256), "Pair classifier shape mismatch")

    def _load_bank(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        path = Path(self.config["feature_bank"])
        with np.load(path, allow_pickle=False) as data:
            _require({"vectors", "pair_ids", "labels"}.issubset(data.files), "Feature bank keys are incomplete")
            vectors = np.asarray(data["vectors"], dtype=np.float32)
            pair_ids = np.asarray(data["pair_ids"])
            labels = np.asarray(data["labels"])
        expected = self.config["expected"]
        shape = (int(expected["bank_rows"]), int(expected["pair_hidden_dim"]))
        _require(vectors.shape == shape, f"Feature bank shape mismatch: {vectors.shape} != {shape}")
        _require(len(pair_ids) == len(vectors) == len(labels), "Feature bank metadata length mismatch")
        _require(np.isfinite(vectors).all(), "Feature bank contains NaN or Inf")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        _require(bool(np.all(norms > 0)), "Feature bank contains zero vectors")
        normalized = np.ascontiguousarray(vectors / norms, dtype=np.float32)
        return normalized, pair_ids, labels

    def score_feature(self, feature: np.ndarray) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = cosine_knn1(feature, self.bank, self.pair_ids, self.labels, self.threshold)
        except OODScoringError as exc:
            raise OODCompatibilityError(str(exc)) from exc
        result.update({
            "ood_time_ms": (time.perf_counter() - started) * 1000.0,
        })
        return result

    @torch.inference_mode()
    def predict_arrays(
        self,
        cam0_bgr: np.ndarray,
        cam1_bgr: np.ndarray,
        top_k: int = 5,
        *,
        include_feature: bool = False,
    ) -> dict[str, Any]:
        total_started = time.perf_counter()
        prediction = self.predictor.predict_arrays_with_features(cam0_bgr, cam1_bgr, top_k=top_k)
        feature = prediction.pop("pair_feature")
        prediction.pop("pair_logits", None)
        scored = self.score_feature(feature)
        prediction.update(scored)
        prediction.update({
            "pair_forward_count": 1,
            "pair_forward_time_ms": prediction.get("time_ms"),
            "ood_total_time_ms": (time.perf_counter() - total_started) * 1000.0,
            "feature_dim": int(feature.shape[0]),
        })
        if include_feature:
            prediction["pair_feature"] = feature.copy()
        return prediction

    def compatibility_metadata(self) -> dict[str, Any]:
        return {
            "config_path": self.config["config_path"],
            "threshold": self.threshold,
            "method": self.config["method"],
            "device": str(self.device),
            "bank_shape": list(self.bank.shape),
            "sha256": dict(self.config["sha256"]),
            "expected": dict(self.config["expected"]),
        }
