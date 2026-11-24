"""Bağımsız testten önce model ve ayarların doğrulanabilir kopyasını saklar."""

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import file_digest
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory

import joblib

from core.windows import FEATURE_NAMES
from offline.select_horizon import EVENTS, T4_DIR, inputs, load_interventions, select
from offline.split_data import RESEARCH_CONFIG
from runtime.worker import ROOT, selected_setup

DEFAULT_FROZEN = ROOT / 'data/runtime/frozen'


def sha256(path):
    with path.open('rb') as stream:
        return file_digest(stream, 'sha256').hexdigest()


def load_frozen_setup(directory=DEFAULT_FROZEN, horizon=None):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if horizon is None:
        horizon = manifest['selected']['selected_horizon_minutes']
    if horizon not in (5, 10, 15):
        raise ValueError('Sabitlenmiş tahmin süresi geçersiz')
    entry = manifest['models_by_horizon'][str(horizon)]
    path = directory / f'random_forest_{horizon}m.joblib'
    config_path = directory / 'research.json'
    if (entry['file'] != path.name or sha256(path) != entry['sha256'] or
            sha256(config_path) != manifest['input_sha256']['research.json']):
        raise ValueError('Sabitlenmiş model veya araştırma yapılandırması değişmiş')
    bundle = joblib.load(path)
    if (tuple(bundle['feature_names']) != FEATURE_NAMES or bundle['horizon_minutes'] != horizon or
            bundle['parameters'] != entry['settings']['random_forest']):
        raise ValueError('Sabitlenmiş model ayarları uyuşmuyor')
    selected = {method: {'parameters': parameters} for method, parameters in entry['settings'].items()}
    config = json.loads(config_path.read_text(encoding='utf-8'))
    return horizon, selected, bundle['model'].set_params(n_jobs=1), entry['sha256'], str(path), config


def freeze(interventions, destination=DEFAULT_FROZEN):
    if destination.exists():
        raise FileExistsError(f'Sabitlenmiş dosyalar zaten var: {destination}')
    repetitions = load_interventions(interventions)
    predictions, events, report = inputs()
    results = report['by_horizon_minutes']
    choice = select(predictions, events, results, max(repetitions) + Decimal(30))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent, prefix='.freeze-') as staging:
        snapshot = Path(staging) / 'snapshot'
        snapshot.mkdir()
        for source, name in ((RESEARCH_CONFIG, 'research.json'), (interventions, 'intervention_times.csv'),
                             (T4_DIR / 'parameter_search_report.json', 'parameter_search_report.json')):
            copyfile(source, snapshot / name)
        models = {}
        for h in results:
            selected, _, digest, model_path = selected_setup(int(h))
            source = ROOT / model_path
            model = snapshot / source.name
            copyfile(source, model)
            if sha256(model) != digest:
                raise ValueError(f'Model kopyası kaynakla uyuşmuyor: {h} dk')
            models[h] = dict(file=model.name, sha256=digest,
                             settings={method: row['parameters'] for method, row in selected.items()})
        manifest = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(), selected=choice,
                        intervention_seconds=[str(value) for value in repetitions], models_by_horizon=models,
                        sklearn_version=report['sklearn_version'],
                        input_sha256={file.name: sha256(file) for file in (
                            EVENTS, T4_DIR / 'selected_t4_predictions.csv.gz', snapshot / 'research.json',
                            snapshot / 'intervention_times.csv', snapshot / 'parameter_search_report.json')})
        (snapshot / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        snapshot.rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--interventions', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=DEFAULT_FROZEN)
    args = parser.parse_args()
    print(json.dumps(freeze(args.interventions, args.output)['selected'], indent=2))


if __name__ == '__main__':
    main()
