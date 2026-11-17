from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import TextIO

from .domain import MeasurementSnapshot


class CsvDataLogger:
    def __init__(self) -> None:
        self._file: TextIO | None = None
        self._writer: csv.writer | None = None
        self.path: Path | None = None

    @property
    def is_active(self) -> bool:
        return self._file is not None

    def start(self, path: str | Path) -> None:
        self.stop()
        self.path = Path(path)
        self._file = self.path.open("w", newline="", encoding="utf-8-sig")
        self._writer = csv.writer(self._file)
        self._writer.writerow(
            [
                "timestamp",
                "voltage_V",
                "current_A",
                "power_W",
                "left_temperature_C",
                "right_temperature_C",
            ]
        )
        self._file.flush()

    def append(self, snapshot: MeasurementSnapshot) -> None:
        if self._writer is None or self._file is None:
            return
        self._writer.writerow(
            [
                datetime.now().astimezone().isoformat(timespec="milliseconds"),
                f"{snapshot.voltage_v:.4f}",
                f"{snapshot.current_a:.4f}",
                f"{snapshot.power_w:.4f}",
                f"{snapshot.left_temperature_c:.2f}",
                f"{snapshot.right_temperature_c:.2f}",
            ]
        )
        self._file.flush()

    def stop(self) -> None:
        if self._file is not None:
            self._file.close()
        self._file = None
        self._writer = None
