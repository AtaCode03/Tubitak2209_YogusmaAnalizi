"""Yoğuşma projesinin Streamlit arayüzü."""

from pathlib import Path

import streamlit as st

from runtime.dashboard import compare, experiments, history, monitor

st.set_page_config(page_title='Yoğuşma izleme', layout='wide')
st.html(Path(__file__).with_name('dashboard.css'))
st.sidebar.markdown('## Yoğuşma izleme')
pages = {'İzleme': monitor, 'Deney yönetimi': experiments, 'Geçmiş kayıtlar': history,
         'Yöntem karşılaştırması': compare}
page = st.sidebar.radio('Ekran', tuple(pages), label_visibility='collapsed')
pages[page]()
