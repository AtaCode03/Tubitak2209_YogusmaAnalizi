"""Streamlit ekranları ve kayıt oynatma denetimleri."""

import json
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from statistics import median
from pathlib import Path
from tempfile import TemporaryDirectory

import altair as alt
import pandas as pd
import streamlit as st

from core.contracts import Measurement
from core.physics import calculate_measurement
from core.validation import MeasurementValidationError
from offline.freeze_configuration import DEFAULT_FROZEN, sha256
from offline.split_data import RESEARCH_CONFIG
from runtime.live_worker import DEMO_DB, DEMO_STATE, LIVE_STATE
from runtime.worker import DEFAULT_REPLAY_DATABASE, ROOT
from storage.database import DEFAULT_DATABASE, connect, initialize
from storage.export_csv import export_experiment
from storage.repositories import add_event, create_experiment, finish_experiment, mark_first_display

METHODS = {'threshold': 'Güvenlik paylı eşik', 'linear': 'Doğrusal eğim', 'random_forest': 'Random Forest'}
SCENARIOS = {'lid_open': 'Kapak açılması', 'warm_product': 'Ilık ürün eklenmesi', 'control': 'Müdahalesiz kontrol'}
MEASURES = {'air_temperature_c': 'Ortam sıcaklığı', 'surface_temperature_c': 'Yüzey sıcaklığı',
            'dew_point_c': 'Çiğ noktası', 'relative_humidity_pct': 'Bağıl nem', 'dpu_c': 'DPU'}
METHOD_COLORS = ['#8D5300', '#AD350B', '#6743A4']
PREDICTION_STEP = json.loads(RESEARCH_CONFIG.read_text(encoding='utf-8'))['prediction_step_seconds']


def list_experiments(path):
    if not path.is_file():
        return []
    with connect(path) as db:
        return [dict(row) for row in db.execute('SELECT * FROM experiments ORDER BY id DESC')]


def experiment_label(row):
    return f"#{row['id']} · {row['description'] or SCENARIOS.get(row['scenario'], row['scenario'])}"


def list_replays(path):
    if not path.is_file():
        return []
    with connect(path) as db:
        return [dict(row) for row in db.execute('''SELECT e.*, MIN(s.horizon_minutes) AS horizon_minutes
            FROM experiments e LEFT JOIN measurements m ON m.experiment_id=e.id
            LEFT JOIN predictions p ON p.measurement_id=m.id LEFT JOIN method_settings s ON s.id=p.setting_id
            WHERE e.scenario='replay' GROUP BY e.id ORDER BY e.id DESC''')]


def replay_label(row):
    start = datetime.fromisoformat(row['started_at']).strftime('%d.%m.%Y')
    horizon = row['horizon_minutes']
    suffix = f' · {horizon} dk tahmin' if horizon is not None else ''
    return f"Örnek kayıt {row['id']} · {start}{suffix}"


def forecast_at(timestamp, current, decisions_by_time, max_age_seconds):
    """Son tamamlanmış tahmin adımını ve eksik kararın açıklamasını döndürür."""
    now = datetime.fromisoformat(timestamp)
    step_epoch = int(now.timestamp()) // PREDICTION_STEP * PREDICTION_STEP
    step = datetime.fromtimestamp(step_epoch, timezone.utc)
    step_key = step.isoformat(timespec='microseconds')
    table = {row['method']: row for row in decisions_by_time.get(step_key, ())}
    if current['dpu_c'] <= 0:
        return {}, 'Mevcut risk durumuna bak', 'Yüzey çiğ noktasında veya altında.', step
    if (now - datetime.fromisoformat(current['measured_at'])).total_seconds() > max_age_seconds:
        return {}, 'Ölçüm güncelleniyor', 'Yeni ölçüm bekleniyor.', step
    if table:
        return table, 'Geçmiş ölçümler birikiyor', 'Bu yöntem için pencere henüz dolmadı.', step
    return {}, 'Sonraki tahmin bekleniyor', f"Bir sonraki adım {(step + timedelta(seconds=PREDICTION_STEP)):%H:%M:%S} UTC.", step


