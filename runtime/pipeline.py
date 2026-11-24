"""Bir ölçüm akışını hesaplar, tahmin eder ve deneyle ilişkilendirir."""

from collections import Counter
from datetime import datetime, timezone

from core.methods import linear_trend, random_forest, threshold
from core.physics import calculate_measurement
from core.windows import FEATURE_NAMES, WindowGrid
from storage.repositories import add_measurement, add_prediction

DPU_SLOPE = FEATURE_NAMES.index('dpu_c_slope_per_minute')


class Pipeline:
    def __init__(self, db, experiment_id, settings, model, step_seconds, maximum_age):
        self.db = db
        self.experiment_id = experiment_id
        self.settings = settings
        self.model = model
        self.maximum_age = maximum_age
        self.previous_time = None
        self.counts = Counter()
        windows = sorted({settings[m]['parameters']['window_minutes'] for m in ('linear', 'random_forest')})
        self.grid = WindowGrid(step_seconds, windows, maximum_age)

    def interrupt(self):
        self.grid.reset()
        self.previous_time = None
        self.counts['interruptions'] += 1

    def ingest(self, timestamp, measurement):
        now = timestamp.timestamp()
        if self.previous_time is not None and now <= self.previous_time:
            raise ValueError('Akış zamanları kesin artan sırada olmalı')
        if self.previous_time is not None and now - self.previous_time > self.maximum_age:
            self.grid.reset()
            self.counts['long_gaps'] += 1
        self.previous_time = now
        if measurement is None:
            self.grid.reset()
            self.counts['invalid_rows'] += 1
            return
        if measurement.timestamp != timestamp:
            raise ValueError('Ölçüm ve akış zamanları eşleşmiyor')
        result = calculate_measurement(measurement)
        measurement_id = add_measurement(self.db, self.experiment_id, result)
        self.counts['stored_measurements'] += 1
        values = (measurement.air_temperature_c, measurement.relative_humidity_pct,
                  measurement.surface_temperature_c, result.dpu_c)
        for tick, current, windows, source in self.grid.feed(now, values, measurement_id):
            if current is None or current[-1] <= 0:
                continue
            self._predict(tick, current[-1], windows, source)

    def _predict(self, tick, dpu, windows, measurement_id):
        threshold_setting = self.settings['threshold']
        linear_setting = self.settings['linear']
        forest_setting = self.settings['random_forest']
        linear = windows.get(linear_setting['parameters']['window_minutes'])
        forest = windows.get(forest_setting['parameters']['window_minutes'])
        decisions = {
            'threshold': threshold.predict(dpu, threshold_setting['parameters']['margin_c']),
            'linear': linear_trend.predict(dpu, linear[DPU_SLOPE] if linear is not None else None, linear_setting['horizon']),
            'random_forest': random_forest.predict(self.model, forest, dpu),
        }
        for method, risk in decisions.items():
            if risk is None:
                self.counts[f'{method}_waiting'] += 1
                continue
            add_prediction(self.db, measurement_id, self.settings[method]['id'],
                           datetime.fromtimestamp(tick, timezone.utc), risk)
            self.counts[f'{method}_predictions'] += 1
            if risk:
                self.counts[f'{method}_warnings'] += 1
