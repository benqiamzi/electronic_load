import logging
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from ..devices.drpd.device import DrpdDevice
from ..devices.drpd.transport import DrpdTransport
from .capture_service import CaptureService, DeviceState


class DeviceService(QObject):
    """GUI-thread facade for the independent DRPD worker and its serial ownership."""

    changed = Signal(object)
    error = Signal(str)
    batch_ready = Signal(object, int)
    snapshot_ready = Signal(object)
    capture_cleared = Signal()
    finished = Signal()

    _connect = Signal(str)
    disconnect_port = Signal()
    refresh_status = Signal()
    query_source = Signal()
    start_capture = Signal()
    stop_capture = Signal()
    acknowledge = Signal(int)
    snapshot = Signal()
    clear_capture = Signal()
    _close = Signal()

    def __init__(self, parent: QObject, *, journal_path: Path | None = None, device_factory=DrpdDevice) -> None:
        super().__init__(parent)
        self.state = DeviceState()
        self._path = journal_path
        self._owns_path = journal_path is None
        self._factory = device_factory
        self._thread = None
        self._worker = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    @staticmethod
    def available_ports() -> list[tuple[str, str]]:
        ports = DrpdTransport.available_ports()
        ports.sort(key=lambda port: ((port.vendorIdentifier(), port.productIdentifier()) != (0x2E8A, 0x000A),
                                     port.portName()))
        return [(port.portName(), f"{port.portName()} — {port.description()}".rstrip(" —")) for port in ports]

    def _start_worker(self) -> None:
        if self._path is None:
            fd, name = tempfile.mkstemp(prefix="electronic-load-pd-", suffix=".drpd")
            os.close(fd)
            self._path = Path(name)
        thread = QThread(self)
        worker = CaptureService(self._path, self._factory)
        worker.moveToThread(thread)
        self._connect.connect(worker.connect_port)
        self.disconnect_port.connect(worker.disconnect_port)
        self.refresh_status.connect(worker.refresh_status)
        self.query_source.connect(worker.query_source)
        self.start_capture.connect(worker.start)
        self.stop_capture.connect(worker.stop)
        self.acknowledge.connect(worker.acknowledge)
        self.snapshot.connect(worker.snapshot)
        self.clear_capture.connect(worker.clear_capture)
        self._close.connect(worker.shutdown)
        worker.changed.connect(self._update)
        worker.error.connect(self.error)
        worker.batch_ready.connect(self.batch_ready)
        worker.snapshot_ready.connect(self.snapshot_ready)
        worker.capture_cleared.connect(self.capture_cleared)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self.finished)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot(object)
    def _update(self, state: DeviceState) -> None:
        self.state = state
        self.changed.emit(state)

    def connect_port(self, port: str) -> None:
        if self.state.connection not in ("disconnected", "error"):
            return
        if not self.running:
            try:
                self._start_worker()
            except OSError as exc:
                self.error.emit(f"无法建立临时捕获文件：{exc}")
                return
        self._update(DeviceState(connection="connecting", port=port, count=self.state.count,
                                 crc_errors=self.state.crc_errors, diagnostic_count=self.state.diagnostic_count))
        self._connect.emit(port)

    def shutdown(self) -> None:
        if self.running:
            self._close.emit()

    def cleanup(self) -> None:
        if self._owns_path and self._path is not None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("Could not remove capture journal %s", self._path, exc_info=True)
            self._path = None
