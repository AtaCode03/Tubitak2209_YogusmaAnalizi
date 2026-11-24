"""Güncel DPU ve geçmiş DPU eğimiyle doğrusal öngörü."""

from math import isfinite


def predict(dpu_c: float | None, slope_c_per_minute: float | None, horizon_minutes: int) -> bool | None:
    if not isfinite(horizon_minutes) or horizon_minutes <= 0:
        raise ValueError("Tahmin süresi sonlu ve pozitif olmalı")
    if dpu_c is None or not isfinite(dpu_c) or dpu_c <= 0:
        return None
    if slope_c_per_minute is None or not isfinite(slope_c_per_minute):
        return None
    return slope_c_per_minute < 0 and dpu_c + slope_c_per_minute * horizon_minutes < 0
