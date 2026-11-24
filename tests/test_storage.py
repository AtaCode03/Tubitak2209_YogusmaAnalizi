import csv
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from core.contracts import Measurement
from core.physics import calculate_measurement
from storage.database import connect, initialize, initialize_schema
from storage.export_csv import export_experiment
from storage.repositories import (add_event, add_measurement, add_prediction, create_experiment,
                                  finish_experiment, get_or_create_setting, mark_first_display, utc_text)

START = datetime(2026, 11, 24, 12, tzinfo=timezone(timedelta(hours=3)))


def example_measurement(time):
    return calculate_measurement(Measurement('example', time, 10, 90, 9))


class StorageTests(unittest.TestCase):
    def test_join_export_and_first_warning_display(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            with connect(':memory:') as db:
                initialize_schema(db)
                experiment = create_experiment(db, 'example', START)
                add_event(db, experiment, 'lid_open', START)
                measurement = add_measurement(db, experiment, example_measurement(START))
                later = START + timedelta(minutes=5)
                add_measurement(db, experiment, example_measurement(later))
                threshold = get_or_create_setting(db, 'threshold', {'margin_c': 1}, 5)
                self.assertEqual(get_or_create_setting(db, 'threshold', {'margin_c': 1}, 5), threshold)
                linear = get_or_create_setting(db, 'linear', {'window_minutes': 5}, 5)
                alarm = add_prediction(db, measurement, threshold, START, True)
                no_alarm = add_prediction(db, measurement, linear, START, False)
                self.assertTrue(mark_first_display(db, alarm, START + timedelta(seconds=2)))
                self.assertFalse(mark_first_display(db, alarm, later))
                self.assertFalse(mark_first_display(db, no_alarm, later))
                self.assertTrue(finish_experiment(db, experiment, later))
                measurements, events = export_experiment(db, experiment, output, START, later)
            with measurements.open(encoding='utf-8-sig', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([row['method'] for row in rows], ['threshold', 'linear'])
            self.assertEqual(rows[0]['first_displayed_at'], '2026-11-24T09:00:02.000000+00:00')
            self.assertEqual(rows[1]['first_displayed_at'], '')
            with events.open(encoding='utf-8-sig', newline='') as stream:
                self.assertEqual(next(csv.DictReader(stream))['event_type'], 'lid_open')

    def test_missing_parent_is_rejected_and_failed_transaction_rolls_back(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.sqlite3'
            initialize(path)
            initialize(path)
            with self.assertRaises(sqlite3.IntegrityError), connect(path) as db:
                create_experiment(db, 'example', START)
                add_measurement(db, 999, example_measurement(START))
            with connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM experiments').fetchone()[0], 0)
                setting = get_or_create_setting(db, 'threshold', {'margin_c': 1}, 5)
                with self.assertRaises(sqlite3.IntegrityError):
                    add_prediction(db, 999, setting, START, True)

    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            utc_text(START.replace(tzinfo=None))
