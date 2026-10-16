"""Patch PaddleOCR 2.7.x so its documented ir_optim option is respected.

PaddleOCR 2.7.3 parses ``ir_optim`` but unconditionally enables Paddle's IR
optimizer when creating every predictor.  Some CPUs/virtualized Docker hosts
then terminate in SelfAttentionFusePass with SIGILL.  Fail the image build if
the dependency source no longer has the exact expected implementation.
"""

from pathlib import Path
import sysconfig


def patch(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    old = "config.switch_ir_optim(True)"
    new = "config.switch_ir_optim(bool(getattr(args, 'ir_optim', True)))"
    occurrences = source.count(old)
    if occurrences != 1:
        raise RuntimeError(
            f"Expected exactly one PaddleOCR IR optimizer call in {path}; "
            f"found {occurrences}. Refusing an unsafe dependency patch."
        )
    path.write_text(source.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    utility = Path(sysconfig.get_paths()["purelib"]) / "paddleocr" / "tools" / "infer" / "utility.py"
    patch(utility)
    print(f"Patched PaddleOCR IR optimizer handling: {utility}")

