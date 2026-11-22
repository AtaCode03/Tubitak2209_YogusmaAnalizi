"""Hatalı kayıtları tahmin veya fizik hesabına geçirmeden reddeder."""

from datetime import datetime, timezone
from math import isfinite
from numbers import Real
from typing import Mapping

from core.contracts import Measurement


class MeasurementValidationError(ValueError):
    """Ölçüm sözleşmesine uymayan kayıt."""


def finite_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise MeasurementValidationError(f"{field}: sonlu bir sayı gerekli")
    result = float(value)
    if not isfinite(result):
        raise MeasurementValidationError(f"{field}: sonlu bir sayı gerekli")
    return result


def validate_measurement(measurement: Measurement) -> Measurement:
    if not isinstance(measurement, Measurement):
        raise MeasurementValidationError("Measurement nesnesi gerekli")
    if not isinstance(measurement.series_id, str) or not measurement.series_id.strip():
        raise MeasurementValidationError("series_id: boş olmayan metin gerekli")
    timestamp = measurement.timestamp
    if not isinstance(timestamp, datetime) or timestamp.utcoffset() is None:
        raise MeasurementValidationError("timestamp: saat dilimi bilgili tarih gerekli")
    air = finite_number(measurement.air_temperature_c, "air_temperature_c")
    rh = finite_number(measurement.relative_humidity_pct, "relative_humidity_pct")
    surface = finite_number(measurement.surface_temperature_c, "surface_temperature_c")
    if not 0 < rh <= 100:
        raise MeasurementValidationError("relative_humidity_pct: 0 < RH <= 100 olmalı")
    if air <= -273.15 or surface <= -273.15:
        raise MeasurementValidationError("Sıcaklık mutlak sıfırın üzerinde olmalı")
    return Measurement(measurement.series_id.strip(), timestamp.astimezone(timezone.utc), air, rh, surface)


def measurement_from_mapping(record: Mapping[str, object]) -> Measurement:
    fields = ("series_id", "timestamp", "air_temperature_c", "relative_humidity_pct", "surface_temperature_c")
    missing = [field for field in fields if field not in record]
    if missing:
        raise MeasurementValidationError("Eksik alanlar: " + ", ".join(missing))
    timestamp = record["timestamp"]
    if isinstance(timestamp, str):
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MeasurementValidationError("timestamp: geçersiz ISO 8601 tarih") from exc
    return validate_measurement(Measurement(
        series_id=record["series_id"], timestamp=timestamp,
        air_temperature_c=record["air_temperature_c"],
        relative_humidity_pct=record["relative_humidity_pct"],
        surface_temperature_c=record["surface_temperature_c"],
    ))
