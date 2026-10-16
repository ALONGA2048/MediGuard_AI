"""Per-group bounded tracing; never retain image/tensor references."""
import contextvars
import time
import traceback
from contextlib import contextmanager

_trace = contextvars.ContextVar("ocr_trace", default=None)
_image = contextvars.ContextVar("ocr_image", default=None)


def exception_details(error):
    return {"exception_type": type(error).__name__, "exception_message": str(error),
            "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))}


@contextmanager
def capture(trace):
    token = _trace.set(trace)
    try:
        yield
    finally:
        _trace.reset(token)


@contextmanager
def span(stage, image=None):
    trace = _trace.get()
    token = _image.set(str(image)) if image is not None else None
    event = {"stage": stage, "image": _image.get()}
    started = time.perf_counter()
    try:
        yield event
    except Exception as error:
        event.update(exception_details(error))
        if not hasattr(error, "ocr_stage"):
            error.ocr_stage = stage
        if trace is not None:
            trace["error_stage"] = error.ocr_stage
        raise
    finally:
        event["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        if trace is not None:
            trace.setdefault("events", []).append(event)
        if token is not None:
            _image.reset(token)


def record_exception(stage, error):
    trace = _trace.get()
    event = {"stage": stage, "image": _image.get(), **exception_details(error)}
    if trace is not None:
        trace.setdefault("warnings", []).append(event)
    else:
        import logging
        logging.getLogger(__name__).warning("%s: %s", stage, error, exc_info=True)
