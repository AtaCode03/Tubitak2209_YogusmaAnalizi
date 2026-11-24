"""T4 ortak adımlarında eşik ve eğim adaylarının kararlarını üretir."""

import argparse
import csv
import gzip
import json
from collections import Counter
from pathlib import Path

from core.methods import linear_trend, threshold
from offline.import_data import publish_file
from offline.split_data import RESEARCH_CONFIG

ROOT = RESEARCH_CONFIG.parents[1]


def key(row):
    return row['series_id'], row['timestamp']


def read_rows(path):
    with gzip.open(path, 'rt', encoding='utf-8', newline='') as stream:
        yield from csv.DictReader(stream)


def run(source, output):
    settings = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    windows = settings['windows_minutes']
    margins = settings['threshold_candidates_c']
    horizons = settings['horizons_minutes']
    common = {key(row): row for row in read_rows(source / 'validation_grid_labels.csv.gz')
              if row['all_windows'] == '1'}
    slopes = {}
    for window in windows:
        path = source / f'validation_features_{window}m.csv.gz'
        slopes[window] = {key(row): (float(row['dpu_c_current']), float(row['dpu_c_slope_per_minute']))
                          for row in read_rows(path) if key(row) in common}
        if slopes[window].keys() != common.keys():
            raise ValueError(f'{window} dk özellikleri ortak adımlarla eşleşmiyor')

    output.mkdir(parents=True, exist_ok=True)
    path = output / 'validation_baseline_predictions.csv.gz'
    temporary = path.with_name(path.name + '.tmp')
    counts = {h: Counter() for h in horizons}
    with gzip.open(temporary, 'wt', encoding='utf-8', newline='', compresslevel=1) as stream:
        writer = csv.writer(stream)
        writer.writerow(('series_id', 'timestamp', 'horizon_minutes', 'reference_label',
                         *(f'threshold_{margin:g}c' for margin in margins),
                         *(f'linear_{window}m' for window in windows)))
        for step, row in common.items():
            dpu = slopes[windows[0]][step][0]
            if any(slopes[w][step][0] != dpu for w in windows):
                raise ValueError(f'Ortak adımdaki güncel DPU değerleri eşleşmiyor: {step}')
            threshold_decisions = [threshold.predict(dpu, margin) for margin in margins]
            for h in horizons:
                label = row[f'label_{h}m']
                if label not in ('0', '1'):
                    continue
                decisions = threshold_decisions + [linear_trend.predict(dpu, slopes[w][step][1], h) for w in windows]
                if any(decision is None for decision in decisions):
                    raise ValueError(f'Ortak adım için aday kararı eksik: {step}, {h} dk')
                writer.writerow((*step, h, label, *(int(decision) for decision in decisions)))
                counts[h]['common_steps'] += 1
                counts[h]['positive_reference' if label == '1' else 'negative_reference'] += 1
    publish_file(temporary, path)
    report = {'partition': 'T4', 'threshold_candidates_c': margins, 'linear_windows_minutes': windows,
              'counts_by_horizon_minutes': counts}
    report_path = output / 'baseline_report.json'
    temporary_report = report_path.with_name(report_path.name + '.tmp')
    temporary_report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    publish_file(temporary_report, report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/processed/windows')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/baselines')
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
