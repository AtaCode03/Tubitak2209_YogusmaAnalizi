"""Sabit ayarlarla tamamlanan deney kutusu kayıtlarını değerlendirir."""

import argparse
import json
from datetime import datetime
from pathlib import Path
from statistics import median

import numpy as np

from core.windows import VARIABLES
from offline.evaluate_test import series_grid, split_at_breaks
from offline.events import Sample, continuity_blocks
from offline.freeze_configuration import DEFAULT_FROZEN, load_frozen_setup, sha256
from offline.import_data import publish_file
from offline.labels import utc
from offline.metrics import ratio, score
from offline.select_horizon import METHODS
from runtime.worker import ROOT
from storage.database import DEFAULT_DATABASE, connect

MARKERS = {'lid_open': 'Kapak açıldı', 'warm_product': 'Ilık ürün eklendi', 'control': 'Kontrol başlangıcı'}
INTERRUPTIONS = {'Veri kesintisi', 'Geçersiz paket', 'Eksik paket', 'ESP32 yeniden başladı'}


def seconds(timestamp):
    return datetime.fromisoformat(timestamp).timestamp()


def procedure_checks(scenario, events, measurements, breaks, config):
    marker = next((row for row in events if row['event_type'] == MARKERS[scenario]), None)
    if marker is None:
        return dict(issues=['missing_scenario_marker'], intervention_at=None)
    intervention = seconds(marker['started_at'])
    lid = next((row for row in events if row['event_type'] == 'Kapak açıldı'), None)
    if scenario == 'warm_product' and lid is not None:
        intervention = min(intervention, seconds(lid['started_at']))
    nominal, blocks = continuity_blocks([Sample(t, values[-1]) for t, values in measurements.items()],
                                        config['max_measurement_age_median_multiplier'])
    segments = list(split_at_breaks(blocks, breaks))
    before = [sample for block in segments for sample in block if sample.timestamp <= intervention]
    issues = []
    elapsed = 0
    if before and nominal is not None:
        limit = nominal * config['max_measurement_age_median_multiplier']
        for block in reversed(segments):
            preceding = [sample for sample in block if sample.timestamp <= intervention]
            if preceding and intervention - preceding[-1].timestamp <= limit and not any(
                    preceding[-1].timestamp < t <= intervention for t in breaks):
                elapsed = preceding[-1].timestamp - preceding[0].timestamp
                break
    if elapsed < 900:
        issues.append('less_than_15_minutes_continuous_before')
    if not before or before[-1].dpu <= 0:
        issues.append('pre_intervention_dpu_not_positive')
    after = max(measurements, default=intervention) - intervention
    if after < 1200:
        issues.append('less_than_20_minutes_after')
    if scenario == 'control' and any(row['event_type'] in ('Kapak açıldı', 'Ilık ürün eklendi') for row in events):
        issues.append('intervention_in_control')
    closed = next((row for row in events if row['event_type'] == 'Kapak kapatıldı' and
                   seconds(row['started_at']) >= intervention), None)
    open_seconds = seconds(closed['started_at']) - intervention if closed is not None else None
    if scenario != 'control' and (lid is None or closed is None):
        issues.append('missing_lid_open_or_close_time')
    return dict(intervention_at=utc(intervention), continuous_before_seconds=elapsed, after_seconds=max(0, after),
                lid_open_seconds=open_seconds, lid_open_target_seconds=15 if scenario != 'control' else None,
                issues=issues)


