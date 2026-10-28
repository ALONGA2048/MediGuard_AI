"""Standalone paired-YOLO inference utilities.

This module contains only the model definitions and helper functions required
for inference with a paired cam0/cam1 YOLO classification checkpoint.

It intentionally has NO dependency on train.py or pair_utils.py.

Expected checkpoint fields:
    classes
    num_classes
    yolo_state_dict
    pair_head_state_dict
    imgsz                  (optional, default=640)
    feature_source         (optional, default='logits')
    camera_order           (optional, default=['cam0', 'cam1'])
    format_version         (optional, supported: 1/2/3)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
from PIL import Image
from torchvision import transforms
from ultralytics import YOLO
from ultralytics.nn.modules.head import Classify


# ============================================================
# Pair Fusion Head
# ============================================================

class PairFusionHead(nn.Module):
    """Ordered cam0/cam1 feature fusion; one prediction per image pair."""

    def __init__(
        self,
        yolo_output_dim: int,
        num_classes: int,
        feature_source: str = "logits",
        normalization: str = "layernorm",
    ) -> None:
        super().__init__()

        if feature_source not in {"logits", "pooled"}:
            raise ValueError(f"Unsupported feature source: {feature_source}")

        self.feature_source = feature_source

        hidden_dim = max(256, num_classes * 2)

        if normalization == "layernorm":
            norm: nn.Module = nn.LayerNorm(hidden_dim)
        elif normalization == "batchnorm":
            norm = nn.BatchNorm1d(hidden_dim)
        else:
            raise ValueError(
                "normalization must be 'layernorm' or 'batchnorm'"
            )

        self.fusion = nn.Sequential(
            nn.Linear(yolo_output_dim * 2, hidden_dim),
            norm,
            nn.ReLU(inplace=False),
            nn.Dropout(0.25),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(
        self,
        cam0_features: torch.Tensor,
        cam1_features: torch.Tensor,
        return_features: bool = False,
    ):
        pair = torch.cat((cam0_features, cam1_features), dim=1)

        # Same structure as training:
        # Linear -> Norm -> ReLU -> Dropout -> Classifier
        feature = self.fusion[:3](pair)
        logits = self.fusion[4](self.fusion[3](feature))

        if return_features:
            return logits, feature
        return logits


# ============================================================
# Locate YOLO classification head
# ============================================================

def get_classify_head(model: nn.Module) -> Classify:
    classify_heads = [
        module
        for module in model.modules()
        if isinstance(module, Classify)
    ]

    if not classify_heads:
        raise RuntimeError(
            "Ultralytics Classify head was not found in the YOLO model."
        )

    return classify_heads[-1]


# ============================================================
# Configure YOLO class count
# ============================================================

def configure_yolo_classes(
    yolo_model: nn.Module,
    num_classes: int,
    verbose: bool = False,
) -> int:
    """Ensure the final YOLO classification Linear has num_classes outputs."""

    classify_head = get_classify_head(yolo_model)
    old_linear = classify_head.linear
    old_num_classes = int(old_linear.out_features)

    if verbose:
        print(f"YOLO original classes : {old_num_classes}")
        print(f"Checkpoint classes    : {num_classes}")

    if old_num_classes == num_classes:
        if verbose:
            print("YOLO class count matches checkpoint; no change required.")
        return old_num_classes

    if verbose:
        print(
            "Replacing YOLO final classification Linear: "
            f"{old_num_classes} -> {num_classes}"
        )

    classify_head.linear = nn.Linear(
        in_features=old_linear.in_features,
        out_features=num_classes,
        bias=True,
    )

    if hasattr(yolo_model, "nc"):
        yolo_model.nc = num_classes

    return num_classes


# ============================================================
# YOLO raw output helpers
# ============================================================

def get_raw_yolo_logits(
    yolo_model: nn.Module,
    images: torch.Tensor,
) -> torch.Tensor:
    """Return raw classification logits from Ultralytics YOLO-cls."""

    output = yolo_model(images)

    # In eval mode Ultralytics classification may return:
    # (probabilities, raw_logits)
    if isinstance(output, tuple):
        output = output[-1]

    if not torch.is_tensor(output):
        raise RuntimeError(
            "YOLO classification output is not a Tensor: "
            f"{type(output)}"
        )

    return output


# ============================================================
# Pair forward
# ============================================================

def pair_forward(
    yolo_model: nn.Module,
    pair_head: PairFusionHead,
    cam0_images: torch.Tensor,
    cam1_images: torch.Tensor,
    return_features: bool = False,
):
    """Run ordered cam0/cam1 inference through the shared YOLO + Pair Head."""

    if cam0_images.shape != cam1_images.shape:
        raise ValueError(
            "Pair tensors must have identical batch/image shapes: "
            f"cam0={tuple(cam0_images.shape)}, "
            f"cam1={tuple(cam1_images.shape)}"
        )

    batch_size = cam0_images.shape[0]
    images = torch.cat((cam0_images, cam1_images), dim=0)

    if pair_head.feature_source == "pooled":
        captured: List[torch.Tensor] = []

        handle = get_classify_head(yolo_model).pool.register_forward_hook(
            lambda module, inputs, output: captured.append(
                output.flatten(1)
            )
        )

        try:
            yolo_model(images)
        finally:
            handle.remove()

        if len(captured) != 1:
            raise RuntimeError(
                "Expected exactly one YOLO pooled feature tensor, "
                f"got {len(captured)}."
            )

        features = captured[0]

    else:
        features = get_raw_yolo_logits(yolo_model, images)

    return pair_head(
        features[:batch_size],
        features[batch_size:],
        return_features=return_features,
    )


# ============================================================
# Build Pair Head from checkpoint
# ============================================================

def build_pair_head(
    checkpoint: Dict[str, Any],
    yolo_model: nn.Module,
) -> PairFusionHead:
    """Recreate the Pair Head architecture used by the saved checkpoint."""

    format_version = int(checkpoint.get("format_version", 1))
    if format_version not in (1, 2, 3):
        raise ValueError(
            f"Unsupported checkpoint format_version: {format_version}"
        )

    if "pair_head_state_dict" not in checkpoint:
        raise KeyError("Checkpoint missing pair_head_state_dict")
    if "num_classes" not in checkpoint:
        raise KeyError("Checkpoint missing num_classes")

    state = checkpoint["pair_head_state_dict"]
    source = checkpoint.get("feature_source", "logits")

    if source not in {"logits", "pooled"}:
        raise ValueError(f"Unsupported feature source: {source}")

    # Detect LayerNorm vs BatchNorm from saved state_dict.
    bn_keys = [
        "fusion.1.running_mean",
        "fusion.1.running_var",
    ]

    has_any_bn_key = any(key in state for key in bn_keys)
    has_all_bn_keys = all(key in state for key in bn_keys)

    if has_any_bn_key and not has_all_bn_keys:
        raise ValueError("Incomplete BatchNorm checkpoint")

    normalization = "batchnorm" if has_all_bn_keys else "layernorm"

    if source == "pooled":
        yolo_output_dim = get_classify_head(yolo_model).linear.in_features
    else:
        yolo_output_dim = int(checkpoint["num_classes"])

    head = PairFusionHead(
        yolo_output_dim=yolo_output_dim,
        num_classes=int(checkpoint["num_classes"]),
        feature_source=source,
        normalization=normalization,
    )

    head.load_state_dict(state, strict=True)
    head.crop_backgrounds = checkpoint.get("crop_backgrounds")

    camera_order = list(
        checkpoint.get("camera_order", ["cam0", "cam1"])
    )
    if camera_order != ["cam0", "cam1"]:
        raise ValueError(
            f"Unsupported camera order: {camera_order}; "
            "expected ['cam0', 'cam1']"
        )

    return head


# ============================================================
# Image preprocessing
# ============================================================

def make_eval_transform(imgsz: int):
    """Inference transform matching the pair validation transform."""
    return transforms.Compose(
        [
            transforms.Resize((imgsz, imgsz)),
            transforms.ToTensor(),
        ]
    )


def image_to_tensor(
    image_path: Path | str,
    transform,
    device: torch.device,
) -> torch.Tensor:
    path = Path(image_path)

    if not path.is_file():
        raise FileNotFoundError(f"Image not found: {path}")

    with Image.open(path) as image:
        image = image.convert("RGB")
        tensor = transform(image)

    return tensor.unsqueeze(0).to(
        device,
        non_blocking=True,
    )


def bgr_array_to_tensor(
    image: np.ndarray,
    transform,
    device: torch.device,
) -> torch.Tensor:
    """Convert an in-memory uint8 BGR frame without mutating the source."""
    if not isinstance(image, np.ndarray):
        raise TypeError(f"Expected numpy.ndarray, got {type(image)}")
    if image.dtype != np.uint8:
        raise ValueError(f"Expected uint8 frame, got {image.dtype}")
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected HxWx3 BGR frame, got {image.shape}")

    # Negative-stride RGB views are not accepted reliably by PIL/torchvision;
    # this copy is the model's private working image.  The camera frame stays
    # full-resolution BGR and is never resized or modified in place.
    rgb = image[:, :, ::-1].copy()
    tensor = transform(Image.fromarray(rgb))
    return tensor.unsqueeze(0).to(device, non_blocking=True)


def logits_to_prediction(
    logits: torch.Tensor,
    classes: List[str],
    top_k: int = 5,
) -> Dict[str, Any]:
    """Turn one pair-logit tensor into the established prediction schema."""
    if logits.ndim != 2 or logits.shape[0] != 1:
        raise ValueError(f"Expected logits shape [1,C], got {tuple(logits.shape)}")
    if logits.shape[1] != len(classes):
        raise ValueError(
            f"Logit count {logits.shape[1]} != class count {len(classes)}"
        )

    probabilities = torch.softmax(logits, dim=1)
    actual_top_k = min(max(1, int(top_k)), len(classes))
    top_confidences, top_indices = torch.topk(
        probabilities[0], k=actual_top_k
    )
    candidates = []
    for rank, (index_tensor, confidence_tensor) in enumerate(
        zip(top_indices, top_confidences), start=1
    ):
        class_index = int(index_tensor.item())
        candidates.append(
            {
                "rank": rank,
                "class_id": class_index,
                "name": classes[class_index],
                "confidence": float(confidence_tensor.item()),
            }
        )
    best = candidates[0]
    return {
        "prediction": best["name"],
        "class_id": best["class_id"],
        "confidence": best["confidence"],
        "candidates": candidates,
    }


# ============================================================
# Load complete Pair model
# ============================================================

def load_pair_model(
    checkpoint_path: Path | str,
    base_model_path: Path | str,
    device: torch.device | str = "cpu",
    verbose: bool = False,
) -> Tuple[
    nn.Module,
    PairFusionHead,
    List[str],
    int,
    Dict[str, Any],
]:
    """Load base YOLO architecture + trained pair checkpoint weights."""

    device = torch.device(device)
    checkpoint_path = Path(checkpoint_path).resolve()
    base_model_path = Path(base_model_path).resolve()

    if not checkpoint_path.is_file():
        raise FileNotFoundError(
            f"Pair checkpoint not found: {checkpoint_path}"
        )

    if not base_model_path.is_file():
        raise FileNotFoundError(
            f"Base YOLO model not found: {base_model_path}"
        )

    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )

    required_fields = {
        "classes",
        "num_classes",
        "yolo_state_dict",
        "pair_head_state_dict",
    }

    missing = required_fields.difference(checkpoint)
    if missing:
        raise RuntimeError(
            "Invalid pair checkpoint; missing fields: "
            + ", ".join(sorted(missing))
        )

    classes = [str(x) for x in checkpoint["classes"]]
    num_classes = int(checkpoint["num_classes"])

    if num_classes != len(classes):
        raise RuntimeError(
            f"Checkpoint num_classes={num_classes} but "
            f"len(classes)={len(classes)}"
        )

    camera_order = list(
        checkpoint.get("camera_order", ["cam0", "cam1"])
    )
    if camera_order != ["cam0", "cam1"]:
        raise RuntimeError(
            f"Unsupported camera order: {camera_order}"
        )

    if verbose:
        print(f"Loading base YOLO : {base_model_path}")
        print(f"Loading checkpoint: {checkpoint_path}")
        print(f"Classes           : {num_classes}")
        print(f"Feature source    : {checkpoint.get('feature_source', 'logits')}")

    yolo_model = YOLO(str(base_model_path)).model

    configure_yolo_classes(
        yolo_model,
        num_classes,
        verbose=verbose,
    )

    yolo_model.names = {
        index: class_name
        for index, class_name in enumerate(classes)
    }

    pair_head = build_pair_head(
        checkpoint,
        yolo_model,
    )

    yolo_model.load_state_dict(
        checkpoint["yolo_state_dict"],
        strict=True,
    )

    # build_pair_head already loads this state_dict, but reload explicitly
    # here for clarity and strict checkpoint validation.
    pair_head.load_state_dict(
        checkpoint["pair_head_state_dict"],
        strict=True,
    )

    yolo_model = yolo_model.to(device).eval()
    pair_head = pair_head.to(device).eval()
    # Keep inference models frozen; historical feature-analysis tools may also
    # reuse this exact trained Pair representation.
    # Explicitly disable gradients so training a downstream head can never
    # update the existing YOLO or Pair checkpoint parameters.
    for parameter in yolo_model.parameters():
        parameter.requires_grad_(False)
    for parameter in pair_head.parameters():
        parameter.requires_grad_(False)

    imgsz = int(checkpoint.get("imgsz", 640))

    return (
        yolo_model,
        pair_head,
        classes,
        imgsz,
        checkpoint,
    )


# ============================================================
# One-pair inference
# ============================================================

@torch.inference_mode()
def predict_pair(
    yolo_model: nn.Module,
    pair_head: PairFusionHead,
    classes: List[str],
    cam0_path: Path | str,
    cam1_path: Path | str,
    device: torch.device | str,
    imgsz: int = 640,
    top_k: int = 5,
) -> Dict[str, Any]:
    """Predict one ordered cam0/cam1 pair."""

    device = torch.device(device)
    transform = make_eval_transform(imgsz)

    cam0 = image_to_tensor(
        cam0_path,
        transform,
        device,
    )
    cam1 = image_to_tensor(
        cam1_path,
        transform,
        device,
    )

    logits = pair_forward(
        yolo_model,
        pair_head,
        cam0,
        cam1,
    )

    probabilities = torch.softmax(logits, dim=1)

    actual_top_k = min(
        max(1, int(top_k)),
        len(classes),
    )

    top_confidences, top_indices = torch.topk(
        probabilities[0],
        k=actual_top_k,
    )

    candidates = []

    for rank, (index_tensor, confidence_tensor) in enumerate(
        zip(top_indices, top_confidences),
        start=1,
    ):
        class_index = int(index_tensor.item())
        confidence = float(confidence_tensor.item())

        candidates.append(
            {
                "rank": rank,
                "class_id": class_index,
                "name": classes[class_index],
                "confidence": confidence,
            }
        )

    best = candidates[0]

    return {
        "prediction": best["name"],
        "class_id": best["class_id"],
        "confidence": best["confidence"],
        "candidates": candidates,
    }


# ============================================================
# Convenience wrapper
# ============================================================

class PairYoloPredictor:
    """Small reusable object for repeated pair inference."""

    def __init__(
        self,
        checkpoint_path: Path | str,
        base_model_path: Path | str,
        device: torch.device | str = "cpu",
        verbose: bool = False,
    ) -> None:
        self.device = torch.device(device)

        (
            self.yolo_model,
            self.pair_head,
            self.classes,
            self.imgsz,
            self.checkpoint,
        ) = load_pair_model(
            checkpoint_path=checkpoint_path,
            base_model_path=base_model_path,
            device=self.device,
            verbose=verbose,
        )

        self.transform = make_eval_transform(self.imgsz)

    @torch.inference_mode()
    def predict(
        self,
        cam0_path: Path | str,
        cam1_path: Path | str,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        cam0 = image_to_tensor(
            cam0_path,
            self.transform,
            self.device,
        )
        cam1 = image_to_tensor(
            cam1_path,
            self.transform,
            self.device,
        )

        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

        import time
        started = time.perf_counter()

        logits = pair_forward(
            self.yolo_model,
            self.pair_head,
            cam0,
            cam1,
        )
        probabilities = torch.softmax(logits, dim=1)

        actual_top_k = min(
            max(1, int(top_k)),
            len(self.classes),
        )

        top_confidences, top_indices = torch.topk(
            probabilities[0],
            k=actual_top_k,
        )

        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        candidates = []

        for rank, (index_tensor, confidence_tensor) in enumerate(
            zip(top_indices, top_confidences),
            start=1,
        ):
            class_index = int(index_tensor.item())
            candidates.append(
                {
                    "rank": rank,
                    "class_id": class_index,
                    "name": self.classes[class_index],
                    "confidence": float(confidence_tensor.item()),
                }
            )

        best = candidates[0]

        return {
            "prediction": best["name"],
            "class_id": best["class_id"],
            "confidence": best["confidence"],
            "candidates": candidates,
            "time_ms": elapsed_ms,
        }

    @torch.inference_mode()
    def predict_arrays(
        self,
        cam0_bgr: np.ndarray,
        cam1_bgr: np.ndarray,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Classify two in-memory BGR frames with one Pair forward pass."""
        cam0 = bgr_array_to_tensor(cam0_bgr, self.transform, self.device)
        cam1 = bgr_array_to_tensor(cam1_bgr, self.transform, self.device)
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        import time
        started = time.perf_counter()
        logits = pair_forward(self.yolo_model, self.pair_head, cam0, cam1)
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        prediction = logits_to_prediction(logits, self.classes, top_k=top_k)
        prediction.update({
            "time_ms": (time.perf_counter() - started) * 1000.0,
            "processing_resolution": [self.imgsz, self.imgsz],
        })
        return prediction

    @torch.inference_mode()
    def predict_arrays_with_features(
        self,
        cam0_bgr: np.ndarray,
        cam1_bgr: np.ndarray,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """Legacy research API: return Pair logits and hidden feature together."""
        cam0 = bgr_array_to_tensor(cam0_bgr, self.transform, self.device)
        cam1 = bgr_array_to_tensor(cam1_bgr, self.transform, self.device)

        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        import time
        started = time.perf_counter()
        logits, hidden = pair_forward(
            self.yolo_model,
            self.pair_head,
            cam0,
            cam1,
            return_features=True,
        )
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        prediction = logits_to_prediction(logits, self.classes, top_k=top_k)
        prediction.update(
            {
                "time_ms": elapsed_ms,
                "pair_logits": logits[0].detach().cpu().numpy(),
                "pair_feature": hidden[0].detach().cpu().numpy(),
                "processing_resolution": [self.imgsz, self.imgsz],
            }
        )
        return prediction

    @torch.inference_mode()
    def predict_array_batch_with_features(
        self,
        cam0_images: List[np.ndarray],
        cam1_images: List[np.ndarray],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Extract a batch with one shared frozen Pair forward."""
        if len(cam0_images) != len(cam1_images) or not cam0_images:
            raise ValueError("cam0/cam1 batches must be non-empty and equal length")
        cam0 = torch.cat([
            bgr_array_to_tensor(image, self.transform, self.device)
            for image in cam0_images
        ], dim=0)
        cam1 = torch.cat([
            bgr_array_to_tensor(image, self.transform, self.device)
            for image in cam1_images
        ], dim=0)
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        import time
        started = time.perf_counter()
        logits, hidden = pair_forward(
            self.yolo_model,
            self.pair_head,
            cam0,
            cam1,
            return_features=True,
        )
        if self.device.type == "cuda":
            torch.cuda.synchronize(self.device)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        per_pair_ms = elapsed_ms / len(cam0_images)
        results = []
        for index in range(len(cam0_images)):
            prediction = logits_to_prediction(
                logits[index:index + 1], self.classes, top_k=top_k
            )
            prediction.update({
                "time_ms": per_pair_ms,
                "batch_forward_time_ms": elapsed_ms,
                "pair_logits": logits[index].detach().cpu().numpy(),
                "pair_feature": hidden[index].detach().cpu().numpy(),
                "processing_resolution": [self.imgsz, self.imgsz],
            })
            results.append(prediction)
        return results


__all__ = [
    "PairFusionHead",
    "PairYoloPredictor",
    "bgr_array_to_tensor",
    "build_pair_head",
    "configure_yolo_classes",
    "get_classify_head",
    "get_raw_yolo_logits",
    "image_to_tensor",
    "load_pair_model",
    "logits_to_prediction",
    "make_eval_transform",
    "pair_forward",
    "predict_pair",
]
