"""Bir deneyin ölçümlerini, tahminlerini ve müdahale kayıtlarını dışa aktarır."""

import argparse
import csv
from datetime import datetime
from pathlib import Path

from storage.database import DEFAULT_DATABASE, connect
from storage.repositories import utc_text


def filters(experiment_id, start, stop, time_column):
    conditions = []
    params = [experiment_id]
    if start is not None:
        conditions.append(f'AND {time_column} >= ?')
        params.append(utc_text(start))
    if stop is not None:
        conditions.append(f'AND {time_column} < ?')
        params.append(utc_text(stop))
    return ' '.join(conditions), params


def write_csv(cursor, path):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(column[0] for column in cursor.description)
        writer.writerows(cursor)


def export_experiment(connection, experiment_id, output, start=None, stop=None):
    if start is not None and stop is not None and utc_text(start) >= utc_text(stop):
        raise ValueError('Tarih aralığının başlangıcı bitişten önce olmalı')
    if connection.execute('SELECT 1 FROM experiments WHERE id=?', (experiment_id,)).fetchone() is None:
        raise ValueError(f'Deney bulunamadı: {experiment_id}')
    output.mkdir(parents=True, exist_ok=True)
    extra, params = filters(experiment_id, start, stop, 'm.measured_at')
    measurements = connection.execute(f'''
        SELECT m.*, e.scenario, p.id AS prediction_id, p.predicted_at, p.risk, p.first_displayed_at,
               s.method, s.horizon_minutes, s.parameters_json, s.model_version, s.model_path
        FROM measurements m JOIN experiments e ON m.experiment_id=e.id
        LEFT JOIN predictions p ON p.measurement_id=m.id
        LEFT JOIN method_settings s ON s.id=p.setting_id
        WHERE m.experiment_id=? {extra} ORDER BY m.measured_at, m.id, p.predicted_at, p.id''', params)
    extra, params = filters(experiment_id, start, stop, 'started_at')
    events = connection.execute(f'''SELECT * FROM experiment_events WHERE experiment_id=? {extra}
        ORDER BY started_at, id''', params)
    paths = output / 'measurements_and_predictions.csv', output / 'events.csv'
    write_csv(measurements, paths[0])
    write_csv(events, paths[1])
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('experiment_id', type=int)
    parser.add_argument('output', type=Path)
    parser.add_argument('--database', type=Path, default=DEFAULT_DATABASE)
    parser.add_argument('--start', type=datetime.fromisoformat)
    parser.add_argument('--stop', type=datetime.fromisoformat)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error('Veritabanı dosyası bulunamadı')
    with connect(args.database) as connection:
        export_experiment(connection, args.experiment_id, args.output, args.start, args.stop)


if __name__ == '__main__':
    main()
