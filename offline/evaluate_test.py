"""Sabitlenmiş yöntemleri bağımsız T5 kayıtlarında değerlendirir."""

import argparse
import csv
import gzip
import json
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median

import numpy as np

from core.methods import linear_trend, threshold
from core.windows import FEATURE_NAMES, grid_windows
from offline.bootstrap import time_block_analysis
from offline.build_samples import series
from offline.events import Sample, continuity_blocks, find_events
from offline.freeze_configuration import DEFAULT_FROZEN, load_frozen_setup, sha256
from offline.import_data import publish_file
from offline.labels import label_at, utc
from offline.metrics import ratio, score
from offline.select_horizon import METHODS
from runtime.worker import ROOT

DPU_SLOPE = FEATURE_NAMES.index('dpu_c_slope_per_minute')


def series_grid(measurements, config, break_times=()):
    duration = config['event_min_duration_seconds']
    alternatives = config['alternative_event_durations_seconds']
    horizons = config['horizons_minutes']
    factor = config['max_measurement_age_median_multiplier']
    nominal, blocks = continuity_blocks([Sample(t, values[-1] if values else None)
                                         for t, values in measurements.items()], factor)
    events = []
    grid = []
    counts = {value: {'events': 0, 'labels': {h: {'positive': 0, 'negative': 0, 'unknown': 0} for h in horizons}}
              for value in (duration, *alternatives)}
    if nominal is None:
        return grid, events, counts
    for block in split_at_breaks(blocks, break_times):
        event_sets = {value: find_events(block, value) for value in counts}
        events.extend(event_sets[duration])
        for value, found in event_sets.items():
            counts[value]['events'] += len(found)
        starts = {value: [event.start for event in found] for value, found in event_sets.items()}
        end = block[-1].timestamp
        readings = ((sample.timestamp, measurements[sample.timestamp]) for sample in block)
        for tick, values, windows in grid_windows(readings, config['prediction_step_seconds'],
                                                  config['windows_minutes'], nominal * factor):
            if values is None or values[-1] <= 0:
                continue
            labels = {}
            for value in counts:
                for h in horizons:
                    label, _ = label_at(tick, h * 60, value, end, None, starts[value])
                    field = 'unknown' if label is None else 'positive' if label else 'negative'
                    counts[value]['labels'][h][field] += 1
                    if value == duration:
                        labels[h] = label
            grid.append((tick, values[-1], windows, labels))
    return grid, events, counts


def split_at_breaks(blocks, break_times):
    breaks = sorted(break_times)
    for block in blocks:
        start = 0
        for index in range(1, len(block)):
            left = bisect_right(breaks, block[index - 1].timestamp)
            if left < len(breaks) and breaks[left] <= block[index].timestamp:
                yield block[start:index]
                start = index
        yield block[start:]


def predict_grid(grid, h, setup, window_count):
    selected, model = setup
    margin = selected['threshold']['parameters']['margin_c']
    linear_window = selected['linear']['parameters']['window_minutes']
    forest_window = selected['random_forest']['parameters']['window_minutes']
    features = [windows[forest_window] for _, _, windows, _ in grid if forest_window in windows]
    forest = iter(model.predict(np.asarray(features, dtype=np.float32))) if features else iter(())
    for time, dpu, windows, labels in grid:
        slope = windows[linear_window][DPU_SLOPE] if linear_window in windows else None
        decisions = (threshold.predict(dpu, margin), linear_trend.predict(dpu, slope, h),
                     bool(next(forest)) if forest_window in windows else None)
        yield time, labels[h], len(windows) == window_count, decisions


def event_results(events, times, decisions, horizon, minimum_seconds):
    leads = []
    eligible = []
    conservative_success = 0
    for event in events:
        left = bisect_left(times, event.start - horizon * 60)
        right = bisect_left(times, event.start)
        if left == right:
            continue
        eligible.append(event)
        first = next((times[i] for i in range(left, right) if decisions[i]), None)
        if first is not None:
            leads.append(event.start - first)
            if event.previous_nonnegative is not None and event.previous_nonnegative - first >= minimum_seconds:
                conservative_success += 1
    timely = sum(lead >= minimum_seconds for lead in leads)
    return dict(eligible=len(eligible), warned=len(leads), timely=timely, missed=len(eligible) - len(leads),
                median_lead_seconds=median(leads) if leads else None,
                timely_using_last_nonnegative=conservative_success), eligible, leads