@st.cache_data(show_spinner=False, max_entries=10)
def replay_data(path, experiment_id, version):
    with connect(path) as db:
        measurements = [dict(row) for row in db.execute('''SELECT * FROM measurements
            WHERE experiment_id=? ORDER BY measured_at, id''', (experiment_id,))]
        predictions = [dict(row) for row in db.execute('''SELECT p.*, s.method, s.horizon_minutes
            FROM predictions p JOIN measurements m ON p.measurement_id=m.id
            JOIN method_settings s ON p.setting_id=s.id WHERE m.experiment_id=? ORDER BY p.predicted_at, p.id''',
            (experiment_id,))]
    return measurements, predictions


def manual_check():
    with st.expander('Elle ölçüm hesabı'):
        with st.form('measurement'):
            air = st.number_input('Ortam sıcaklığı (°C)', value=20.0)
            humidity = st.number_input('Bağıl nem (%)', min_value=0.01, max_value=100.0, value=50.0)
            surface = st.number_input('Elma yüzey sıcaklığı (°C)', value=8.0)
            submitted = st.form_submit_button('Hesapla')
        if submitted:
            try:
                result = calculate_measurement(Measurement('manual', datetime.now(timezone.utc), air, humidity, surface))
            except MeasurementValidationError as exc:
                st.error(str(exc))
                return
            left, right = st.columns(2)
            left.metric('Çiğ noktası', f'{result.dew_point_c:.3f} °C')
            right.metric('DPU', f'{result.dpu_c:.3f} °C')
            st.info(result.current_status)


def monitor():
    st.html('<div class="monitor-heading"><h1>Yoğuşma izleme</h1></div>')
    mode = st.radio('İzleme kaynağı', ('Kayıt oynatma', 'Canlı USB', 'Canlı akış denemesi'), horizontal=True)
    if mode != 'Kayıt oynatma':
        live_view(demo=mode == 'Canlı akış denemesi')
        return
    st.caption('Ticari depo doğrulama verisi (T4)')
    rows = list_replays(DEFAULT_REPLAY_DATABASE)
    if not rows:
        st.info('Henüz oynatma kaydı yok.')
    else:
        by_id = {row['id']: row for row in rows}
        experiment_id = st.selectbox('Oynatılacak kayıt', tuple(by_id),
                                     format_func=lambda value: replay_label(by_id[value]))
        measurements, predictions = replay_data(DEFAULT_REPLAY_DATABASE, experiment_id,
                                                DEFAULT_REPLAY_DATABASE.stat().st_mtime_ns)
        if measurements:
            playback(experiment_id, measurements, predictions)
        else:
            st.info('Bu deneyde ölçüm bulunamadı.')
    manual_check()


