"""Ortak UTC adımlarında yalnızca o ana kadar bilinen ölçümler."""

from collections import deque
from math import ceil, sqrt

VARIABLES = ('air_temperature_c', 'relative_humidity_pct', 'surface_temperature_c', 'dpu_c')
STATISTICS = ('current', 'mean', 'std', 'delta', 'slope_per_minute')
FEATURE_NAMES = tuple(f'{variable}_{stat}' for variable in VARIABLES for stat in STATISTICS)


def summarize(points, step_seconds):
    center = (len(points) - 1) / 2
    offsets = [(i - center) * step_seconds / 60 for i in range(len(points))]
    denominator = sum(offset * offset for offset in offsets)
    result = []
    for values in zip(*points, strict=True):
        mean = sum(values) / len(values)
        std = sqrt(sum((value - mean) ** 2 for value in values) / len(values))
        slope = sum(offset * (value - mean) for offset, value in zip(offsets, values)) / denominator
        result.extend((values[-1], mean, std, values[-1] - values[0], slope))
    return tuple(result)


class WindowGrid:
    """Her ölçüm geldikçe geçmiş pencereleri günceller."""

    def __init__(self, step_seconds, windows_minutes, max_age_seconds):
        if step_seconds <= 0 or not windows_minutes or any(
                w * 60 < step_seconds or w * 60 % step_seconds for w in windows_minutes):
            raise ValueError('Pencere süresi pozitif tam grid adımlarından oluşmalı')
        self.step = step_seconds
        self.max_age = max_age_seconds
        self.sizes = {w: w * 60 // step_seconds + 1 for w in windows_minutes}
        self.history = deque(maxlen=max(self.sizes.values()))
        self.reset()

    def reset(self):
        self.history.clear()
        self.previous = self.tick = None

    def _evaluate(self):
        tick = self.tick
        self.tick += self.step
        time, values, source = self.previous
        if tick - time > self.max_age:
            self.history.clear()
            return tick, None, {}, source
        self.history.append(values)
        features = {}
        if values[-1] > 0:
            points = list(self.history)
            features = {w: summarize(points[-size:], self.step)
                        for w, size in self.sizes.items() if len(points) >= size}
        return tick, values, features, source

    def feed(self, timestamp, values, source=None):
        if self.previous is not None:
            if timestamp <= self.previous[0]:
                raise ValueError('Ölçüm zamanları kesin artan sırada olmalı')
            while self.tick < timestamp:
                yield self._evaluate()
        else:
            self.tick = ceil(timestamp / self.step) * self.step
        self.previous = timestamp, values, source
        if self.tick == timestamp:
            yield self._evaluate()


def grid_windows(readings, step_seconds, windows_minutes, max_age_seconds):
    """Tek bir kesintisiz ölçüm bloğunun adımlarını üretir."""
    grid = WindowGrid(step_seconds, windows_minutes, max_age_seconds)
    for timestamp, values in readings:
        for tick, current, features, _ in grid.feed(timestamp, values):
            yield tick, current, features
