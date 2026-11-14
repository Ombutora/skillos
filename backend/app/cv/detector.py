"""Object detector interface.

YOLO runs only when `ultralytics` is installed AND SKILLOS_YOLO_WEIGHTS points
to weights trained on solar components. Stock COCO weights do not know solar
panels, charge controllers or MC4 connectors, so they are not used as a
silent fallback. Detections are hints for the observation agent; they never
verify a step on their own (see validation.evidence).
"""

import os
from functools import lru_cache


@lru_cache
def _model():
    weights = os.getenv("SKILLOS_YOLO_WEIGHTS")
    if not weights or not os.path.exists(weights):
        return None
    try:
        from ultralytics import YOLO
    except ImportError:
        return None
    return YOLO(weights)


def detector_status() -> dict:
    m = _model()
    return {"available": m is not None,
            "reason": None if m else "set SKILLOS_YOLO_WEIGHTS to solar-component weights and install ultralytics"}


def detect(image_path: str, min_conf: float = 0.4) -> list[dict]:
    m = _model()
    if m is None:
        return []
    res = m.predict(image_path, conf=min_conf, verbose=False)[0]
    names = res.names
    return [{"label": names[int(b.cls)], "confidence": float(b.conf), "box": [float(x) for x in b.xyxy[0]]}
            for b in res.boxes]