def add_event_counts(total, current):
    for name in ('eligible', 'warned', 'timely', 'missed', 'timely_using_last_nonnegative'):
        total[name] = total.get(name, 0) + current[name]


def compare_horizons(all_rows, events_by_series, minimum):
    by_series = {h: defaultdict(dict) for h in all_rows}
    for h, rows in all_rows.items():
        for series_id, time, label, predictions in rows:
            by_series[h][series_id][time] = (label, predictions)
    comparisons = {h: {m: dict(eligible=0, missed=0, timely=0, tp=0, fp=0) for m in METHODS} for h in all_rows}
    for key, events in events_by_series.items():
        common_times = sorted(set.intersection(*(set(data.get(key, {})) for data in by_series.values())))
        common_events = []
        for event in events:
            left = bisect_left(common_times, event.start - 300)
            if left < len(common_times) and common_times[left] < event.start:
                common_events.append(event)
        for h, data in by_series.items():
            records = data.get(key, {})
            times = sorted(records)
            for idx, method in enumerate(METHODS):
                decisions = [records[time][1][idx] for time in times]
                result, _, _ = event_results(common_events, times, decisions, h, minimum)
                aggregate = comparisons[h][method]
                for field in ('eligible', 'missed', 'timely'):
                    aggregate[field] += result[field]
                for time in common_times:
                    label, forecast = records[time]
                    if forecast[idx]:
                        aggregate['tp' if label else 'fp'] += 1
    for rows in comparisons.values():
        for values in rows.values():
            values['shared_step_precision'] = ratio(values['tp'], values['tp'] + values['fp'])
            values['shared_event_timely_rate'] = ratio(values['timely'], values['eligible'])
    return comparisons


def overlap_groups(events_by_series):
    groups = []
    for start, end, key in sorted((event.start, event.end, key)
                                  for key, events in events_by_series.items() for event in events):
        if not groups or start > groups[-1]['end']:
            groups.append(dict(start=start, end=end, series={key}, series_events=1))
        else:
            group = groups[-1]
            group['end'] = max(end, group['end'])
            group['series'].add(key)
            group['series_events'] += 1
    return [dict(start_utc=utc(g['start']), last_negative_utc=utc(g['end']), series=sorted(g['series']),
                 series_events=g['series_events']) for g in groups]


