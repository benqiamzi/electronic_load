from __future__ import annotations

from dataclasses import replace
import time
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .domain import (
    DeviceStatus,
    MeasurementSnapshot,
    ProtectionThresholds,
    ResponseError,
    format_channel_mode_command,
    format_current_command,
    format_dac_voltage_command,
    format_fan_duty_command,
    format_protection_command,
    parse_channel_mode,
    parse_current,
    parse_device_error,
    parse_dac_voltages,
    parse_identity,
    parse_fan_duty,
    parse_measurements,
    parse_protection_thresholds,
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
    dac_voltages_updated = Signal(object)
    dac_capability_changed = Signal(bool)
    live_dac_capability_changed = Signal(bool)
    dac_mode_updated = Signal(str)
    channel_mode_updated = Signal(str)
    fan_duty_updated = Signal(float)
    advanced_control_capability_changed = Signal(bool)
    protection_thresholds_updated = Signal(object)
    protection_error = Signal(str)
    error_occurred = Signal(str)
    traffic = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.transport = SerialTransport(self)
        self.protocol = ProtocolClient(self.transport, self)
        self._ready = False
        self._dac_voltage_supported = False
        self._live_dac_supported = False
        self._advanced_control_supported = False
        self._protection_supported = False
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

    @property
    def protection_supported(self) -> bool:
        return self.is_connected and self._protection_supported

    def connect_to(self, port_name: str) -> None:
        self.disconnect_device()
        self.connection_changed.emit(False, f"正在连接 {port_name}…")
        self.transport.open(port_name)

    def disconnect_device(self) -> None:
        self._stop_polling()
        self._ready = False
        self._dac_voltage_supported = False
        self._live_dac_supported = False
        self._advanced_control_supported = False
        self._protection_supported = False
        self.dac_capability_changed.emit(False)
        self.live_dac_capability_changed.emit(False)
        self.advanced_control_capability_changed.emit(False)
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
        self._dac_voltage_supported = self._supports_dac_voltage(identity)
        self._live_dac_supported = self._supports_live_dac(identity)
        self._advanced_control_supported = self._supports_advanced_controls(identity)
        self._protection_supported = self._supports_protection(identity)
        self.identity_changed.emit(identity)
        self.dac_capability_changed.emit(self._dac_voltage_supported)
        self.live_dac_capability_changed.emit(self._live_dac_supported)
        self.advanced_control_capability_changed.emit(self._advanced_control_supported)
        self.connection_changed.emit(True, f"已连接 {self.transport.port_name}")
        self._measurement_timer.start()
        self._status_timer.start()
        self._poll_measurements()
        self._poll_status()
        self._poll_dac_voltages()
        self._poll_advanced_controls()

    @staticmethod
    def _supports_dac_voltage(identity: str) -> bool:
        try:
            version = tuple(int(part) for part in identity.split(",")[3].split("."))
        except (IndexError, ValueError):
            return False
        return version >= (0, 2, 0)

    @staticmethod
    def _supports_advanced_controls(identity: str) -> bool:
        try:
            version = tuple(int(part) for part in identity.split(",")[3].split("."))
        except (IndexError, ValueError):
            return False
        return version >= (0, 3, 0)

    @staticmethod
    def _supports_live_dac(identity: str) -> bool:
        try:
            version = tuple(int(part) for part in identity.split(",")[3].split("."))
        except (IndexError, ValueError):
            return False
        return version >= (0, 3, 6)

    @staticmethod
    def _supports_protection(identity: str) -> bool:
        try:
            version = tuple(int(part) for part in identity.split(",")[3].split("."))
        except (IndexError, ValueError):
            return False
        return version >= (0, 3, 7)

    def _identity_failed(self, message: str) -> None:
        self.error_occurred.emit(f"设备识别失败: {message}")
        self.disconnect_device()

    @Slot()
    def _on_port_closed(self) -> None:
        was_ready = self._ready
        self._ready = False
        self._dac_voltage_supported = False
        self._live_dac_supported = False
        self._advanced_control_supported = False
        self._protection_supported = False
        self.dac_capability_changed.emit(False)
        self.live_dac_capability_changed.emit(False)
        self.advanced_control_capability_changed.emit(False)
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
        self._poll_dac_voltages()
        self._poll_advanced_controls()

    def _accept_input_state(self, line: str) -> None:
        self.input_state_updated.emit(parse_switch_state(line))

    def _poll_dac_voltages(self) -> None:
        if self.is_connected and self._dac_voltage_supported:
            self.protocol.query(
                "DIAG:DAC:VOLT?",
                self._accept_dac_voltages,
                key="poll-dac-voltages",
            )
            if self._live_dac_supported:
                self.protocol.query(
                    "DIAG:DAC:MODE?",
                    self._accept_dac_mode,
                    key="poll-dac-mode",
                )

    def _accept_dac_voltages(self, line: str) -> None:
        self.dac_voltages_updated.emit(parse_dac_voltages(line))

    def _accept_dac_mode(self, line: str) -> None:
        mode = line.strip().upper()
        if mode not in ("AUTO", "MANUAL"):
            raise ResponseError(f"无效的 DAC 模式: {line!r}")
        self.dac_mode_updated.emit(mode)

    def _poll_advanced_controls(self) -> None:
        if not self.is_connected or not self._advanced_control_supported:
            return
        self.protocol.query(
            "SOUR:CHAN?",
            lambda line: self.channel_mode_updated.emit(parse_channel_mode(line)),
            key="poll-channel-mode",
        )
        self.protocol.query(
            "FAN:DUTY?",
            lambda line: self.fan_duty_updated.emit(parse_fan_duty(line)),
            key="poll-fan-duty",
        )

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

    def set_channel_mode(self, mode: str) -> None:
        if not self._require_advanced_control_support():
            return
        try:
            command = format_channel_mode_command(mode)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return
        # A mode change is deliberately non-seamless: first disable and verify
        # the load, then change the DAC routing. The load remains disabled and
        # requires a separate explicit ON command from the operator.
        self._run_control(
            "INP OFF",
            lambda: self.protocol.query(
                "INP?",
                lambda line: self._after_input_disabled_for_mode(line, command, mode),
            ),
        )

    def _after_input_disabled_for_mode(self, line: str, command: str, mode: str) -> None:
        enabled = parse_switch_state(line)
        self.input_state_updated.emit(enabled)
        if enabled:
            self.error_occurred.emit("通道切换前无法确认负载已关闭")
            return
        self._run_control(
            command,
            lambda: self.protocol.query(
                "SOUR:CHAN?",
                lambda response: self._verify_channel_mode(response, mode),
            ),
        )

    def _verify_channel_mode(self, line: str, requested: str) -> None:
        actual = parse_channel_mode(line)
        self.channel_mode_updated.emit(actual)
        if actual != requested.strip().upper():
            self.error_occurred.emit(f"输出通道模式读回不一致：请求 {requested}，实际 {actual}")
        self._poll_status()

    def set_fan_duty(self, duty_percent: float) -> None:
        if not self._require_advanced_control_support():
            return
        try:
            command = format_fan_duty_command(duty_percent)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return
        self._run_control(
            command,
            lambda: self.protocol.query(
                "FAN:DUTY?",
                lambda line: self._verify_fan_duty(line, duty_percent),
            ),
        )

    def _verify_fan_duty(self, line: str, requested: float) -> None:
        actual = parse_fan_duty(line)
        self.fan_duty_updated.emit(actual)
        if abs(actual - requested) > 0.11:
            self.error_occurred.emit(
                f"风扇占空比读回不一致：请求 {requested:.1f}%，实际 {actual:.1f}%"
            )

    def clear_fault(self) -> None:
        if self._require_connection():
            self._run_control("SYST:FAULT:CLEAR", self._poll_status)

    def read_protection_thresholds(self) -> None:
        self._query_protection("SYST:PROT?")

    def set_protection_thresholds(self, thresholds: ProtectionThresholds) -> None:
        try:
            command = format_protection_command(thresholds)
        except ValueError as exc:
            self.protection_error.emit(str(exc))
            return
        self._query_protection(command)

    def restore_protection_thresholds(self) -> None:
        self._query_protection("SYST:PROT:DEF")

    def _query_protection(self, command: str) -> None:
        if not self.protection_supported:
            self.protection_error.emit("保护阈值设置需要连接固件 0.3.7 或更新版本")
            return
        self.protocol.query(
            command, self._accept_protection, errback=self.protection_error.emit
        )

    def _accept_protection(self, line: str) -> None:
        try:
            thresholds = parse_protection_thresholds(line)
        except ResponseError as exc:
            self.protection_error.emit(str(exc))
            return
        self.protection_thresholds_updated.emit(thresholds)

    def set_dac_voltage(self, channel: int, volts: float) -> None:
        if not self._require_dac_voltage_support():
            return
        try:
            command = format_dac_voltage_command(channel, volts)
        except ValueError as exc:
            self.error_occurred.emit(str(exc))
            return
        self._run_control(command, self._poll_dac_voltages)

    def zero_dac(self) -> None:
        if self._require_dac_voltage_support():
            self._run_control("DIAG:DAC:ZERO", self._poll_dac_voltages)

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

    def _require_dac_voltage_support(self) -> bool:
        if not self._require_connection():
            return False
        if self._dac_voltage_supported:
            return True
        self.error_occurred.emit("当前固件不支持单通道 DAC 电压控制，请升级到 0.2.0 或更高版本")
        return False

    def _require_advanced_control_support(self) -> bool:
        if not self._require_connection():
            return False
        if self._advanced_control_supported:
            return True
        self.error_occurred.emit("当前固件不支持通道模式和风扇控制，请升级到 0.3.0 或更高版本")
        return False
