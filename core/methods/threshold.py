"""Güvenlik paylı eşik yöntemi."""

from math import isfinite


def predict(dpu_c: float | None, margin_c: float) -> bool | None:
    if not isfinite(margin_c) or margin_c <= 0:
        raise ValueError("Güvenlik payı sonlu ve pozitif olmalı")
    if dpu_c is None or not isfinite(dpu_c) or dpu_c <= 0:
        return None
    return dpu_c < margin_c
