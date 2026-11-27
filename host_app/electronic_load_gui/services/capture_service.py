import csv
from dataclasses import dataclass, replace
from datetime import datetime
import logging
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from ..devices.drpd.device import DrpdDevice
from .analysis_service import AnalysisService
from .capture_file import CaptureJournal, CaptureSnapshot
from .log_service import LogService
from .telemetry_service import TelemetryService
from .trigger_service import TriggerService


@dataclass(frozen=True, slots=True)
class CaptureMetrics:
    """Host counters for the current raw journal."""

    received: int = 0
    archived: int = 0
    capture_read_errors: int = 0
    analysis_errors: int = 0
    analysis_ns: int = 0
    crc_unavailable: int = 0
    journal_errors: int = 0
    pending: int = 0
    peak_pending: int = 0
    backpressure_count: int = 0

    @property
    def analyzed(self) -> int:
        return self.received - self.analysis_errors


@dataclass(frozen=True, slots=True)
class DeviceState:
    connection: str = "disconnected"
    port: str = ""
    identity: str = ""
    firmware: str = ""
    sink_state: str = ""
    device_capture: bool | None = None
    capture: str = "idle"
    cycle_ns: float | None = None
    last_communication: str = ""
    error: str = ""
    queue: int | None = None
    peak_queue: int = 0
    count: int = 0
    crc_errors: int = 0
    diagnostic_count: int = 0
    waiting_for_ui: bool = False
    epr_config: str = ""
    firmware_epr_count: int | None = None
    epr_observed: bool = False
    epr_pdo_count: int = 0
    metrics: CaptureMetrics = CaptureMetrics()


