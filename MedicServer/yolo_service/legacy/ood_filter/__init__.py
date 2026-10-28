"""Production cosine kNN1 OOD gate built on the frozen Pair-YOLO model.

Torch is imported lazily so the parent coordinator does not load CUDA/PyTorch
beside PaddleOCR. The Pair-OOD worker owns the PyTorch runtime.
"""

__all__ = ["CosineKNN1OODFilter", "OODCompatibilityError", "load_ood_config"]


def __getattr__(name):
    if name in __all__:
        from .service import CosineKNN1OODFilter, OODCompatibilityError, load_ood_config
        return {
            "CosineKNN1OODFilter": CosineKNN1OODFilter,
            "OODCompatibilityError": OODCompatibilityError,
            "load_ood_config": load_ood_config,
        }[name]
    raise AttributeError(name)