@st.fragment(run_every=1)
def live_view(demo):
    path, database = (DEMO_STATE, DEMO_DB) if demo else (LIVE_STATE, DEFAULT_DATABASE)
    if demo:
        st.info('Benzetim · Üretilmiş ölçümler gösteriliyor.')
    try:
        state = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        st.info('Benzetim henüz başlatılmadı.' if demo else 'USB alıcısı henüz başlatılmadı.')
        return
    except (PermissionError, json.JSONDecodeError):
        st.caption('Bağlantı durumu güncelleniyor.')
        return
    status = state['status']
    last_received = state['last_received_at']
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_received)).total_seconds() if last_received else None
    if status == 'receiving' and age is not None and age > 60:
        status = 'disconnected'
    if status == 'receiving':
        st.success('Ölçüm akışı bağlı')
    elif status == 'disconnected':
        st.error('Veri akışı kesildi. Yeni ölçüm bekleniyor.')
    elif status == 'invalid':
        st.warning('Geçersiz ölçüm mesajı alındı. Geçerli ölçüm bekleniyor.')
    elif status == 'stopped':
        st.info('Benzetim tamamlandı. Son kaydedilen ölçümler gösteriliyor.' if demo else 'USB kaydı durduruldu.')
    else:
        st.info('İlk ölçüm bekleniyor.')
    setting_label = 'sabitlenmiş tahmin süresi' if state.get('frozen') else 'deneme tahmin ayarı'
    st.caption(f"Deney #{state['experiment_id']} · {state['horizon']} dk {setting_label}")
    diagnostics = st.columns(3)
    diagnostics[0].metric('Kayıp paket', state['missing_packets'])
    diagnostics[1].metric('Reddedilen paket', state['rejected_packets'])
    minimum = state['minimum_heap_bytes']
    diagnostics[2].metric('En düşük boş RAM', f'{minimum / 1024:.1f} KiB' if minimum is not None else '—')
    if not state['last_sample_at']:
        return
    with connect(database) as db:
        measurements = [dict(row) for row in db.execute('''SELECT * FROM measurements WHERE experiment_id=?
            ORDER BY measured_at DESC LIMIT 120''', (state['experiment_id'],))][::-1]
        if not measurements:
            return
        predictions = [dict(row) for row in db.execute('''SELECT p.*, s.method, s.horizon_minutes FROM predictions p
            JOIN measurements m ON m.id=p.measurement_id JOIN method_settings s ON s.id=p.setting_id
            WHERE m.experiment_id=? AND p.predicted_at>=? ORDER BY p.predicted_at, p.id''',
            (state['experiment_id'], measurements[0]['measured_at']))]
    current = measurements[-1]
    st.subheader('Güncel ölçümler' if status == 'receiving' else 'Son kaydedilen ölçümler')
    st.caption(datetime.fromisoformat(current['measured_at']).strftime('%d.%m.%Y %H:%M:%S UTC'))
    for col, (field, label) in zip(st.columns(5), MEASURES.items(), strict=True):
        unit = '%' if field == 'relative_humidity_pct' else '°C'
        col.metric(label, f'{current[field]:.2f} {unit}')
    if status == 'receiving':
        st.subheader('Erken uyarı tahminleri')
        if current['dpu_c'] <= 0:
            st.warning('Yüzey çiğ noktasında veya altında.')
        start = datetime.fromisoformat(state['stream_started_at'])
        grouped = {}
        for row in predictions:
            if datetime.fromisoformat(row['predicted_at']) >= start:
                grouped.setdefault(row['predicted_at'], []).append(row)
        decisions, waiting, detail, tick = forecast_at(current['measured_at'], current, grouped, 60)
        shown = []
        for col, (method, label) in zip(st.columns(3), METHODS.items(), strict=True):
            col.markdown(f'**{label}**')
            row = decisions.get(method)
            if row is None:
                col.caption(f'{waiting} · {detail}')
            elif row['risk']:
                col.warning(f'Erken uyarı · {tick:%H:%M:%S} UTC')
                if row['first_displayed_at'] is None:
                    shown.append(row['id'])
            else:
                col.success(f'Risk öngörülmedi · {tick:%H:%M:%S} UTC')
        if shown:
            with connect(database) as db:
                for id_ in shown:
                    mark_first_display(db, id_, datetime.now(timezone.utc))
    measurement_chart(measurements, predictions, current['measured_at'], 'DPU ve uyarılar')


def utc_axis():
    return alt.X('Zaman:T', title='Ölçüm zamanı (UTC)', scale=alt.Scale(type='utc'),
                 axis=alt.Axis(format='%H:%M'))