def display_metrics(rows, events, horizon, minimum):
    leads = []
    eligible = 0
    conservative = 0
    alerts = [row for row in rows if row['risk']]
    displayed = [row for row in alerts if row['first_displayed_at'] is not None]
    for event in events:
        start = event.start - horizon * 60
        opportunities = [row for row in rows if start <= row['tick'] < event.start]
        if not opportunities:
            continue
        eligible += 1
        times = [seconds(row['first_displayed_at']) for row in opportunities
                 if row['risk'] and row['first_displayed_at'] is not None and
                 seconds(row['first_displayed_at']) < event.start]
        if times:
            first = min(times)
            leads.append(event.start - first)
            if event.previous_nonnegative is not None and event.previous_nonnegative - first >= minimum:
                conservative += 1
    delays = [seconds(row['first_displayed_at']) - seconds(row['measured_at']) for row in displayed]
    timely = sum(lead >= minimum for lead in leads)
    return dict(eligible_events=eligible, warned_events=len(leads), timely_events=timely,
                missed_events=eligible - len(leads), timely_warning_rate=ratio(timely, eligible),
                median_lead_seconds=median(leads) if leads else None, timely_using_last_nonnegative=conservative,
                alert_rows_without_display_time=len(alerts) - len(displayed),
                median_measurement_to_display_seconds=median(delays) if delays else None)


def score_method(rows, step, events, horizon, minimum):
    comparable = [row for row in rows if row['common'] and row['label'] is not None]
    labels = np.asarray([row['label'] for row in comparable], dtype=bool)
    decisions = np.asarray([row['risk'] for row in comparable], dtype=bool)
    continues = np.asarray([False] + [b['tick'] - a['tick'] == step for a, b in zip(comparable, comparable[1:])],
                           dtype=bool)[:len(comparable)]
    records = score(labels, decisions, continues, step)
    false_steps = 0
    false_period = False
    active = False
    for label, warning, ongoing in zip(labels, decisions, continues, strict=True):
        if not ongoing or not warning:
            false_period = False
        if warning and (not ongoing or not active):
            false_period = not label
        active = warning
        if false_period:
            false_steps += 1
    records['false_alarm_duration_seconds'] = false_steps * step
    return dict(records=records, display=display_metrics(comparable, events, horizon, minimum),
                excluded_alerts_unknown_reference=sum(row['risk'] and row['label'] is None for row in rows),
                excluded_alerts_incomplete_history=sum(row['risk'] and row['label'] is not None and not row['common']
                                                       for row in rows))


def analyze_experiment(db, experiment, horizon, settings, version, config, minimum):
    experiment_id = experiment['id']
    measurements = list(db.execute('SELECT * FROM measurements WHERE experiment_id=? ORDER BY measured_at, id',
                                   (experiment_id,)))
    series_ids = {row['series_id'] for row in measurements}
    if len(series_ids) != 1:
        raise ValueError('Deney kutusu değerlendirmesi tek sensör serisi gerektirir')
    raw = {seconds(row['measured_at']): tuple(row[variable] for variable in VARIABLES) for row in measurements}
    events = [dict(row) for row in db.execute('SELECT * FROM experiment_events WHERE experiment_id=? ORDER BY started_at,id',
                                             (experiment_id,))]
    breaks = [seconds(row['started_at']) for row in events if row['event_type'] in INTERRUPTIONS]
    grid, reference, sensitivity = series_grid(raw, config, breaks)
    labels = {time: (targets[horizon], len(windows) == len(config['windows_minutes']))
              for time, _, windows, targets in grid}
    all_predictions = list(db.execute('''SELECT p.*, m.measured_at, s.method, s.horizon_minutes,
         s.parameters_json, s.model_version FROM predictions p JOIN measurements m ON m.id=p.measurement_id
         JOIN method_settings s ON s.id=p.setting_id WHERE m.experiment_id=? ORDER BY p.predicted_at,p.id''', (experiment_id,)))
    if not all_predictions:
        raise ValueError('Deneyde kayıtlı tahmin yok')
    records = {method: [] for method in METHODS}
    seen = set()
    for raw_prediction in all_predictions:
        row = dict(raw_prediction)
        method = row['method']
        if (row['horizon_minutes'] != horizon or json.loads(row['parameters_json']) != settings[method]['parameters']
                or (method == 'random_forest' and row['model_version'] != version)):
            raise ValueError('Deney tahminleri sabitlenmiş ayarlarla eşleşmiyor')
        tick = seconds(row['predicted_at'])
        key = (method, tick)
        if key in seen:
            raise ValueError('Aynı yöntem ve tahmin adımında birden fazla karar var')
        seen.add(key)
        label, common = labels.get(tick, (None, False))
        records[method].append(dict(row, tick=tick, label=label, common=common))
    shared = set.intersection(*({row['tick'] for row in rows if row['common'] and row['label'] is not None}
                                for rows in records.values()))
    for rows in records.values():
        for row in rows:
            if row['tick'] not in shared:
                row['common'] = False
    return dict(experiment_id=experiment_id, scenario=experiment['scenario'], measurements=len(raw),
                common_steps=len(shared),
                procedure=procedure_checks(experiment['scenario'], events, raw, breaks, config), interruptions=len(breaks),
                risk_events=[dict(start=utc(e.start), confirmed=utc(e.confirmed), last_negative=utc(e.end)) for e in reference],
                sensitivity=sensitivity,
                methods={method: score_method(rows, config['prediction_step_seconds'], reference, horizon, minimum)
                         for method, rows in records.items()})


