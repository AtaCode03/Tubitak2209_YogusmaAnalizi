"""Sıcaklıklar °C, bağıl nem yüzde; zamanlar saat dilimi bilgili UTC."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Measurement:
    series_id: str
    timestamp: datetime
    air_temperature_c: float
    relative_humidity_pct: float
    surface_temperature_c: float


@dataclass(frozen=True)
class ComputedMeasurement:
    measurement: Measurement
    dew_point_c: float
    dpu_c: float

    @property
    def current_status(self) -> str:
        if self.dpu_c < 0:
            return "Mevcut yoğuşma riski"
        if self.dpu_c == 0:
            return "Risk sınırında"
        return "Mevcut DPU pozitif"