def measurement_chart(measurements, predictions, timestamp, view):
    frame = pd.DataFrame(measurements)
    frame['Zaman'] = pd.to_datetime(frame['measured_at'], utc=True)
    intervals = frame['Zaman'].diff().dt.total_seconds()
    median_interval = intervals.median()
    frame['Kesit'] = (intervals > 2 * median_interval).cumsum()
    cursor = alt.Chart(pd.DataFrame({'Zaman': [pd.Timestamp(timestamp)]})).mark_rule(
        color='#23494C', strokeDash=[4, 4], strokeWidth=1.4).encode(x=utc_axis())
    if view == 'DPU ve uyarılar':
        risks = frame.rename(columns={'dpu_c': 'Fark'})
        trend = alt.Chart(risks).mark_line(color='#007568', strokeWidth=2.5, point=True).encode(
            x=utc_axis(), y=alt.Y('Fark:Q', title='DPU (°C)'), detail='Kesit:N',
            tooltip=[alt.Tooltip('Zaman:T', title='UTC', format='%d.%m %H:%M:%S'),
                     alt.Tooltip('Fark:Q', title='DPU (°C)', format='.2f')])
        zero = alt.Chart(pd.DataFrame({'Sınır': [0]})).mark_rule(color='#9A481D', strokeDash=[5, 4]).encode(y='Sınır:Q')
        measurement_times = [row['measured_at'] for row in measurements]
        warnings = [{'Zaman': pd.Timestamp(row['predicted_at']), 'Yöntem': METHODS[row['method']],
                     'Fark': measurements[bisect_right(measurement_times, row['predicted_at']) - 1]['dpu_c'],
                     'Süre': row['horizon_minutes']} for row in predictions
                    if row['risk'] and measurement_times[0] <= row['predicted_at'] <= timestamp]
        layers = zero + trend + cursor
        if warnings:
            markers = alt.Chart(pd.DataFrame(warnings)).mark_point(filled=True, size=95, stroke='white').encode(
                x=utc_axis(), y='Fark:Q', shape='Yöntem:N',
                color=alt.Color('Yöntem:N', scale=alt.Scale(domain=list(METHODS.values()), range=METHOD_COLORS)),
                tooltip=[alt.Tooltip('Yöntem:N'), alt.Tooltip('Zaman:T', title='UTC', format='%d.%m %H:%M:%S'),
                         alt.Tooltip('Süre:Q', title='Tahmin süresi (dk)')])
            layers += markers
        st.altair_chart(layers.properties(height=285), width='stretch')
        st.caption('Sıfır çizgisi mevcut risk sınırı. İşaretler yöntemlerin geçmiş uyarılarını gösterir.')
        return
    fields = ('relative_humidity_pct',) if view == 'Bağıl nem' else (
        'air_temperature_c', 'surface_temperature_c', 'dew_point_c')
    long = frame.melt(id_vars=['Zaman', 'Kesit'], value_vars=fields, var_name='Alan', value_name='Ölçüm')
    long['Seri'] = long['Alan'].map(MEASURES)
    unit = '%' if view == 'Bağıl nem' else '°C'
    trend = alt.Chart(long).mark_line(point=True, strokeWidth=2).encode(
        x=utc_axis(), y=alt.Y('Ölçüm:Q', title=f'Ölçüm ({unit})', scale=alt.Scale(zero=False)),
        detail='Kesit:N', color=alt.Color('Seri:N', title=None, scale=alt.Scale(range=['#007568', '#B55429', '#6743A4'])),
        tooltip=[alt.Tooltip('Zaman:T', title='UTC', format='%d.%m %H:%M:%S'), 'Seri:N',
                 alt.Tooltip('Ölçüm:Q', format='.2f')])
    st.altair_chart((trend + cursor).properties(height=285), width='stretch')