def aggregate(experiments):
    metrics = {}
    for method in METHODS:
        candidates = [row['methods'][method] for row in experiments]
        counts = {key: sum(row['records'][key] for row in candidates) for key in ('tp', 'fp', 'fn', 'tn')}
        tp, fp, fn = (counts[key] for key in ('tp', 'fp', 'fn'))
        eligible = sum(row['display']['eligible_events'] for row in candidates)
        timely = sum(row['display']['timely_events'] for row in candidates)
        metrics[method] = dict(**counts, precision=ratio(tp, tp + fp), recall=ratio(tp, tp + fn),
                               f1=ratio(2 * tp, 2 * tp + fp + fn), displayed_timely_rate=ratio(timely, eligible),
                               false_alarm_periods=sum(row['records']['false_alarm_periods'] for row in candidates))
    return metrics


def evaluate(database, frozen, output):
    manifest_path = frozen / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    horizon, settings, _, version, _, config = load_frozen_setup(frozen)
    minimum = manifest['selected']['minimum_intervention_seconds']
    frozen_time = seconds(manifest['frozen_at_utc'])
    accepted, excluded = [], []
    with connect(database) as db:
        for experiment in db.execute('SELECT * FROM experiments WHERE ended_at IS NOT NULL ORDER BY id'):
            if experiment['scenario'] not in MARKERS or seconds(experiment['started_at']) < frozen_time:
                continue
            try:
                accepted.append(analyze_experiment(db, experiment, horizon, settings, version, config, minimum))
            except ValueError as exc:
                excluded.append({'experiment_id': experiment['id'], 'reason': str(exc)})
    counts = {scenario: sum(row['scenario'] == scenario and not row['procedure']['issues'] for row in accepted)
              for scenario in MARKERS}
    report = dict(frozen_manifest_sha256=sha256(manifest_path), horizon_minutes=horizon,
                  minimum_intervention_seconds=minimum, experiments=accepted, excluded_experiments=excluded,
                  aggregate_all_included=aggregate(accepted),
                  aggregate_by_scenario={scenario: aggregate([row for row in accepted if row['scenario'] == scenario])
                                         for scenario in MARKERS},
                  protocol_ready_counts=counts, minimum_repetitions_met=all(n >= 3 for n in counts.values()))
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'experiment_report.json'
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    publish_file(temporary, path)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--frozen', type=Path, default=DEFAULT_FROZEN)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/experiment_evaluation')
    args = parser.parse_args()
    if not (args.frozen / 'manifest.json').is_file():
        parser.error('Deney değerlendirmesi için önce ayarları sabitleyin')
    if not args.database.is_file():
        parser.error('Deney veritabanı bulunamadı')
    print(json.dumps(evaluate(args.database, args.frozen, args.output)['protocol_ready_counts'], indent=2))


if __name__ == '__main__':
    main()
