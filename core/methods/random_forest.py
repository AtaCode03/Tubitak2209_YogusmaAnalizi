"""Kaydedilen Random Forest modeli için tahmin girişi."""

from core.windows import FEATURE_NAMES


def predict(model, features, dpu_c):
    if dpu_c is None or not dpu_c > 0 or features is None:
        return None
    if len(features) != len(FEATURE_NAMES):
        raise ValueError('Random Forest özellik sayısı uyuşmuyor')
    return bool(model.predict([features])[0])