@st.fragment(run_every=1)
def playback(experiment_id, measurements, predictions):
    measurement_times = [r['measured_at'] for r in measurements]
    grouped = {}
    for prediction in predictions:
        grouped.setdefault(prediction['predicted_at'], []).append(prediction)
    timeline = sorted(set(measurement_times) | grouped.keys())
    warning_steps = [i for i, tick in enumerate(timeline) if any(row['risk'] for row in grouped.get(tick, ()))]
    prefix = f'replay-{experiment_id}'
    cursor, running = f'{prefix}-step', f'{prefix}-running'
    st.session_state.setdefault(cursor, 1)
    st.session_state.setdefault(running, False)
    if st.session_state[running]:
        st.session_state[cursor] = min(st.session_state[cursor] + 1, len(timeline))
        if st.session_state[cursor] == len(timeline):
            st.session_state[running] = False

    def toggle():
        if not st.session_state[running] and st.session_state[cursor] == len(timeline):
            st.session_state[cursor] = 1
        st.session_state[running] = not st.session_state[running]

    controls = st.columns(4)
    controls[0].button('Duraklat' if st.session_state[running] else 'Oynat', on_click=toggle,
                       key=f'{prefix}-play', disabled=len(timeline) < 2)
    controls[1].button('Bir adım ilerle', key=f'{prefix}-next', on_click=lambda: st.session_state.update(
        {cursor: min(st.session_state[cursor] + 1, len(timeline)), running: False}))
    controls[2].button('Başa dön', key=f'{prefix}-reset', on_click=lambda: st.session_state.update(
        {cursor: 1, running: False}))
    next_warning = bisect_right(warning_steps, st.session_state[cursor] - 1)
    controls[3].button('Sonraki uyarıya git', key=f'{prefix}-warning', disabled=next_warning == len(warning_steps),
                       on_click=lambda: st.session_state.update({cursor: warning_steps[next_warning] + 1, running: False}))
    if len(timeline) > 1:
        st.slider('Oynatma adımı', 1, len(timeline), key=cursor,
                  on_change=lambda: st.session_state.update({running: False}))
    timestamp = timeline[st.session_state[cursor] - 1]
    index = bisect_right(measurement_times, timestamp) - 1
    current = measurements[index]
    st.caption(datetime.fromisoformat(timestamp).strftime('%d.%m.%Y %H:%M:%S UTC')
               + f' · Adım {st.session_state[cursor]} / {len(timeline)}')
    st.subheader('Mevcut ölçüm durumu')
    dpu = current['dpu_c']
    if dpu < 0:
        st.warning('Mevcut yoğuşma riski · Yüzey çiğ noktasının altında.')
    elif dpu == 0:
        st.info('Risk sınırında · Yüzey sıcaklığı çiğ noktasına eşit.')
    else:
        st.success('Yüzey çiğ noktasının üzerinde.')
    for col, (label, field, unit) in zip(st.columns(5), (
        ('Ortam sıcaklığı', 'air_temperature_c', '°C'), ('Bağıl nem', 'relative_humidity_pct', '%'),
        ('Yüzey sıcaklığı', 'surface_temperature_c', '°C'), ('Çiğ noktası', 'dew_point_c', '°C'),
        ('DPU', 'dpu_c', '°C')), strict=True):
        col.metric(label, f'{current[field]:.2f} {unit}',
                   help='Yüzey sıcaklığı eksi çiğ noktası.' if field == 'dpu_c' else None)
    epochs = [datetime.fromisoformat(value).timestamp() for value in measurement_times]
    gaps = [b - a for a, b in zip(epochs, epochs[1:]) if b > a]
    max_age = 2 * median(gaps) if gaps else PREDICTION_STEP
    decisions, waiting, waiting_detail, decision_time = forecast_at(timestamp, current, grouped, max_age)
    st.subheader('Erken uyarı tahminleri')
    if predictions:
        st.caption(f"Oynatılan tahmin süresi: {predictions[0]['horizon_minutes']} dakika")
    visible = []
    for col, (method, name) in zip(st.columns(3), METHODS.items(), strict=True):
        row = decisions.get(method)
        if row is None:
            status, style = waiting, 'waiting'
            detail = f'<small>{waiting_detail}</small>'
        elif row['risk']:
            status, style = 'Erken uyarı', 'alert'
            if row['first_displayed_at'] is None:
                visible.append(row['id'])
        else:
            status, style = 'Risk öngörülmedi', 'clear'
        if row is not None:
            detail = f'<small>{decision_time:%H:%M:%S} UTC itibarıyla · {row["horizon_minutes"]} dk tahmin</small>'
        col.html(f'<div class="forecast-card {style}"><strong>{name}</strong><p>{status}</p>{detail}</div>')
    known = st.session_state.setdefault(f'{prefix}-shown', set())
    pending = set(visible) - known
    if pending:
        with connect(DEFAULT_REPLAY_DATABASE) as db:
            displayed_at = datetime.now(timezone.utc)
            for prediction_id in pending:
                mark_first_display(db, prediction_id, displayed_at)
        known.update(pending)

    st.subheader('Ölçüm grafiği')
    view = st.radio('Gösterilecek ölçüm', ('DPU ve uyarılar', 'Sıcaklıklar', 'Bağıl nem'), horizontal=True,
                    key=f'{prefix}-chart')
    measurement_chart(measurements[max(0, index - 119):index + 1], predictions, timestamp, view)


