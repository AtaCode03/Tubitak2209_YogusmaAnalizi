"""Tüm sensör serilerine uygulanan ortak UTC bölüm sınırları."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

RESEARCH_CONFIG = Path(__file__).resolve().parents[1] / "config" / "research.json"


@dataclass(frozen=True)
class SplitBoundaries:
    validation_start: datetime
    test_start: datetime

    @classmethod
    def load(cls, path: Path = RESEARCH_CONFIG) -> "SplitBoundaries":
        config = json.loads(path.read_text(encoding="utf-8"))["split"]
        return cls(datetime.fromisoformat(config["validation_start_utc"]),
                   datetime.fromisoformat(config["test_start_utc"]))

    def partition(self, timestamp: datetime) -> str:
        if timestamp.utcoffset() is None:
            raise ValueError("Bölümleme için saat dilimi bilgili zaman gerekli")
        if timestamp < self.validation_start:
            return "train"
        if timestamp < self.test_start:
            return "validation"
        return "test"
