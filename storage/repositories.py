"""Deney, ölçüm, müdahale, yöntem ayarı ve tahmin kayıtları."""

import json
from datetime import timezone

from core.contracts import ComputedMeasurement


def utc_text(timestamp):
    if timestamp.utcoffset() is None:
        raise ValueError('Saat dilimi bilgisi gerekli')
    return timestamp.astimezone(timezone.utc).isoformat(timespec='microseconds')


def create_experiment(connection, scenario, started_at, description=''):
    return connection.execute('INSERT INTO experiments(scenario, started_at, description) VALUES (?, ?, ?)',
                              (scenario, utc_text(started_at), description)).lastrowid


def finish_experiment(connection, experiment_id, ended_at):
    return connection.execute('UPDATE experiments SET ended_at = ? WHERE id = ? AND ended_at IS NULL',
                              (utc_text(ended_at), experiment_id)).rowcount == 1


def add_measurement(connection, experiment_id, result: ComputedMeasurement):
    measurement = result.measurement
    return connection.execute('''
        INSERT INTO measurements(experiment_id, series_id, measured_at, air_temperature_c,
            relative_humidity_pct, surface_temperature_c, dew_point_c, dpu_c)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
        (experiment_id, measurement.series_id, utc_text(measurement.timestamp), measurement.air_temperature_c,
         measurement.relative_humidity_pct, measurement.surface_temperature_c, result.dew_point_c, result.dpu_c)).lastrowid


def add_event(connection, experiment_id, event_type, started_at, ended_at=None, description=''):
    return connection.execute('''
        INSERT INTO experiment_events(experiment_id, event_type, started_at, ended_at, description)
        VALUES (?, ?, ?, ?, ?)''', (experiment_id, event_type, utc_text(started_at),
                                   utc_text(ended_at) if ended_at is not None else None, description)).lastrowid


def get_or_create_setting(connection, method, parameters, horizon_minutes, model_version='', model_path=''):
    values = (method, json.dumps(parameters, sort_keys=True, allow_nan=False, separators=(',', ':')),
              horizon_minutes, model_version, model_path)
    connection.execute('''INSERT INTO method_settings(method, parameters_json, horizon_minutes, model_version, model_path)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(method, parameters_json, horizon_minutes, model_version, model_path)
        DO NOTHING''', values)
    return connection.execute('''SELECT id FROM method_settings WHERE method=? AND parameters_json=?
        AND horizon_minutes=? AND model_version=? AND model_path=?''', values).fetchone()['id']


def add_prediction(connection, measurement_id, setting_id, predicted_at, risk):
    if not isinstance(risk, bool):
        raise ValueError('Tahmin kaydı için True veya False gerekli')
    return connection.execute('''INSERT INTO predictions(measurement_id, setting_id, predicted_at, risk)
        VALUES (?, ?, ?, ?)''', (measurement_id, setting_id, utc_text(predicted_at), int(risk))).lastrowid


def mark_first_display(connection, prediction_id, displayed_at):
    """Arayüz yenilense bile ilk gösterim zamanı korunur."""
    return connection.execute('''UPDATE predictions SET first_displayed_at=?
        WHERE id=? AND risk=1 AND first_displayed_at IS NULL''',
        (utc_text(displayed_at), prediction_id)).rowcount == 1
