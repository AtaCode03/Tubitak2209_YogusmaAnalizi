import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest


class AppTests(unittest.TestCase):
    def test_default_measurement_submission(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        next(button for button in app.button if button.label == 'Hesapla').click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertIn("9.261 °C", [metric.value for metric in app.metric])
        self.assertIn("-1.261 °C", [metric.value for metric in app.metric])
        self.assertIn("Mevcut yoğuşma riski", [notice.value for notice in app.info])

    def test_invalid_temperature_shows_error(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"))
        app.run(timeout=30)
        app.number_input[0].set_value(-300.0)
        next(button for button in app.button if button.label == 'Hesapla').click().run(timeout=30)
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(len(app.error), 1)
        self.assertNotIn('9.261 °C', [metric.value for metric in app.metric])

    def test_other_screens_open(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'app.py')).run(timeout=30)
        for page in ('Deney yönetimi', 'Geçmiş kayıtlar', 'Yöntem karşılaştırması'):
            with self.subTest(page=page):
                app.sidebar.radio[0].set_value(page).run(timeout=30)
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.title[0].value, page)


if __name__ == "__main__":
    unittest.main()
