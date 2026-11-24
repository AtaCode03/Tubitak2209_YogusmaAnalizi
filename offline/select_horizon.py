"""Başvuru §2.6: ortak tahmin süresi T4 olayları üzerinden seçilir."""

import argparse
import csv
import gzip
import json
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path

from offline.split_data import RESEARCH_CONFIG

ROOT = RESEARCH_CONFIG.parents[1]
METHODS = ('threshold', 'linear', 'random_forest')
T4_DIR = ROOT / 'data/processed/parameter_search'
EVENTS = ROOT / 'data/processed/risk_events.csv'


def load_interventions(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 5 or {row.get('trial') for row in rows} != {'1', '2', '3', '4', '5'}:
        raise ValueError('1–5 numaralı beş müdahale ölçümü gerekli')
    times = []
    for row in sorted(rows, key=lambda item: item['trial']):
        try:
            seconds = Decimal(row.get('seconds') or '')
        except InvalidOperation as exc:
            raise ValueError('Müdahale sürelerini saniye olarak girin; ondalık ayırıcı nokta') from exc
        if not seconds.is_finite() or seconds <= 0:
            raise ValueError('Müdahale süreleri sonlu ve pozitif olmalı')
        times.append(seconds)
    return times


def load_t4(predictions, events, event_duration_seconds, horizons):
    grouped = {h: defaultdict(dict) for h in horizons}
    with gzip.open(predictions, 'rt', encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            horizon = int(row['horizon_minutes'])
            timestamp = datetime.fromisoformat(row['timestamp'])
            grouped[horizon][row['series_id']][timestamp] = tuple(row[m] == '1' for m in METHODS)
    with events.open(encoding='utf-8', newline='') as stream:
        reference = [(row['series_id'], datetime.fromisoformat(row['start_utc'])) for row in csv.DictReader(stream)
                     if row['partition'] == 'validation' and int(row['duration_seconds']) == event_duration_seconds]
    return grouped, reference


def eligible_events(predictions, events):
    if not predictions:
        return []
    shortest = min(predictions)
    common = {}
    for series, rows in predictions[shortest].items():
        shared = set(rows)
        for by_series in predictions.values():
            shared.intersection_update(by_series.get(series, {}))
        common[series] = sorted(shared)
    selected = []
    for series, onset in events:
        times = common.get(series, ())
        index = bisect_left(times, onset - timedelta(minutes=5))
        if index < len(times) and times[index] < onset:
            selected.append((series, onset))
    return selected


def select(predictions, events, selected_results, minimum_seconds):
    eligible = eligible_events(predictions, events)
    candidates = {}
    ranked = []
    for horizon, by_series in predictions.items():
        alarms = [selected_results[str(horizon)]['selected'][m]['metrics']['false_alarms_per_24_sensor_hours']
                  for m in METHODS]
        if any(value is None for value in alarms):
            raise ValueError(f'{horizon} dk için T4 yanlış alarm oranı tanımsız')
        mean_alarms = sum(Decimal(str(value)) for value in alarms) / len(METHODS)
        counts = dict.fromkeys(METHODS, 0)
        ordered = {series: sorted(rows) for series, rows in by_series.items()}
        for series, onset in eligible:
            rows = by_series[series]
            times = ordered[series]
            left = bisect_left(times, onset - timedelta(minutes=horizon))
            right = bisect_left(times, onset)
            first = {}
            for time in times[left:right]:
                for method, warning in zip(METHODS, rows[time], strict=True):
                    if warning and method not in first:
                        first[method] = time
            for method, time in first.items():
                if Decimal(str((onset - time).total_seconds())) >= minimum_seconds:
                    counts[method] += 1
        mean_rate = Fraction(sum(counts.values()), len(METHODS) * len(eligible)) if eligible else None
        candidates[str(horizon)] = dict(timely_warning_counts=counts, mean_timely_warning_rate=float(mean_rate)
                                        if mean_rate is not None else None, mean_false_alarms_per_24_sensor_hours=float(mean_alarms))
        ranked.append((mean_rate if mean_rate is not None else Fraction(0), -mean_alarms, -horizon))
    selected = -max(ranked)[-1]
    return dict(selected_horizon_minutes=selected, minimum_intervention_seconds=float(minimum_seconds),
                eligible_t4_events=len(eligible), no_common_event_fallback=not eligible, candidates=candidates)


def inputs():
    config = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    predictions, events = load_t4(T4_DIR / 'selected_t4_predictions.csv.gz', EVENTS,
                                  config['event_min_duration_seconds'], config['horizons_minutes'])
    report = json.loads((T4_DIR / 'parameter_search_report.json').read_text(encoding='utf-8'))
    return predictions, events, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interventions', type=Path)
    args = parser.parse_args()
    predictions, events, report = inputs()
    if args.interventions is None:
        print(json.dumps({'t4_risk_events': len(events), 'common_event_candidates': len(eligible_events(predictions, events)),
                          'selected_horizon_minutes': None, 'note': 'Five physical measurements required'}, indent=2))
        return
    times = load_interventions(args.interventions)
    result = select(predictions, events, report['by_horizon_minutes'], max(times) + Decimal(30))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