class CaptureService(QObject):
    """Own DRPD I/O, analysis and the raw journal on a single worker thread."""

    changed = Signal(object)
    batch_ready = Signal(object, int)
    error = Signal(str)
    snapshot_ready = Signal(object)
    capture_cleared = Signal()
    finished = Signal()
    history_error = Signal(str)
    session_sample = Signal(str, object)
    stream_changed = Signal(str)

    def __init__(self, journal_path: Path, device_factory=DrpdDevice, log_path: Path | None = None) -> None:
        super().__init__()
        self._path = journal_path
        self._log_path = log_path
        self._history = None
        self._indexing = False
        self._session_id = ""
        self._session_index = 0
        self._last_sample_us = None
        self._csv_file = None
        self._csv = None
        self._device = device_factory(self)
        self._protocol = self._device.protocol
        self._transport = self._device.transport
        self._capture = self._device.capture
        self._state = DeviceState()
        self._metrics = CaptureMetrics()
        self._analysis = AnalysisService()
        self._journal = None
        self._batch = []
        self._token = 0
        self._waiting = None
        self._disconnecting = False
        self._closing = False
        self._disk_failed = False
        self._start_after_trigger = False
        self.telemetry = TelemetryService(
            self._protocol,
            lambda: self._state.connection == "connected" and self._state.capture in ("idle", "running")
            and self._waiting is None,
            self,
        )
        self.telemetry.sampled.connect(self._sample)
        self.trigger = TriggerService(
            self._protocol, lambda: self._state.connection == "connected" and self._state.capture == "idle", self
        )
        self.trigger.changed.connect(self._trigger_changed)
        self._timer = QTimer(self, interval=60)
        self._timer.timeout.connect(self._poll)
        self._capture.capture_received.connect(self._receive)
        self._capture.capture_count_changed.connect(self._queue_count)
        self._capture.drain_finished.connect(self._drain_finished)
        self._capture.error_occurred.connect(self._capture_error)
        self._transport.error_occurred.connect(self._error)
        self._protocol.disconnected.connect(self._disconnected)

    def _publish(self, **changes) -> None:
        state = replace(self._state, metrics=self._metrics, **changes)
        if state != self._state:
            self._state = state
            self.changed.emit(state)

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%H:%M:%S")

    @Slot(str)
    def connect_port(self, port: str) -> None:
        if self._transport.is_open or self._closing:
            return
        self._publish(connection="connecting", port=port, error="", identity="", firmware="", sink_state="",
                      cycle_ns=None, queue=None, device_capture=None, last_communication="", epr_config="",
                      firmware_epr_count=None)
        if not self._transport.open(port):
            self._publish(connection="error", port="")
            return
        self._protocol.query_text("*IDN?", self._identified, errback=self._connection_error)

    def _identified(self, value: str) -> None:
        fields = next(csv.reader([value]), [])
        if len(fields) < 4 or fields[1].strip().casefold() != "dr.pd":
            self._connection_error(f"所选端口的设备标识不是 Dr. PD：{value}")
            return
        self._publish(identity=value, firmware=fields[-1], last_communication=self._now())
        self._capture.get_cycle_time(self._connected_cycle, errback=self._connection_error)

    def _connected_cycle(self, value: float) -> None:
        self._publish(cycle_ns=value)
        self._protocol.query_text("BUS:CC:CAP:EN?", self._connected_capture, errback=self._connection_error)

    def _connected_capture(self, value: str) -> None:
        if value not in ("ON", "OFF"):
            self._connection_error(f"DRPD 返回了未知捕获开关状态：{value}")
            return
        self._publish(connection="connected", last_communication=self._now(), device_capture=value == "ON")
        self.refresh_status()
        self.telemetry.activate(self._state.firmware)
        self.trigger.activate(self._state.firmware)

    @Slot()
    def refresh_status(self) -> None:
        if self._state.connection != "connected":
            return
        def sink_status(value):
            self._publish(sink_state=value, last_communication=self._now())

        def epr_state(value):
            self._publish(epr_config=value if value in ("ON", "OFF") else "",
                          last_communication=self._now())

        def epr_count(value):
            self._publish(firmware_epr_count=int(value) if len(value) <= 10 and value.isdecimal() else None,
                          last_communication=self._now())

        self._protocol.query_text("SINK:STATUS?", sink_status, errback=self._error, key="ui-sink-status")
        self._protocol.query_text("SINK:EPR:EN?", epr_state, errback=self._error, key="ui-epr-state")
        self._protocol.query_text("SINK:CAP:EPR:COUNT?", epr_count, errback=self._error, key="ui-epr-count")

    @Slot()
    def query_source(self) -> None:
        if self._state.capture == "running":
            self._protocol.command("SINK:INQ GET_SOURCE_CAP", errback=self._error, key="ui-source-inquiry")

    @Slot()
    def start(self) -> None:
        if self._state.connection != "connected" or self._state.capture != "idle" or self._closing:
            return
        if self.trigger.writing:
            self._error("请等待 Trigger 配置读回后再启动捕获")
            return
        if self.trigger.loading_initial_config:
            self._start_after_trigger = True
            return
        if self._disk_failed:
            self._error("捕获文件写入失败。请保存可读部分并清空本次捕获后重试。")
            return
        session_id = uuid4().hex
        metadata = {
            "session_id": session_id, "firmware_version": self._state.firmware, "port": self._state.port,
            "provenance": "real", "capture_cycle_ns": self._state.cycle_ns,
        }
        trigger = self.trigger.metadata()
        if trigger is not None:
            metadata["trigger"] = trigger
        try:
            if self._journal is None:
                self._journal = CaptureJournal(self._path, metadata)
            else:
                self._journal.boundary(**metadata)
                self._journal.flush()
        except OSError as exc:
            self._disk_failed = True
            self._metrics = replace(self._metrics, journal_errors=self._metrics.journal_errors + 1)
            self._error(f"无法写入捕获文件：{exc}")
            return
        self._session_id, self._session_index = session_id, 0
        self._last_sample_us = None
        self._indexing = self._log_path is not None
        if self._indexing:
            self._index(lambda db: db.start(session_id, metadata))
        self._analysis.reset()
        self._publish(capture="starting", error="", peak_queue=0, epr_observed=False, epr_pdo_count=0)
        self._set_capture(True, self._started)

    def _set_capture(self, enabled: bool, complete) -> None:
        setting = "ON" if enabled else "OFF"

        def confirmed(value):
            actual = value == "ON" if value in ("ON", "OFF") else None
            self._publish(device_capture=actual, last_communication=self._now())
            if value != setting:
                self._capture_switch_error(f"DRPD 捕获开关未切换到 {setting}，回读为 {value}")
            else:
                complete()

        def written():
            self._protocol.query_text("BUS:CC:CAP:EN?", confirmed, errback=self._capture_switch_error)

        self._protocol.command(f"BUS:CC:CAP:EN {setting}", callback=written, errback=self._capture_switch_error)

    def _started(self) -> None:
        if self._state.capture == "starting":
            self._publish(capture="running")
            self._timer.start()
            self._poll()

    @Slot()
    def stop(self) -> None:
        self._start_after_trigger = False
        if self._state.capture not in ("running", "starting"):
            return
        self._timer.stop()
        self._publish(capture="stopping")
        self._set_capture(False, self._capture_off)

    def _capture_off(self) -> None:
        if self._disk_failed:
            self._stopped()
            return
        self._publish(capture="draining")
        self._timer.start()
        self._poll()

    def _stopped(self) -> None:
        self._timer.stop()
        self.stop_stream()
        logging.getLogger(__name__).info("Capture stopped. Device queue peak %d; firmware drop count unavailable",
                                         self._state.peak_queue)
        self._publish(capture="idle", waiting_for_ui=False)
        if self._disconnecting:
            self._transport.close()

    @Slot()
    def _poll(self) -> None:
        if self._state.capture not in ("running", "draining"):
            return
        if self._waiting is not None:
            if not self._state.waiting_for_ui:
                logging.getLogger(__name__).warning("DRPD capture polling paused by GUI backpressure")
                self._metrics = replace(self._metrics, backpressure_count=self._metrics.backpressure_count + 1)
            self._publish(waiting_for_ui=True)
            return
        self._capture.drain_capture_queue()

    @Slot(int)
    def _queue_count(self, count: int) -> None:
        self._publish(queue=count, peak_queue=max(count, self._state.peak_queue), last_communication=self._now())

    @Slot(object)
    def _receive(self, record) -> None:
        started = perf_counter_ns()
        self._session_index += 1
        event = self._analysis.consume(self._metrics.received + 1, record, "real",
                                       self._session_id, self._session_index)
        duration = perf_counter_ns() - started
        self._batch.append(event)
        self._metrics = replace(
            self._metrics,
            received=event.index,
            analysis_errors=self._metrics.analysis_errors + any(d.code == "analysis_error" for d in event.diagnostics),
            analysis_ns=self._metrics.analysis_ns + duration,
            crc_unavailable=self._metrics.crc_unavailable + (event.crc == "unavailable"),
            pending=len(self._batch),
            peak_pending=max(self._metrics.peak_pending, len(self._batch)),
        )
        if self._disk_failed:
            return
        try:
            self._journal.append(record, "real")
        except OSError as exc:
            self._journal_failed(exc)

    def _journal_failed(self, exc: OSError) -> None:
        self._disk_failed = True
        self._metrics = replace(self._metrics, journal_errors=self._metrics.journal_errors + 1)
        self._error(f"捕获写入失败，已停止读取；已落盘部分仍可保存：{exc}")
        if self._state.capture == "draining":
            self._stopped()
        else:
            self.stop()

    def _deliver(self) -> None:
        if not self._batch:
            return
        if not self._disk_failed:
            try:
                snapshot = self._journal.flush()
                self._metrics = replace(self._metrics, archived=snapshot.count)
            except OSError as exc:
                self._journal_failed(exc)
        events = tuple(self._batch)
        self._batch.clear()
        self._index(lambda db: db.add(events))
        if self._csv is not None:
            try:
                self._csv.writerows((event.session_id, event.session_index, event.timestamp_us,
                                     event.sender, event.receiver, event.sop, event.message_name,
                                     event.crc, event.event_type) for event in events)
                self._csv_file.flush()
            except OSError as exc:
                self.history_error.emit(f"实时 CSV 写入失败：{exc}")
                self.stop_stream()
        self._token += 1
        self._waiting = self._token
        last = events[-1]
        self._publish(count=last.index, crc_errors=self._state.crc_errors + sum(e.crc == "invalid" for e in events),
                      diagnostic_count=self._state.diagnostic_count + sum(len(e.diagnostics) for e in events),
                      last_communication=self._now(), epr_observed=last.epr_observed, epr_pdo_count=last.epr_pdo_count)
        self.batch_ready.emit(events, self._token)

    @Slot(int)
    def _drain_finished(self, count: int) -> None:
        self._deliver()
        if (not count or self._disk_failed) and self._state.capture == "draining":
            self._stopped()

    @Slot(int)
    def acknowledge(self, token: int) -> None:
        if token == self._waiting:
            self._waiting = None
            self._metrics = replace(self._metrics, pending=0)
            self._publish(waiting_for_ui=False)

    @Slot()
    def snapshot(self) -> None:
        snapshot = None
        if self._journal is not None:
            if not self._disk_failed:
                try:
                    snapshot = self._journal.flush()
                    self._metrics = replace(self._metrics, archived=snapshot.count)
                    self._publish()
                except OSError as exc:
                    self._journal_failed(exc)
            snapshot = CaptureSnapshot(self._path, self._journal.size, self._journal.committed_count)
        self.snapshot_ready.emit(snapshot)

    @Slot()
    def clear_capture(self) -> None:
        if self._state.capture != "idle":
            return
        self._close_journal()
        self._disk_failed = False
        self._metrics = CaptureMetrics()
        self._waiting = None
        self._analysis.reset()
        self._publish(count=0, crc_errors=0, diagnostic_count=0, peak_queue=0, epr_observed=False, epr_pdo_count=0,
                      waiting_for_ui=False, error="")
        self.capture_cleared.emit()

    @Slot()
    def disconnect_port(self) -> None:
        if not self._transport.is_open:
            self._disconnected()
            return
        self._disconnecting = True
        self._publish(connection="disconnecting")
        if self._state.capture == "idle":
            self._transport.close()
        else:
            self.stop()

    def _error(self, error) -> None:
        message = str(error)
        self._publish(error=message)
        self.error.emit(message)

    def _connection_error(self, error) -> None:
        self._error(error)
        self._publish(connection="error")
        self._transport.close()

    def _capture_switch_error(self, error) -> None:
        self._error(error)
        self._stopped()

    @Slot(str)
    def _capture_error(self, error: str) -> None:
        self._metrics = replace(self._metrics, capture_read_errors=self._metrics.capture_read_errors + 1)
        self._deliver()
        self._error(error)
        if self._state.capture == "draining":
            self._stopped()
        else:
            self.stop()

    @Slot()
    def _disconnected(self) -> None:
        self._timer.stop()
        self._start_after_trigger = False
        self.telemetry.disconnect()
        self.trigger.disconnect()
        before = self._state.connection
        self._deliver()
        self.stop_stream()
        self._waiting = None
        self._metrics = replace(self._metrics, pending=0)
        expected = self._disconnecting or self._closing or before == "error"
        if not expected and before in ("connected", "connecting") and not self._state.error:
            self._error("DRPD 串口已断开")
        self._disconnecting = False
        self._analysis.reset()
        self._publish(connection="disconnected" if expected and before != "error" else "error",
                      port="", capture="idle", device_capture=None, queue=None, waiting_for_ui=False, sink_state="",
                      cycle_ns=None, epr_config="", firmware_epr_count=None,
                      epr_observed=False, epr_pdo_count=0)
        if self._closing:
            self._close_journal()
            if self._history is not None:
                self._history.close()
            self.finished.emit()

    @Slot(object)
    def _trigger_changed(self, state):
        if self._start_after_trigger and not state.busy:
            self._start_after_trigger = False
            self.start()

    @Slot(object)
    def _sample(self, sample):
        if self._state.capture == "running" and self._session_id:
            if self._last_sample_us is not None and sample.timestamp_us < self._last_sample_us:
                self._error("设备时钟已重置，已停止当前捕获")
                self.stop()
                return
            self._last_sample_us = sample.timestamp_us
            self._index(lambda db: db.add_sample(self._session_id, sample))
            self.session_sample.emit(self._session_id, sample)

    def _index(self, operation):
        if not self._indexing:
            return
        try:
            if self._history is None:
                self._history = LogService(self._log_path)
            operation(self._history)
        except Exception as exc:
            self._indexing = False
            self.history_error.emit(f"历史日志写入失败：{exc}")

    @Slot(object)
    def start_stream(self, path: Path):
        if self._csv_file is not None:
            return
        try:
            self._csv_file = path.open("x", newline="", encoding="utf-8-sig")
            self._csv = csv.writer(self._csv_file)
            self._csv.writerow(("Session", "Frame", "Timestamp µs", "Sender", "Receiver",
                                "SOP", "Message", "CRC", "Event"))
            self._csv_file.flush()
            self.stream_changed.emit(str(path))
        except OSError as exc:
            self.history_error.emit(f"无法启动实时 CSV：{exc}")
            self.stop_stream()

    @Slot()
    def stop_stream(self):
        file, self._csv_file = self._csv_file, None
        self._csv = None
        if file is not None:
            try:
                file.close()
            except OSError as exc:
                self.history_error.emit(f"无法关闭实时 CSV：{exc}")
            self.stream_changed.emit("")

    def _close_journal(self) -> None:
        journal, self._journal = self._journal, None
        if journal is not None:
            try:
                journal.close()
            except OSError as exc:
                self._metrics = replace(self._metrics, journal_errors=self._metrics.journal_errors + 1)
                self._error(f"关闭捕获文件失败：{exc}")

    @Slot()
    def shutdown(self) -> None:
        self._closing = True
        self.disconnect_port()
