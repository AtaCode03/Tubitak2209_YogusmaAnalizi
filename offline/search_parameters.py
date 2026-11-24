"""T2–T3 eğitimi ve T4 üzerinde aday ayar seçimi."""

import argparse
import csv
import gzip
import json
from datetime import datetime
from itertools import product
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn import __version__ as sklearn_version
from sklearn.ensemble import RandomForestClassifier

from core.windows import FEATURE_NAMES
from offline.import_data import publish_file
from offline.metrics import ranking, score
from offline.run_baselines import key, read_rows
from offline.split_data import RESEARCH_CONFIG

ROOT = RESEARCH_CONFIG.parents[1]
KEY_COLUMNS = ['series_id', 'timestamp']


def load_features(path):
    frame = pd.read_csv(path, dtype={name: 'float32' for name in FEATURE_NAMES})
    return index_by_step(frame, path)


def index_by_step(frame, path):
    indexed = frame.set_index(KEY_COLUMNS)
    if not indexed.index.is_unique:
        raise ValueError(f'Tekil olmayan tahmin anahtarı: {path}')
    return indexed


def training_targets(source, horizons):
    path = source / 'train_grid_labels.csv.gz'
    frame = pd.read_csv(path, usecols=[*KEY_COLUMNS, *(f'label_{h}m' for h in horizons)])
    return index_by_step(frame, path)


def continuity(rows, step):
    previous = None
    flags = []
    for row in rows:
        current = (row['series_id'], datetime.fromisoformat(row['timestamp']).timestamp())
        flags.append(previous is not None and previous[0] == current[0] and current[1] - previous[1] == step)
        previous = current
    return np.asarray(flags, dtype=bool)


def best_baselines(rows, labels, continues, settings):
    candidates = []
    winners = {}
    groups = [('threshold', 'margin_c', settings['threshold_candidates_c'], 'c'),
              ('linear', 'window_minutes', settings['windows_minutes'], 'm')]
    for method, parameter, values, suffix in groups:
        best = None
        for value in values:
            column = f'{method}_{value:g}{suffix}'
            decisions = np.asarray([row[column] == '1' for row in rows], dtype=bool)
            metrics = score(labels, decisions, continues, settings['prediction_step_seconds'])
            candidate = dict(method=method, parameters={parameter: value}, metrics=metrics)
            candidates.append(candidate)
            ranked = ranking(metrics, (-value,))
            if best is None or ranked > best:
                best = ranked
                winners[method] = candidate, decisions
    return candidates, winners


def search_forest(horizon, features, targets, rows, labels, continues, settings, models, jobs):
    options = settings['rf_candidates']
    target = targets[f'label_{horizon}m'].dropna()
    index = pd.MultiIndex.from_tuples([key(row) for row in rows], names=KEY_COLUMNS)
    candidates = []
    best, winner = None, None
    path = models / f'random_forest_{horizon}m.joblib'
    temporary = path.with_name(path.name + '.tmp')
    for window, (train_frame, validation_frame) in features.items():
        train_index = train_frame.index.intersection(target.index, sort=False)
        train_x = train_frame.loc[train_index, list(FEATURE_NAMES)].to_numpy(dtype=np.float32)
        train_y = target.loc[train_index].to_numpy(dtype=np.int8)
        valid_x = validation_frame.loc[index, list(FEATURE_NAMES)].to_numpy(dtype=np.float32)
        if len(np.unique(train_y)) != 2:
            raise ValueError(f'{horizon} dk / {window} dk eğitiminde iki sınıf da gerekli')
        print(f'T4 | H={horizon} dk | pencere={window} dk | T2-T3 n={len(train_y)}', flush=True)
        for depth, leaf in product(options['max_depth'], options['min_samples_leaf']):
            model = RandomForestClassifier(max_depth=depth, min_samples_leaf=leaf, random_state=settings['random_seed'],
                                           n_jobs=jobs, warm_start=True)
            for trees in sorted(options['n_estimators']):
                model.set_params(n_estimators=trees)
                model.fit(train_x, train_y)
                decisions = model.predict(valid_x).astype(bool)
                metrics = score(labels, decisions, continues, settings['prediction_step_seconds'])
                parameters = dict(window_minutes=window, n_estimators=trees, max_depth=depth, min_samples_leaf=leaf)
                candidate = dict(method='random_forest', parameters=parameters, training_rows=len(train_y), metrics=metrics)
                candidates.append(candidate)
                ranked = ranking(metrics, (-window, -trees, -depth if depth is not None else -float('inf'), leaf))
                if best is None or ranked > best:
                    best = ranked
                    winner = candidate, decisions
                    joblib.dump(dict(model=model, feature_names=FEATURE_NAMES, horizon_minutes=horizon,
                                     parameters=parameters, sklearn_version=sklearn_version), temporary, compress=1)
    publish_file(temporary, path)
    return candidates, winner


def run(source, baseline_file, output, models, jobs):
    settings = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    horizons = settings['horizons_minutes']
    targets = training_targets(source, horizons)
    features = {w: (load_features(source / f'train_features_{w}m.csv.gz'),
                    load_features(source / f'validation_features_{w}m.csv.gz')) for w in settings['windows_minutes']}
    baseline_rows = list(read_rows(baseline_file))
    output.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    results = {}
    path = output / 'selected_t4_predictions.csv.gz'
    temporary = path.with_name(path.name + '.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8', newline='', compresslevel=1) as stream:
        writer = csv.writer(stream)
        writer.writerow((*KEY_COLUMNS, 'horizon_minutes', 'reference_label', 'threshold', 'linear', 'random_forest'))
        for h in horizons:
            rows = [row for row in baseline_rows if int(row['horizon_minutes']) == h]
            if not rows:
                raise ValueError(f'T4 için ortak adım yok: {h} dk')
            labels = np.asarray([row['reference_label'] == '1' for row in rows], dtype=bool)
            continues = continuity(rows, settings['prediction_step_seconds'])
            candidates, winners = best_baselines(rows, labels, continues, settings)
            forest_candidates, winners['random_forest'] = search_forest(
                h, features, targets, rows, labels, continues, settings, models, jobs)
            selections = {method: candidate for method, (candidate, _) in winners.items()}
            results[str(h)] = dict(common_steps=len(rows), candidates=candidates + forest_candidates, selected=selections)
            decisions = [winners[method][1] for method in ('threshold', 'linear', 'random_forest')]
            writer.writerows((*key(row), h, int(label), *(int(value) for value in preds))
                             for row, label, preds in zip(rows, labels, zip(*decisions, strict=True), strict=True))
    publish_file(temporary, path)
    report = dict(training_periods=['T2', 'T3'], validation_period='T4', sklearn_version=sklearn_version,
                  random_seed=settings['random_seed'], by_horizon_minutes=results)
    report_path = output / 'parameter_search_report.json'
    temporary_report = report_path.with_name(report_path.name + '.tmp')
    temporary_report.write_text(json.dumps(report, indent=2, allow_nan=False), encoding='utf-8')
    publish_file(temporary_report, report_path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/processed/windows')
    parser.add_argument('--baselines', type=Path, default=ROOT / 'data/processed/baselines/validation_baseline_predictions.csv.gz')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/parameter_search')
    parser.add_argument('--models', type=Path, default=ROOT / 'models')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    run(args.source, args.baselines, args.output, args.models, args.jobs)


if __name__ == '__main__':
    main()
