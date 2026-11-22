"""Adım 1 hesaplama kontrol ekranı. Canlı sensör bağlantısı içermez."""

from datetime import datetime, timezone

import streamlit as st

from core.contracts import Measurement
from core.physics import calculate_measurement
from core.validation import MeasurementValidationError

st.set_page_config(page_title="Yoğuşma · Hesaplama kontrolü", page_icon="🌡️")
st.title("Yoğuşma hesabı")
st.caption("Adım 1 · Elle girilen örnek ölçüm. Canlı sensör verisi veya erken uyarı tahmini değildir.")
with st.form("measurement"):
    air = st.number_input("Ortam sıcaklığı (°C)", value=20.0)
    humidity = st.number_input("Bağıl nem (%)", min_value=0.01, max_value=100.0, value=50.0)
    surface = st.number_input("Elma yüzey sıcaklığı (°C)", value=8.0)
    submitted = st.form_submit_button("Hesapla")
if submitted:
    try:
        result = calculate_measurement(Measurement("manual", datetime.now(timezone.utc), air, humidity, surface))
        left, right = st.columns(2)
        left.metric("Çiğ noktası", f"{result.dew_point_c:.3f} °C")
        right.metric("DPU", f"{result.dpu_c:.3f} °C")
        st.info(result.current_status)
        st.caption("Bu sonuç anlık koşulu gösterir; süre koşulunu sağlayan bir risk olayını doğrulamaz.")
    except MeasurementValidationError as exc:
        st.error(str(exc))
