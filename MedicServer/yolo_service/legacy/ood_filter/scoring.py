from __future__ import annotations

from typing import Any

import numpy as np


class OODScoringError(RuntimeError):
    pass


def cosine_knn1(
    feature: np.ndarray,
    normalized_bank: np.ndarray,
    pair_ids: np.ndarray,
    labels: np.ndarray,
    threshold: float,
) -> dict[str, Any]:
    vector = np.asarray(feature, dtype=np.float32)
    if vector.shape != (256,):
        raise OODScoringError(f"Pair hidden feature shape is {vector.shape}, expected (256,)")
    if not np.isfinite(vector).all():
        raise OODScoringError("Pair hidden feature contains NaN or Inf")
    norm = float(np.linalg.norm(vector))
    if not np.isfinite(norm) or norm <= 0.0:
        raise OODScoringError("Pair hidden feature has invalid L2 norm")
    vector = vector / norm
    similarities = normalized_bank @ vector
    if not np.isfinite(similarities).all():
        raise OODScoringError("Cosine similarities contain NaN or Inf")
    nearest_index = int(np.argmax(similarities))
    score = float(similarities[nearest_index])
    decision = "REJECT" if score < float(threshold) else "PASS"
    return {
        "ood_status": decision,
        "ood_decision": decision,
        "ood_score": score,
        "ood_threshold": float(threshold),
        "ood_method": "cosine_knn1",
        "ood_nearest_pair_id": str(pair_ids[nearest_index]),
        "ood_nearest_label": str(labels[nearest_index]),
        "ood_error": None,
    }
