"""Offline source, artifact and Compose checks; does not replace Docker build."""
import ast
import hashlib
import json
import re
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parsed = 0
    for path in ROOT.rglob("*.py"):
        if ".test-deps" in path.parts or "__pycache__" in path.parts:
            continue
        ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        parsed += 1
    directory = ROOT / "yolo_service/legacy/ood_filter"
    config = json.loads((directory / "config.json").read_text())
    artifacts = {"feature_bank": directory / config["feature_bank"],
                 "pair_checkpoint": ROOT / "models/best_pair.pt", "base_model": ROOT / "models/yolo_best.pt"}
    for key, path in artifacts.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == config["sha256"][key], key
    with np.load(artifacts["feature_bank"], allow_pickle=False) as bank:
        assert bank["vectors"].shape == (1046, 256)
        assert len(bank["pair_ids"]) == len(bank["labels"]) == 1046
        assert np.isfinite(bank["vectors"]).all()
    for dockerfile in ["yolo_service/Dockerfile", "yolo_service/Dockerfile.gpu",
                       "ocr_service/Dockerfile", "ocr_service/Dockerfile.gpu"]:
        content = (ROOT / dockerfile).read_text()
        for source in re.findall(r"^COPY\s+(\S+)\s+", content, re.MULTILINE):
            assert (ROOT / source).exists(), (dockerfile, source)
    services = yaml.safe_load((ROOT / "docker-compose.yml").read_text())["services"]
    gpu = yaml.safe_load((ROOT / "docker-compose.gpu.yml").read_text())["services"]
    assert set(services) == {"database", "ocr", "yolo"}
    assert services["ocr"]["depends_on"]["yolo"]["condition"] == "service_healthy"
    for name in ["ocr", "yolo"]:
        assert services[name]["shm_size"] == "1gb"
        assert gpu[name]["deploy"]["resources"]["reservations"]["devices"][0]["capabilities"] == ["gpu"]
        assert (ROOT / gpu[name]["build"]["dockerfile"]).is_file()
    assert services["yolo"]["environment"]["OOD_CONFIG"] == "/app/legacy/ood_filter/config.json"
    manifest = json.loads((ROOT / "docs/drug-project-sync.json").read_text())
    for entry in manifest["deployed_files"]:
        path = ROOT / entry["destination"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["deployed_sha256"], entry["destination"]
    print(f"OK: {parsed} Python files parsed; 3 artifact hashes; 1046x256 feature bank; "
          f"4 Dockerfile COPY paths; CPU/GPU Compose structure; {len(manifest['deployed_files'])} source mappings")


if __name__ == "__main__":
    main()