def evaluate(test_file, frozen, output):
    manifest_path = frozen / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    chosen = manifest['selected']['selected_horizon_minutes']
    minimum = manifest['selected']['minimum_intervention_seconds']
    configs = {}
    for h in (5, 10, 15):
        _, selected, model, _, _, config = load_frozen_setup(frozen, h)
        configs[h] = (selected, model)
    start = datetime.fromisoformat(config['split']['test_start_utc']).timestamp()
    observed_end = start
    all_rows = {h: [] for h in configs}
    event_counts = {h: {m: {} for m in METHODS} for h in configs}
    lead_times = {h: {m: [] for m in METHODS} for h in configs}
    warnings_outside = {h: {m: dict(unknown_reference=0, insufficient_common_history=0) for m in METHODS} for h in configs}
    eligible_starts = []
    reference_counts = {}
    events_by_series = {}
    output.mkdir(parents=True, exist_ok=True)
    csv_path = output / 't5_predictions.csv.gz'
    temporary = csv_path.with_name(csv_path.name + '.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('series_id', 'timestamp', 'horizon_minutes', 'reference_label', 'common_history', *METHODS))
        for key, measurements in series(test_file):
            if not key.startswith('T5.') or any(time < start for time in measurements):
                raise ValueError('Bağımsız değerlendirme girdisi yalnızca T5 olmalı')
            if not measurements:
                continue
            observed_end = max(observed_end, max(measurements))
            grid, events, counts = series_grid(measurements, config)
            reference_counts[key] = counts
            events_by_series[key] = events
            for h, setup in configs.items():
                comparable = []
                for time, label, common, decisions in predict_grid(grid, h, setup, len(config['windows_minutes'])):
                    writer.writerow((key, utc(time), h, label, int(common),
                                     *(int(value) if value is not None else None for value in decisions)))
                    if common and label is not None:
                        comparable.append((time, label, decisions))
                    else:
                        reason = 'unknown_reference' if label is None else 'insufficient_common_history'
                        for method, warning in zip(METHODS, decisions, strict=True):
                            if warning:
                                warnings_outside[h][method][reason] += 1
                times = [r[0] for r in comparable]
                all_rows[h].extend((key, *row) for row in comparable)
                for index, method in enumerate(METHODS):
                    results, eligible, leads = event_results(events, times, [r[2][index] for r in comparable], h, minimum)
                    add_event_counts(event_counts[h][method], results)
                    lead_times[h][method].extend(leads)
                    if h == chosen and method == METHODS[0]:
                        eligible_starts.extend(event.start for event in eligible)
    if observed_end <= start:
        raise ValueError('T5 içinde değerlendirilebilir ölçüm dönemi yok')
    reports = {}
    bootstrap = None
    for h, rows in all_rows.items():
        times = np.asarray([row[1] for row in rows])
        labels = np.asarray([row[2] for row in rows], dtype=bool)
        continues = np.asarray([False] + [b[0] == a[0] and b[1] - a[1] == config['prediction_step_seconds']
                                          for a, b in zip(rows, rows[1:])], dtype=bool)[:len(rows)]
        decisions = {method: np.asarray([row[3][i] for row in rows], dtype=bool) for i, method in enumerate(METHODS)}
        reports[h] = dict(common_steps=len(rows), positive_labels=int(labels.sum()), methods={})
        for method in METHODS:
            counts = event_counts[h][method]
            counts['warning_rate'] = ratio(counts.get('warned', 0), counts.get('eligible', 0))
            counts['timely_warning_rate'] = ratio(counts.get('timely', 0), counts.get('eligible', 0))
            counts['median_lead_seconds'] = median(lead_times[h][method]) if lead_times[h][method] else None
            reports[h]['methods'][method] = dict(records=score(labels, decisions[method], continues, config['prediction_step_seconds']),
                                                  events=counts, warnings_outside_comparison=warnings_outside[h][method])
        if h == chosen:
            bootstrap = time_block_analysis(times, labels, decisions['random_forest'], decisions['threshold'],
                                            eligible_starts, start, observed_end, config['random_seed'])
    result = dict(partition='T5', frozen_manifest_sha256=sha256(manifest_path), selected_horizon_minutes=chosen,
                  minimum_intervention_seconds=minimum, observed_end_utc=utc(observed_end),
                  by_horizon_minutes=reports, sensitivity_by_series=reference_counts, paired_bootstrap=bootstrap,
                  shared_horizon_comparison=compare_horizons(all_rows, events_by_series, minimum),
                  overlapping_series_events=overlap_groups(events_by_series))
    report = output / 't5_report.json'
    temporary_report = report.with_name(report.name + '.tmp')
    temporary_report.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    publish_file(temporary, csv_path)
    publish_file(temporary_report, report)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen', type=Path, default=DEFAULT_FROZEN)
    parser.add_argument('--test-file', type=Path, default=ROOT / 'data/processed/test.csv')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/t5_evaluation')
    args = parser.parse_args()
    if not (args.frozen / 'manifest.json').is_file():
        parser.error('T5 değerlendirmesi için önce deney ayarlarını sabitleyin')
    result = evaluate(args.test_file, args.frozen, args.output)
    print(json.dumps(result['paired_bootstrap'], indent=2))


if __name__ == '__main__':
    main()
