"""Özgün ölçüm zamanlarında kesintisiz negatif DPU olayları."""

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class Sample:
    timestamp: float
    dpu: float | None


@dataclass(frozen=True)
class Event:
    start: float
    confirmed: float
    end: float
    previous_nonnegative: float | None


def continuity_blocks(samples, gap_multiplier):
    """Geçersiz satırlar dahil özgün zamanlardan serinin ölçüm aralığını bul."""
    intervals = [b.timestamp - a.timestamp for a, b in zip(samples, samples[1:])]
    if any(interval <= 0 for interval in intervals):
        raise ValueError("Seri zamanları kesin artan sırada olmalı")
    nominal = median(intervals) if intervals else None
    limit = nominal * gap_multiplier if nominal is not None else 0
    blocks = []
    block = []
    for sample in samples:
        if block and (sample.dpu is None or sample.timestamp - block[-1].timestamp > limit):
            blocks.append(block)
            block = []
        if sample.dpu is not None:
            block.append(sample)
    if block:
        blocks.append(block)
    return nominal, blocks


def find_events(block, duration_seconds):
    events = []
    start = confirmed = end = previous_nonnegative = None
    for sample in block:
        if sample.dpu >= 0:
            if confirmed is not None:
                events.append(Event(start, confirmed, end, previous_nonnegative))
            start = confirmed = end = None
            previous_nonnegative = sample.timestamp
            continue
        if start is None:
            start = sample.timestamp
        end = sample.timestamp
        if confirmed is None and end - start >= duration_seconds:
            confirmed = end
    if confirmed is not None:
        events.append(Event(start, confirmed, end, previous_nonnegative))
    return events
