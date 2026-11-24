"""Kayıtlı ölçümleri özgün UTC sırasıyla okur."""

import csv
from datetime import datetime

from core.contracts import Measurement


def read_recording(path, series_id, limit):
    with path.open(encoding='utf-8', newline='') as stream:
        found = 0
        for row in csv.DictReader(stream):
            if row['series_id'] != series_id:
                continue
            timestamp = datetime.fromisoformat(row['timestamp'])
            measurement = None
            if row['valid'] == '1':
                measurement = Measurement(series_id, timestamp, float(row['air_temperature_c']),
                                          float(row['relative_humidity_pct']), float(row['surface_temperature_c']))
            yield timestamp, measurement
            found += 1
            if found == limit:
                return
