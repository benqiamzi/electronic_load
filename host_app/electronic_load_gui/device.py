from __future__ import annotations

from dataclasses import replace
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .domain import (
    DeviceStatus,
    MeasurementSnapshot,
    ResponseError,
    format_current_command,
    parse_current,
    parse_device_error,
    parse_identity,
    parse_measurements,
    parse_status,
    parse_switch_state,
)
from .protocol import ProtocolClient
from .serial_transport import PortDescriptor, SerialTransport


class ElectronicLoadDevice(QObject):
    connection_changed = Signal(bool, str)
    identity_changed = Signal(str)
    measurements_updated = Signal(object)
    status_updated = Signal(object)
    input_state_updated = Signal(bool)
    error_occurred = Signal(str)
    traffic = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.transport = SerialTransport(self)
        self.protocol = ProtocolClient(self.transport, self)
        self._ready = False
        self._measurement_timer = QTimer(self)
        self._measurement_timer.setInterval(100)
        self._measurement_timer.timeout.connect(self._poll_measurements)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._poll_status)
        self.transport.opened.connect(self._on_port_opened)
        self.transport.closed.connect(self._on_port_closed)
        self.transport.error_occurred.connect(self.error_occurred)
        self.transport.traffic.connect(self.traffic)
        self.protocol.error_occurred.connect(self.error_occurred)
        self.protocol.unsolicited_line.connect(
            lambda line: self.error_occurred.emit(f"收到未匹配响应: {line}")
        )

    @staticmethod
    def available_ports() -> list[PortDescriptor]:
        return SerialTransport.available_ports()

    @property
    def is_connected(self) -> bool:
        return self._ready and self.transport.is_open

    def connect_to(self, port_name: str) -> None:
        self.disconnect_device()
        self.connection_changed.emit(False, f"正在连接 {port_name}…")
        self.transport.open(port_name)

    def disconnect_device(self) -> None:
        self._stop_polling()
        self._ready = False
        self.protocol.clear()
        self.transport.close()

    @Slot(str)
    def _on_port_opened(self, port_name: str) -> None:
        self.connection_changed.emit(False, f"正在识别 {port_name}…")
        self.protocol.query(
            "*IDN?",
            self._accept_identity,
            errback=self._identity_failed,
            timeout_ms=1000,
            key="identity",
        )

    def _accept_identity(self, line: str) -> None:
        try:
            identity = parse_identity(line)
        except ResponseError as exc:
            self._identity_failed(str(exc))
            return
        if not identity.upper().startswith("ELECTRONICLOAD,"):
            self._identity_failed(f"所选串口不是电子负载: {identity}")
            return
        self._ready = True
        self.identity_changed.emit(identity)
        self.connection_changed.emit(True, f"已连接 {self.transport.port_name}")
        self._measurement_timer.start()
        self._status_timer.start()
        self._poll_measurements()
        self._poll_status()

    def _identity_failed(self, message: str) -> None:
        self.error_occurred.emit(f"设备识别失败: {message}")
        self.disconnect_device()

    @Slot()
    def _on_port_closed(self) -> None:
        was_ready = self._ready
        self._ready = False
        self._stop_polling()
        self.protocol.clear()
        self.connection_changed.emit(False, "连接已断开" if was_ready else "未连接")

    def _stop_polling(self) -> None:
        self._measurement_timer.stop()
        self._status_timer.stop()

    @Slot()
    def _poll_measurements(self) -> None:
        if self.is_connected:
            self.protocol.query(
                "MEAS:ALL?",
                self._accept_measurements,
                key="poll-measurements",
            )

    def _accept_measurements(self, line: str) -> None:
        snapshot = replace(parse_measurements(line), received_monotonic_s=time.monotonic())
        self.measurements_updated.emit(snapshot)

    @Slot()
    def _poll_status(self) -> None:
        if self.is_connected:
            self.protocol.query("STAT?", self._accept_status, key="poll-status")

    def _accept_status(self, line: str) -> None:
        status = parse_status(line)
        self.status_updated.emit(status)
        self.protocol.query("INP?", self._accept_input_state, key="poll-input")

    def _accept_input_state(self, line: str) -> None:
        self.input_state_updated.emit(parse_switch_state(line))

    def set_current(self, amps: float) -> None:
        if not self._require_connection():
            return
        try:
            command = format_current_command(amps)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return
        self._run_control(
            command,
            lambda: self.protocol.query(
                "SOUR:CURR?",
                lambda line: self._verify_current(line, amps),
            ),
        )

    def _verify_current(self, line: str, requested: float) -> None:
        actual = parse_current(line)
        if abs(actual - requested) > 0.00011:
            self.error_occurred.emit(
                f"电流设定读回不一致：请求 {requested:.4f} A，实际 {actual:.4f} A"
            )
        self._poll_status()

    def set_input(self, enabled: bool) -> None:
        if not self._require_connection():
            return
        command = "INP ON" if enabled else "INP OFF"
        self._run_control(
            command,
            lambda: self.protocol.query(
                "INP?",
                lambda line: self._verify_input(line, enabled),
            ),
        )

    def _verify_input(self, line: str, requested: bool) -> None:
        actual = parse_switch_state(line)
        self.input_state_updated.emit(actual)
        if actual != requested:
            self.error_occurred.emit("负载输入状态与请求不一致")
        self._poll_status()

    def clear_fault(self) -> None:
        if self._require_connection():
            self._run_control("SYST:FAULT:CLEAR", self._poll_status)

    def reset_device(self) -> None:
        if self._require_connection():
            self.protocol.command("*RST")
            QTimer.singleShot(100, self._poll_status)

    def _run_control(self, command: str, verified_action: Callable[[], None]) -> None:
        self.protocol.command(command)
        self.protocol.query(
            "SYST:ERR?",
            lambda line: self._after_control_error(line, verified_action),
        )

    def _after_control_error(self, line: str, verified_action: Callable[[], None]) -> None:
        result = parse_device_error(line)
        if result.is_error:
            self.error_occurred.emit(f"设备拒绝命令 [{result.code}]: {result.message}")
            self._poll_status()
            return
        verified_action()

    def _require_connection(self) -> bool:
        if self.is_connected:
            return True
        self.error_occurred.emit("请先连接电子负载")
        return False