def experiments():
    st.title('Deney yönetimi')
    with st.form('new-experiment', border=True):
        st.subheader('Yeni deney')
        scenario = st.selectbox('Senaryo', tuple(SCENARIOS), format_func=SCENARIOS.get)
        description = st.text_input('Açıklama')
        if st.form_submit_button('Deneyi başlat'):
            initialize(DEFAULT_DATABASE)
            with connect(DEFAULT_DATABASE) as db:
                experiment_id = create_experiment(db, scenario, datetime.now(timezone.utc), description)
            st.success(f'Deney #{experiment_id} açıldı.')
    active = {row['id']: row for row in list_experiments(DEFAULT_DATABASE) if row['ended_at'] is None}
    if not active:
        st.info('Açık deney yok.')
        return
    experiment_id = st.selectbox('Açık deney', tuple(active), format_func=lambda value: experiment_label(active[value]))
    st.success(f"Deney #{experiment_id} sürüyor · {SCENARIOS.get(active[experiment_id]['scenario'], 'Deney')}")
    with st.form('experiment-event'):
        event_choices = ['Kontrol başlangıcı'] if active[experiment_id]['scenario'] == 'control' else [
            'Kapak açıldı', 'Kapak kapatıldı', 'Ilık ürün eklendi']
        event = st.selectbox('Deney olayı', event_choices)
        note = st.text_input('Müdahale notu')
        if st.form_submit_button('Müdahaleyi kaydet'):
            with connect(DEFAULT_DATABASE) as db:
                add_event(db, experiment_id, event, datetime.now(timezone.utc), description=note)
            st.success('Müdahale kaydedildi.')
    if st.button('Deneyi bitir'):
        with connect(DEFAULT_DATABASE) as db:
            finish_experiment(db, experiment_id, datetime.now(timezone.utc))
        st.rerun()
    with connect(DEFAULT_DATABASE) as db:
        events = db.execute('''SELECT started_at, event_type, description FROM experiment_events
            WHERE experiment_id=? ORDER BY started_at DESC, id DESC''', (experiment_id,)).fetchall()
    if events:
        st.subheader('Müdahale günlüğü')
        st.dataframe(pd.DataFrame([dict(row) for row in events]).rename(columns={
            'started_at': 'Zaman (UTC)', 'event_type': 'Müdahale', 'description': 'Not'}), hide_index=True)


def history():
    st.title('Geçmiş kayıtlar')
    source = st.radio('Kayıt kaynağı', ['Oynatma', 'Deney'], horizontal=True)
    path = DEFAULT_REPLAY_DATABASE if source == 'Oynatma' else DEFAULT_DATABASE
    load_rows, format_label = (list_replays, replay_label) if source == 'Oynatma' else (list_experiments, experiment_label)
    rows = {row['id']: row for row in load_rows(path)}
    if not rows:
        st.info('Bu kaynakta henüz deney yok.')
        return
    experiment_id = st.selectbox('Kayıt seç', tuple(rows), format_func=lambda value: format_label(rows[value]))
    start_date = datetime.fromisoformat(rows[experiment_id]['started_at']).date()
    end_date = datetime.fromisoformat(rows[experiment_id]['ended_at']).date() if rows[experiment_id]['ended_at'] else datetime.now(timezone.utc).date()
    bounds = st.date_input('Tarih aralığı (UTC)', (start_date, end_date), key=f'history-{source}-{experiment_id}')
    if len(bounds) != 2:
        return
    start, stop = (datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) for day in bounds)
    with TemporaryDirectory() as temp, connect(path) as db:
        files = export_experiment(db, experiment_id, Path(temp), start, stop + timedelta(days=1))
        for label, file in zip(('Ölçümler ve tahminler', 'Müdahaleler'), files, strict=True):
            frame = pd.read_csv(file)
            st.subheader(label)
            if frame.empty:
                st.info('Seçilen tarih aralığında kayıt yok.')
            else:
                preferred = ['measured_at', 'series_id', *MEASURES, 'method', 'risk', 'horizon_minutes',
                             'started_at', 'event_type', 'description']
                if 'method' in frame:
                    frame['method'] = frame['method'].map(METHODS)
                    frame['risk'] = frame['risk'].map({0: 'Risk öngörülmedi', 1: 'Erken uyarı'})
                columns = [name for name in preferred if name in frame]
                display = frame[columns].rename(columns={**MEASURES, 'measured_at': 'Ölçüm (UTC)',
                    'series_id': 'Sensör serisi', 'method': 'Yöntem', 'risk': 'Karar', 'horizon_minutes': 'Süre (dk)',
                    'started_at': 'Zaman (UTC)', 'event_type': 'Müdahale', 'description': 'Not'})
                st.dataframe(display, hide_index=True)
            st.download_button(f'{label} CSV indir', file.read_bytes(), file_name=file.name, mime='text/csv')


