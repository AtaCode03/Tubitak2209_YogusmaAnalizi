import unittest
from datetime import datetime, timedelta, timezone

from core.contracts import Measurement
from core.physics import calculate_measurement, dew_point_c
from core.validation import MeasurementValidationError, measurement_from_mapping, validate_measurement


class PhysicsTests(unittest.TestCase):
    def sample(self, **changes):
        values = dict(series_id="sensor-1", timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      air_temperature_c=20.0, relative_humidity_pct=50.0, surface_temperature_c=8.0)
        values.update(changes)
        return Measurement(**values)

    def test_known_reference(self):
        result = calculate_measurement(self.sample())
        self.assertAlmostEqual(result.dew_point_c, 9.2611, places=3)
        self.assertAlmostEqual(result.dpu_c, -1.2611, places=3)
        self.assertEqual(result.current_status, "Mevcut yoğuşma riski")

    def test_saturated_air(self):
        for temperature in (-10.0, 0.0, 5.0, 20.0):
            with self.subTest(temperature=temperature):
                self.assertEqual(dew_point_c(temperature, 100), temperature)
                result = calculate_measurement(self.sample(air_temperature_c=temperature,
                                                          relative_humidity_pct=100,
                                                          surface_temperature_c=temperature))
                self.assertEqual(result.dpu_c, 0)
                self.assertEqual(result.current_status, "Risk sınırında")

    def test_boundary_and_positive_status(self):
        result = calculate_measurement(self.sample(air_temperature_c=0, relative_humidity_pct=100, surface_temperature_c=0))
        self.assertEqual(result.dpu_c, 0)
        self.assertEqual(result.current_status, "Risk sınırında")
        self.assertEqual(calculate_measurement(self.sample(surface_temperature_c=15)).current_status, "Mevcut DPU pozitif")

    def test_invalid_humidity(self):
        for humidity in (0, -1, 101, float("nan"), float("inf"), None, True, "50"):
            with self.subTest(humidity=humidity), self.assertRaises(MeasurementValidationError):
                calculate_measurement(self.sample(relative_humidity_pct=humidity))

    def test_invalid_temperatures(self):
        for field in ("air_temperature_c", "surface_temperature_c"):
            for value in (None, float("nan"), float("inf"), -273.15, False):
                with self.subTest(field=field, value=value), self.assertRaises(MeasurementValidationError):
                    calculate_measurement(self.sample(**{field: value}))

    def test_magnus_singularity(self):
        with self.assertRaises(MeasurementValidationError):
            dew_point_c(-243.04, 50)

    def test_missing_field(self):
        with self.assertRaisesRegex(MeasurementValidationError, "Eksik alanlar"):
            measurement_from_mapping({"series_id": "a"})

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(MeasurementValidationError):
            validate_measurement(self.sample(timestamp=datetime(2026, 1, 1)))

    def test_utc_normalization(self):
        local = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=3)))
        result = validate_measurement(self.sample(timestamp=local))
        self.assertEqual(result.timestamp.hour, 9)
        self.assertEqual(result.timestamp.tzinfo, timezone.utc)

    def test_iso_record(self):
        result = measurement_from_mapping(dict(series_id="a", timestamp="2026-01-01T12:00:00+03:00",
                                              air_temperature_c=20, relative_humidity_pct=50, surface_temperature_c=8))
        self.assertEqual(result.timestamp.hour, 9)

    def test_bad_id_and_timestamp(self):
        for changes in ({"series_id": " "}, {"timestamp": "not-a-date"}):
            with self.subTest(changes=changes), self.assertRaises(MeasurementValidationError):
                validate_measurement(self.sample(**changes))


if __name__ == "__main__":
    unittest.main()
