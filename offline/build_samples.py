"""Adım 4: UTC gridinde pencere özellikleri ve ayrı referans etiketleri."""

import argparse
import csv
import gzip
import json
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
from itertools import groupby
from pathlib import Path

from core.windows import FEATURE_NAMES, VARIABLES, grid_windows
from offline.events import Sample, continuity_blocks, find_events
from offline.import_data import publish_file
from offline.labels import PARTITIONS, label_at, utc
from offline.split_data import RESEARCH_CONFIG, SplitBoundaries

ROOT = RESEARCH_CONFIG.parents[1]


def series(path):
    with path.open(encoding='utf-8', newline='') as stream:
        for key, rows in groupby(csv.DictReader(stream), lambda row: row['series_id']):
            measurements = {}
            for row in rows:
                timestamp = datetime.fromisoformat(row['timestamp']).timestamp()
                measurements[timestamp] = (tuple(float(row[name]) for name in VARIABLES)
                                           if row['valid'] == '1' else None)
            yield key, measurements


def partition_samples(source, destination, partition, end, settings):
    step = settings['prediction_step_seconds']
    windows = settings['windows_minutes']
    horizons = settings['horizons_minutes']
    duration = settings['event_min_duration_seconds']
    gap = settings['max_measurement_age_median_multiplier']
    counts = Counter()
    names = [f'{partition}_features_{w}m.csv.gz' for w in windows] + [f'{partition}_grid_labels.csv.gz']
    with ExitStack() as stack:
        writers = [csv.writer(stack.enter_context(gzip.open(destination / f'{name}.tmp', 'wt',
                   encoding='utf-8', newline='', compresslevel=1))) for name in names]
        for writer in writers[:-1]:
            writer.writerow(('series_id', 'timestamp', *FEATURE_NAMES))
        writers[-1].writerow(('series_id', 'timestamp', 'all_windows', *(field for h in horizons
                             for field in (f'label_{h}m', f'issue_{h}m'))))
        for key, measurements in series(source):
            nominal, blocks = continuity_blocks([Sample(t, v[-1] if v is not None else None)
                                                 for t, v in measurements.items()], gap)
            if nominal is None:
                continue
            for block in blocks:
                starts = [event.start for event in find_events(block, duration)]
                readings = ((sample.timestamp, measurements[sample.timestamp]) for sample in block)
                for tick, values, features in grid_windows(readings, step, windows, nominal * gap):
                    if values is None or values[-1] <= 0:
                        continue
                    counts['positive_dpu_grid_steps'] += 1
                    if not features:
                        continue
                    base = (key, utc(tick))
                    for w, writer in zip(windows, writers[:-1], strict=True):
                        if w in features:
                            writer.writerow((*base, *features[w]))
                            counts[f'window_{w}m'] += 1
                    common = len(features) == len(windows)
                    labels = [label_at(tick, h * 60, duration, block[-1].timestamp, end, starts) for h in horizons]
                    writers[-1].writerow((*base, int(common), *(item for pair in labels for item in pair)))
                    if common:
                        for h, (label, issue) in zip(horizons, labels, strict=True):
                            counts[f'common_{h}m_{issue or ("positive" if label else "negative")}'] += 1
    for name in names:
        publish_file(destination / f'{name}.tmp', destination / name)
    return dict(counts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/processed')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/windows')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    settings = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    boundaries = SplitBoundaries.load()
    ends = (boundaries.validation_start.timestamp(), boundaries.test_start.timestamp(), None)
    report = {part: partition_samples(args.source / f'{part}.csv', args.output, part, end, settings)
              for part, end in zip(PARTITIONS, ends, strict=True)}
    temporary = args.output / 'window_report.json.tmp'
    temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
    publish_file(temporary, args.output / 'window_report.json')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
