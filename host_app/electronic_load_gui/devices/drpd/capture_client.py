from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import isfinite

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .capture_record import CaptureRecord, CaptureRecordError, CaptureRecordParser, FirmwareEvent
from .protocol_client import DrpdProtocolClient, DrpdProtocolError, ErrorCallback, ScpiDeviceError


Capture = CaptureRecord | FirmwareEvent


@dataclass(slots=True)
class _Drain:
    remaining: int = 0
    received: int = 0


class CaptureClient(QObject):
    """Read DRPD capture records asynchronously on the owning Qt event loop."""

    capture_received = Signal(object)
    capture_count_changed = Signal(object)
    capture_state_changed = Signal(object)
    drain_finished = Signal(int)
    error_occurred = Signal(str)

    def __init__(
        self,
        protocol: DrpdProtocolClient,
        parent: QObject | None = None,
        *,
        poll_interval_ms: int = 100,
        max_records_per_drain: int = 32,
    ) -> None:
        super().__init__(parent)
        if poll_interval_ms <= 0 or max_records_per_drain <= 0:
            raise ValueError("poll_interval_ms and max_records_per_drain must be positive")
        self._protocol = protocol
        self._max_records = max_records_per_drain
        self._cycle_time_ns: float | None = None
        self._capture_enabled: bool | None = None
        self._drain: _Drain | None = None
        self._poll = QTimer(self, interval=poll_interval_ms)
        self._poll.timeout.connect(self.drain_capture_queue)
        protocol.disconnected.connect(self._on_disconnected)

    @property
    def cycle_time_ns(self) -> float | None:
        return self._cycle_time_ns

    def start_capture(self) -> bool:
        return self._set_capture(True)

    def stop_capture(self) -> bool:
        return self._set_capture(False)

    def _set_capture(self, enabled: bool) -> bool:
        def written() -> None:
            self._capture_enabled = enabled
            self.capture_state_changed.emit(enabled)

        state = "ON" if enabled else "OFF"
        return self._protocol.command(f"BUS:CC:CAP:EN {state}", callback=written,
                                      errback=self._report_error)

    def get_cycle_time(
        self, callback: Callable[[float], None] | None = None, *,
        errback: ErrorCallback | None = None,
    ) -> bool:
        report = errback or self._report_error

        def received(line: str) -> None:
            try:
                cycle_time = float(line)
            except ValueError:
                cycle_time = float("nan")
            if not isfinite(cycle_time) or cycle_time <= 0:
                report(DrpdProtocolError(f"DRPD 捕获周期无效: {line!r}"))
                return
            self._cycle_time_ns = cycle_time
            if callback is not None:
                callback(cycle_time)

        return self._protocol.query_text("BUS:CC:CAP:CYCLETIME?", received, errback=report)

    def get_capture_count(
        self, callback: Callable[[int], None] | None = None, *,
        errback: ErrorCallback | None = None,
    ) -> bool:
        report = errback or self._report_error

        def received(line: str) -> None:
            if not 1 <= len(line) <= 10 or not line.isdecimal() or int(line) > 0xFFFFFFFF:
                report(DrpdProtocolError(f"DRPD 捕获数量无效: {line!r}"))
                return
            count = int(line)
            self.capture_count_changed.emit(count)
            if callback is not None:
                callback(count)

        return self._protocol.query_text("BUS:CC:CAP:COUNT?", received, errback=report)

    def fetch_next_capture(
        self, callback: Callable[[Capture | None], None] | None = None, *,
        errback: ErrorCallback | None = None,
    ) -> bool:
        """Read one record. An empty queue completes with None."""
        report = errback or self._report_error

        def failed(error: DrpdProtocolError) -> None:
            if isinstance(error, ScpiDeviceError) and error.code == -200:
                self.capture_count_changed.emit(0)
                if callback is not None:
                    callback(None)
                return
            report(error)

        def fetch(cycle_time: float) -> bool:
            def received(payload: bytes) -> None:
                try:
                    record = CaptureRecordParser.parse(payload, cycle_time)
                except CaptureRecordError as exc:
                    report(DrpdProtocolError(f"DRPD 捕获记录无效: {exc}"))
                    return
                self.capture_received.emit(record)
                if callback is not None:
                    callback(record)

            return self._protocol.query_binary("BUS:CC:CAP:DATA?", received, errback=failed)

        if self._cycle_time_ns is None:
            return self.get_cycle_time(fetch, errback=report)
        return fetch(self._cycle_time_ns)

    @Slot()
    def drain_capture_queue(self) -> bool:
        """Fetch up to the configured limit of the records currently queued."""
        if self._drain is not None:
            return False
        drain = _Drain()
        self._drain = drain

        def failed(error: DrpdProtocolError) -> None:
            if self._drain is drain:
                self._drain = None
            self._report_error(error)

        def read_next() -> None:
            if self._drain is not drain:
                return
            if drain.remaining == 0:
                self._drain = None
                self.drain_finished.emit(drain.received)
                return
            self.fetch_next_capture(received, errback=failed)

        def received(record: Capture | None) -> None:
            if record is None:
                drain.remaining = 0
            else:
                drain.received += 1
                drain.remaining -= 1
            read_next()

        def counted(count: int) -> None:
            drain.remaining = min(count, self._max_records)
            read_next()

        return self.get_capture_count(counted, errback=failed)

    def start_polling(self) -> None:
        self._poll.start()
        if not self.drain_capture_queue() and self._drain is None:
            self._poll.stop()

    def stop_polling(self) -> None:
        self._poll.stop()

    @Slot()
    def _on_disconnected(self) -> None:
        self.stop_polling()
        self._cycle_time_ns = None
        self._drain = None
        if self._capture_enabled is not None:
            self._capture_enabled = None
            self.capture_state_changed.emit(None)

    def _report_error(self, error: DrpdProtocolError) -> None:
        self.error_occurred.emit(str(error))
