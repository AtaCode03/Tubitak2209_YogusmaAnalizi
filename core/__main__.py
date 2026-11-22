"""Sanal ortamın Python'u ile çalıştır: python -m core."""

import json

from core.physics import calculate_measurement
from core.validation import measurement_from_mapping


def main() -> None:
    measurement = measurement_from_mapping({
        "series_id": "demo",
        "timestamp": "2026-11-21T09:00:00Z",
        "air_temperature_c": 20.0,
        "relative_humidity_pct": 50.0,
        "surface_temperature_c": 8.0,
    })
    result = calculate_measurement(measurement)
    print(json.dumps({
        "series_id": result.measurement.series_id,
        "timestamp": result.measurement.timestamp.isoformat(),
        "dew_point_c": result.dew_point_c,
        "dpu_c": result.dpu_c,
        "current_status": result.current_status,
        "note": "Örnek ölçüm hesabıdır; erken uyarı tahmini değildir.",
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
