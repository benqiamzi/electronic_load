from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from .analysis_service import AnalysisService
from .capture_file import CaptureEntry, CaptureReader
from .export_service import ExportJob, ExportService


@dataclass(frozen=True, slots=True)
class ReplayState:
    state: str = "idle"
    path: Path | None = None
    progress: float = 0.0
    count: int = 0
    metadata: dict | None = None


class ReplayService(QObject):
    """Run file I/O and ordered replay on the file worker thread."""

    opened = Signal(object)
    changed = Signal(object)
    batch_ready = Signal(object, int)
    error = Signal(str)
    exported = Signal(object, int, str)
    finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._analysis = AnalysisService()
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._tick)
        self._reader = None
        self._iterator = None
        self._next: CaptureEntry | None = None
        self._path = None
        self._count = 0
        self._state = "idle"
        self._speed = 1.0
        self._capture_time = None
        self._due_ms = 0.0
        self._clock_ms = 0.0
        self._started = 0.0
        self._token = 0
        self._waiting = None

    def _publish(self) -> None:
        progress = self._reader.progress if self._reader else 0.0
        self.changed.emit(ReplayState(self._state, self._path, progress, self._count,
                                      dict(self._reader.metadata) if self._reader else None))

    @Slot(object)
    def load(self, path: Path) -> None:
        self._close_reader()
        self._path = path
        self._analysis.reset()
        self._count = 0
        self._clock_ms = self._due_ms = 0.0
        self._capture_time = None
        self._waiting = None
        self.opened.emit(path)
        try:
            self._reader = CaptureReader(path)
            self._iterator = iter(self._reader)
            self._advance()
            self._state = "ready" if self._next else "ended"
            self._publish()
        except Exception as exc:
            self._fail(exc)

    def _advance(self) -> None:
        self._next = next(self._iterator, None)
        while self._next is not None and self._next.record is None:
            self._analysis.reset()
            self._capture_time = None
            self._next = next(self._iterator, None)
        if self._next is not None:
            record = self._next.record
            timestamp = record.start_timestamp_us if hasattr(record, "start_timestamp_us") else record.timestamp_us
            if self._capture_time is not None:
                self._due_ms += max(0, timestamp - self._capture_time) / 1000
            self._capture_time = timestamp

    def _now_ms(self) -> float:
        return self._clock_ms + (monotonic() - self._started) * self._speed * 1000

    @Slot(str, float)
    def control(self, action: str, value: float) -> None:
        if action == "speed" and value > 0:
            if self._state == "playing":
                self._clock_ms = self._now_ms()
                self._started = monotonic()
            self._speed = value
            self._schedule()
        elif action == "stop" and self._path is not None:
            self.load(self._path)
        elif action == "pause" and self._state == "playing":
            self._pause()
            self._publish()
        elif action == "play" and self._next is not None and self._state != "playing":
            self._started = monotonic()
            self._state = "playing"
            self._publish()
            self._schedule()
        elif action == "step" and self._next is not None and self._waiting is None:
            self._pause()
            self._clock_ms = self._due_ms
            self._tick(single=True)

    def _pause(self) -> None:
        if self._state == "playing":
            self._clock_ms = self._now_ms()
        self._timer.stop()
        self._state = "paused"

    def _schedule(self) -> None:
        if self._state == "playing" and self._waiting is None and self._next is not None:
            delay = max(0.0, (self._due_ms - self._now_ms()) / self._speed)
            self._timer.start(min(1000, int(delay + 0.999)))

    @Slot()
    def _tick(self, single: bool = False) -> None:
        if self._waiting is not None or (not single and self._state != "playing"):
            return
        batch = []
        try:
            while self._next is not None and (single or self._due_ms <= self._now_ms()) and len(batch) < 96:
                entry = self._next
                self._count += 1
                batch.append(self._analysis.consume(self._count, entry.record, entry.provenance))
                self._advance()
                if single:
                    break
        except Exception as exc:
            self._fail(exc)
        if batch:
            self._token += 1
            self._waiting = self._token
            self.batch_ready.emit(tuple(batch), self._token)
        if self._next is None and self._state != "error":
            self._state = "ended"
        self._publish()
        self._schedule()

    @Slot(int)
    def acknowledge(self, token: int) -> None:
        if token == self._waiting:
            self._waiting = None
            self._schedule()

    @Slot(object)
    def export(self, job: ExportJob) -> None:
        was_playing = self._state == "playing"
        if was_playing:
            self._pause()
        try:
            count = ExportService().export(job, QThread.currentThread().isInterruptionRequested)
            self.exported.emit(job.destination, count, "")
        except Exception as exc:
            self.exported.emit(job.destination, 0, str(exc))
        if was_playing:
            self.control("play", 0)

    def _close_reader(self) -> None:
        self._timer.stop()
        if self._reader is not None:
            self._reader.close()
        self._reader = self._iterator = self._next = None

    def _fail(self, exc: Exception) -> None:
        self._close_reader()
        self._state = "error"
        self.error.emit(f"回放文件错误：{exc}")
        self._publish()

    @Slot()
    def shutdown(self) -> None:
        self._close_reader()
        self.finished.emit()
