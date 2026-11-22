import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_default_measurement_submission(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        app.button[0].click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.metric[0].value, "9.261 °C")
        self.assertEqual(app.metric[1].value, "-1.261 °C")
        self.assertEqual(app.info[0].value, "Mevcut yoğuşma riski")

    def test_invalid_temperature_shows_error(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.run(timeout=30)
        app.number_input[0].set_value(-300.0)
        app.button[0].click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertEqual(len(app.metric), 0)


if __name__ == "__main__":
    unittest.main()
