"""T4 kayıt oynatma deneyi. Özgün ölçüm saatleriyle hızlandırılmış çalışır."""

import argparse
import json
from hashlib import file_digest
from itertools import chain
from pathlib import Path

import joblib

from acquisition.replay import read_recording
from core.windows import FEATURE_NAMES
from offline.split_data import RESEARCH_CONFIG
from runtime.pipeline import Pipeline
from storage.database import DEFAULT_DATABASE, connect, initialize
from storage.repositories import create_experiment, finish_experiment, get_or_create_setting

ROOT = RESEARCH_CONFIG.parents[1]
DEFAULT_REPLAY_DATABASE = DEFAULT_DATABASE.with_name('replay.sqlite3')


def selected_setup(horizon):
    search = json.loads((ROOT / 'data/processed/parameter_search/parameter_search_report.json').read_text(encoding='utf-8'))
    selected = search['by_horizon_minutes'][str(horizon)]['selected']
    relative_path = Path(f'models/random_forest_{horizon}m.joblib')
    model_path = ROOT / relative_path
    with model_path.open('rb') as model_file:
        model_version = file_digest(model_file, 'sha256').hexdigest()
        model_file.seek(0)
        bundle = joblib.load(model_file)
    if (tuple(bundle['feature_names']) != FEATURE_NAMES or bundle['horizon_minutes'] != horizon
            or bundle['parameters'] != selected['random_forest']['parameters']):
        raise ValueError('Model dosyası ve seçilen ayarlar uyuşmuyor')
    return selected, bundle['model'].set_params(n_jobs=1), model_version, relative_path.as_posix()


def register_settings(db, selected, horizon, model_version, model_path):
    settings = {}
    for method, candidate in selected.items():
        parameters = candidate['parameters']
        identity = (model_version, model_path) if method == 'random_forest' else ('', '')
        setting_id = get_or_create_setting(db, method, parameters, horizon, *identity)
        settings[method] = dict(id=setting_id, parameters=parameters, horizon=horizon)
    return settings


def play(series_id, horizon, limit, database):
    if limit < 1:
        raise ValueError('Kayıt sınırı pozitif olmalı')
    processed = ROOT / 'data/processed'
    selected, model, model_version, model_path = selected_setup(horizon)
    research = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    intervals = json.loads((processed / 'label_report.json').read_text(encoding='utf-8'))
    nominal = intervals['validation']['median_interval_seconds_by_series'].get(series_id)
    if nominal is None:
        raise ValueError(f'T4 seri veya medyan ölçüm aralığı bulunamadı: {series_id}')
    recording = read_recording(processed / 'validation.csv', series_id, limit)
    first = next(recording, None)
    if first is None:
        raise ValueError(f'Oynatılacak kayıt yok: {series_id}')
    initialize(database)
    with connect(database) as db:
        experiment_id = create_experiment(db, 'replay', first[0], f'T4 {series_id}, H={horizon} dakika')
        settings = register_settings(db, selected, horizon, model_version, model_path)
        pipeline = Pipeline(db, experiment_id, settings, model, research['prediction_step_seconds'],
                            nominal * research['max_measurement_age_median_multiplier'])
        for timestamp, measurement in chain((first,), recording):
            pipeline.ingest(timestamp, measurement)
        finish_experiment(db, experiment_id, timestamp)
    return dict(experiment_id=experiment_id, source='validation/T4', series_id=series_id,
                horizon_minutes=horizon, model_sha256=model_version, counters=dict(pipeline.counts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--series', default='T4.LoraA')
    parser.add_argument('--horizon', type=int, choices=(5, 10, 15), required=True)
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--database', type=Path, default=DEFAULT_REPLAY_DATABASE)
    args = parser.parse_args()
    print(json.dumps(play(args.series, args.horizon, args.limit, args.database), indent=2))


if __name__ == '__main__':
    main()
