"""USB ölçüm toplama ve yalıtılmış canlı akış denemesi."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from math import floor
from time import sleep

from acquisition.protocol import parse_line
from acquisition.serial_source import serial_frames
from core.validation import MeasurementValidationError
from offline.freeze_configuration import DEFAULT_FROZEN, load_frozen_setup
from offline.import_data import publish_file
from offline.split_data import RESEARCH_CONFIG
from runtime.pipeline import Pipeline
from runtime.worker import register_settings, selected_setup
from storage.database import DEFAULT_DATABASE, connect, initialize
from storage.repositories import add_event, create_experiment, finish_experiment

DEMO_DB = DEFAULT_DATABASE.with_name('live_demo.sqlite3')
LIVE_STATE = DEFAULT_DATABASE.with_name('live_state.json')
DEMO_STATE = DEFAULT_DATABASE.with_name('live_demo_state.json')


def demo_frames(seconds):
    start = datetime.now(timezone.utc) - timedelta(minutes=42)
    start = datetime.fromtimestamp(floor(start.timestamp() / 150) * 150, timezone.utc)
    for index in range(82):
        timestamp = start + timedelta(seconds=30 * index)
        if index in (44, 45, 46):
            yield 'disconnected', timestamp, b''
        else:
            position = index if index < 44 else index - 47
            surface = 10.2 - min(position, 43) * 0.035
            line = f'M1,{index},{index * 30000},10.00,88.00,{surface:.3f},184320'.encode('ascii')
            yield 'line', timestamp, line
        if seconds:
            sleep(seconds)


def save_state(path, state):
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(state, indent=2), encoding='utf-8')
    publish_file(temporary, path)


def collect(frames, horizon, experiment_id=None, demo=False, frozen=None):
    database, status_file = (DEMO_DB, DEMO_STATE) if demo else (DEFAULT_DATABASE, LIVE_STATE)
    initialize(database)
    if frozen is None:
        selected, model, version, model_path = selected_setup(horizon)
        config = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))
    else:
        horizon, selected, model, version, model_path, config = load_frozen_setup(frozen)
    max_age = config['sensor_interval_seconds'] * config['max_measurement_age_median_multiplier']
    state = dict(status='waiting', demo=demo, experiment_id=experiment_id, horizon=horizon, frozen=frozen is not None, missing_packets=0,
                 rejected_packets=0, restarts=0, free_heap_bytes=None, minimum_heap_bytes=None,
                 last_received_at=None, last_sample_at=None, stream_started_at=None)
    previous = None
    with connect(database) as db:
        experiment = db.execute('SELECT ended_at FROM experiments WHERE id=?', (experiment_id,)).fetchone()
        if not demo and (experiment is None or experiment['ended_at'] is not None):
            raise ValueError('USB kaydı için başlatılmış ve açık bir deney kimliği gerekli')
        if demo:
            experiment_id = create_experiment(db, 'live_demo', datetime.now(timezone.utc) - timedelta(minutes=46),
                                              'USB akışı benzetimi')
            state['experiment_id'] = experiment_id
        settings = register_settings(db, selected, horizon, version, model_path)
        pipeline = Pipeline(db, experiment_id, settings, model, config['prediction_step_seconds'], max_age)
        db.commit()
        save_state(status_file, state)
        try:
            for kind, timestamp, line in frames:
                if not demo and db.execute('SELECT ended_at FROM experiments WHERE id=?',
                                           (experiment_id,)).fetchone()[0] is not None:
                    break
                received_at = datetime.now(timezone.utc)
                last = state['last_received_at']
                if kind == 'idle' and (not last or (received_at - datetime.fromisoformat(last)).total_seconds() <= max_age):
                    continue
                if kind != 'line':
                    if state['status'] != 'disconnected':
                        pipeline.interrupt()
                        add_event(db, experiment_id, 'Veri kesintisi', timestamp)
                        db.commit()
                        state['status'] = 'disconnected'
                        state['stream_started_at'] = None
                        save_state(status_file, state)
                    continue
                try:
                    packet = parse_line(line, timestamp, 'Demo ESP32' if demo else 'ESP32')
                except ValueError:
                    pipeline.interrupt()
                    add_event(db, experiment_id, 'Geçersiz paket', timestamp)
                    db.commit()
                    state['rejected_packets'] += 1
                    state['stream_started_at'] = None
                    state['status'] = 'invalid'
                    save_state(status_file, state)
                    continue
                restarted = previous is not None and packet.uptime_ms < previous.uptime_ms
                if previous is not None and not restarted and packet.sequence <= previous.sequence:
                    state['rejected_packets'] += 1
                    save_state(status_file, state)
                    continue
                skipped = max(0, packet.sequence - previous.sequence - 1) if previous is not None and not restarted else 0
                if restarted or skipped:
                    pipeline.interrupt()
                    event = 'ESP32 yeniden başladı' if restarted else 'Eksik paket'
                    add_event(db, experiment_id, event, timestamp, description=f'Atlanan sıra: {skipped}')
                    state['stream_started_at'] = None
                    state['restarts'] += int(restarted)
                    state['missing_packets'] += skipped
                try:
                    pipeline.ingest(timestamp, packet.measurement)
                except MeasurementValidationError:
                    pipeline.interrupt()
                    add_event(db, experiment_id, 'Geçersiz paket', timestamp)
                    db.commit()
                    state['rejected_packets'] += 1
                    state['stream_started_at'] = None
                    state['status'] = 'invalid'
                    save_state(status_file, state)
                    continue
                db.commit()
                previous = packet
                state.update(status='receiving', last_received_at=received_at.isoformat(), last_sample_at=timestamp.isoformat(),
                             stream_started_at=state['stream_started_at'] or timestamp.isoformat(),
                             free_heap_bytes=packet.free_heap_bytes,
                             minimum_heap_bytes=min(state['minimum_heap_bytes'] if state['minimum_heap_bytes'] is not None
                                                    else packet.free_heap_bytes, packet.free_heap_bytes))
                save_state(status_file, state)
        except KeyboardInterrupt:
            pass
        finally:
            if demo:
                finish_experiment(db, experiment_id, datetime.now(timezone.utc))
            state.update(status='stopped', counters=dict(pipeline.counts))
            save_state(status_file, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--demo', action='store_true')
    source.add_argument('--port')
    parser.add_argument('--experiment-id', type=int)
    setup = parser.add_mutually_exclusive_group(required=True)
    setup.add_argument('--horizon', type=int, choices=(5, 10, 15))
    setup.add_argument('--frozen', action='store_true')
    parser.add_argument('--demo-delay', type=float, default=1.0)
    args = parser.parse_args()
    if args.port and args.experiment_id is None:
        parser.error('--port için --experiment-id gerekli')
    if args.demo and args.frozen:
        parser.error('--frozen yalnızca gerçek USB kaydında kullanılır')
    if args.demo_delay < 0:
        parser.error('--demo-delay negatif olamaz')
    frames = demo_frames(args.demo_delay) if args.demo else serial_frames(args.port)
    print(json.dumps(collect(frames, args.horizon, args.experiment_id, args.demo,
                             DEFAULT_FROZEN if args.frozen else None), indent=2))


if __name__ == '__main__':
    main()
