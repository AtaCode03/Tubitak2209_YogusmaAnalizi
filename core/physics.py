"""Form Bölüm 2.2: Magnus çiğ noktası ve DPU hesabı."""

from math import isfinite, log

from core.contracts import ComputedMeasurement, Measurement
from core.validation import MeasurementValidationError, finite_number, validate_measurement

MAGNUS_A = 17.625
MAGNUS_B_C = 243.04


def dew_point_c(air_temperature_c: float, relative_humidity_pct: float) -> float:
    air = finite_number(air_temperature_c, "air_temperature_c")
    rh = finite_number(relative_humidity_pct, "relative_humidity_pct")
    if not 0 < rh <= 100:
        raise MeasurementValidationError("relative_humidity_pct: 0 < RH <= 100 olmalı")
    if air <= -MAGNUS_B_C:
        raise MeasurementValidationError("Sıcaklık Magnus hesap alanı dışında")
    if rh == 100:
        return air
    gamma = log(rh / 100.0) + MAGNUS_A * air / (MAGNUS_B_C + air)
    denominator = MAGNUS_A - gamma
    if denominator == 0:
        raise MeasurementValidationError("Magnus hesabının paydası sıfır")
    result = MAGNUS_B_C * gamma / denominator
    if not isfinite(result):
        raise MeasurementValidationError("Çiğ noktası sonlu hesaplanamadı")
    return result


def calculate_measurement(measurement: Measurement) -> ComputedMeasurement:
    valid = validate_measurement(measurement)
    dew = dew_point_c(valid.air_temperature_c, valid.relative_humidity_pct)
    return ComputedMeasurement(valid, dew, valid.surface_temperature_c - dew)