def compare():
    st.title('Yöntem karşılaştırması')
    report_path = ROOT / 'data/processed/parameter_search/parameter_search_report.json'
    if not report_path.is_file():
        st.info('T4 karşılaştırma raporu bulunamadı.')
        return
    report = json.loads(report_path.read_text(encoding='utf-8'))['by_horizon_minutes']
    test_path = ROOT / 'data/processed/t5_evaluation/t5_report.json'
    frozen_path = DEFAULT_FROZEN / 'manifest.json'
    test_valid = False
    if test_path.is_file() and frozen_path.is_file():
        test_report = json.loads(test_path.read_text(encoding='utf-8'))
        test_valid = test_report.get('frozen_manifest_sha256') == sha256(frozen_path)
    if test_valid:
        source = st.radio('Karşılaştırma kaynağı', ('T4 doğrulaması', 'T5 bağımsız testi'), horizontal=True)
        if source == 'T5 bağımsız testi':
            report = {h: {'common_steps': row['common_steps'], 'selected': {
                method: {'metrics': result['records']} for method, result in row['methods'].items()}}
                for h, row in test_report['by_horizon_minutes'].items()}
    else:
        st.caption('T4 doğrulaması · Bağımsız T5 testi, ayarlar sabitlendikten sonra raporlanacak.')
    horizon = st.selectbox('Tahmin süresi (dakika)', tuple(report))
    st.caption(f"{report[horizon]['common_steps']:,} ortak adım".replace(',', '.'))
    rows = []
    for method, candidate in report[horizon]['selected'].items():
        values = candidate['metrics']
        rows.append({'Yöntem': METHODS[method], 'Kesinlik': values['precision'], 'Duyarlılık': values['recall'],
                     'F1': values['f1'], '24 sensör saatinde yanlış alarm': values['false_alarms_per_24_sensor_hours']})
    frame = pd.DataFrame(rows)
    metric = st.radio('Grafikte göster', ('F1', 'Kesinlik', 'Duyarlılık', '24 sensör saatinde yanlış alarm'),
                      horizontal=True)
    domain = [0, 1] if metric != '24 sensör saatinde yanlış alarm' else alt.Undefined
    chart = alt.Chart(frame).mark_bar(color='#007568', cornerRadiusEnd=4).encode(
        y=alt.Y('Yöntem:N', sort=list(METHODS.values()), title=None),
        x=alt.X(f'{metric}:Q', scale=alt.Scale(domain=domain), title=metric),
        tooltip=['Yöntem:N', alt.Tooltip(f'{metric}:Q', format='.4f')])
    st.altair_chart(chart.properties(height=170), width='stretch')
    st.dataframe(frame, hide_index=True, column_config={name: st.column_config.NumberColumn(format='%.4f')
                 for name in frame.columns if name != 'Yöntem'})
