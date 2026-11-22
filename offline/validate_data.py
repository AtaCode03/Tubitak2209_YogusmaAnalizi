"""Ham sayısal değerleri ortak ölçüm sözleşmesine dönüştürür."""

from datetime import datetime, timezone

from core.contracts import Measurement
from core.physics import calculate_measurement
from core.validation import MeasurementValidationError


def parse_timestamp(raw: str) -> datetime:
    return datetime.fromtimestamp(float(raw), tz=timezone.utc)


def parse_values(series_id, timestamp, air, surface, humidity):
    fields = (air, surface, humidity)
    if any(not value.strip() or value.strip().lower() == "nan" for value in fields):
        return None, "missing_measurement"
    try:
        measurement = Measurement(series_id, timestamp, float(air), float(humidity), float(surface))
        return calculate_measurement(measurement), ""
    except MeasurementValidationError:
        return None, "invalid_measurement"
    except ValueError:
        return None, "invalid_number"
