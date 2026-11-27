from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import isclose, isfinite
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal, Slot


def unsigned(text: str, bits: int) -> int:
    if not text.isascii() or not text.isdecimal() or len(text) > 20:
        raise ValueError("设备返回的计数格式无效")
    value = int(text)
    if value >= 1 << bits:
        raise ValueError("设备返回的计数超出范围")
    return value


def number(text: str) -> float:
    value = float(text)
    if not isfinite(value):
        raise ValueError("设备返回的测量值无效")
    return value


@dataclass(frozen=True, slots=True)
class AnalogSample:
    timestamp_us: int
    received_at: datetime
    voltage: float
    current: float
    dut_cc1: float
    dut_cc2: float
    usds_cc1: float
    usds_cc2: float
    adc_reference: float
    ground_reference: float
    current_reference: float
    elapsed_us: int
    charge_mah: int
    energy_mwh: int

    @classmethod
    def parse(cls, line: str) -> "AnalogSample":
        fields = line.split(",")
        if len(fields) != 13:
            raise ValueError("MEAS:ALL? 应返回 13 列")
        return cls(
            unsigned(fields[0], 64),
            datetime.now(timezone.utc),
            *(number(value) for value in fields[1:10]),
            unsigned(fields[10], 64),
            unsigned(fields[11], 32),
            unsigned(fields[12], 32),
        )


@dataclass(frozen=True, slots=True)
class BusRole:
    role: str
    attach: str
    source_port: str
    source_cc: str
    sink_port: str
    sink_cc: str

    @classmethod
    def parse(cls, line: str) -> "BusRole":
        fields = line.split(",")
        if len(fields) != 6:
            raise ValueError("BUS:CC:ROLE? 应返回 6 列")
        result = cls(*fields)
        if (
            result.role not in ("DISABLED", "OBSERVER", "SINK", "CABLE_TEST")
            or result.attach not in ("ATTACHED", "UNATTACHED", "SOURCE_FOUND")
            or {result.source_port, result.sink_port} - {"DUT", "USDS"}
            or {result.source_cc, result.sink_cc} - {"CC1", "CC2"}
        ):
            raise ValueError("设备返回的 CC 角色或连接状态无效")
        return result


@dataclass(frozen=True, slots=True)
class Protection:
    status: str
    ovp_us: int | None
    ocp_us: int | None

    @classmethod
    def parse(cls, line: str) -> "Protection":
        status, voltage, current = line.split(",")
        if status not in ("ENABLED", "DISABLED", "OVP", "OCP"):
            raise ValueError("设备返回的 VBUS 保护状态无效")
        return cls(status, *(None if value == "NONE" else unsigned(value, 64) for value in (voltage, current)))


@dataclass(frozen=True, slots=True)
class TelemetryState:
    available: bool = False
    sample: AnalogSample | None = None
    role: BusRole | None = None
    protection: Protection | None = None
    ovp: float | None = None
    ocp: float | None = None
    sink_error: int | None = None
    busy: bool = False
    message: str = ""


_THRESHOLDS = {"ovp": ("BUS:VBUS:OVPT", 60), "ocp": ("BUS:VBUS:OCPT", 6)}


class TelemetryService(QObject):
    """Schedule one low-priority query at a time on the capture worker session."""

    changed = Signal(object)
    sampled = Signal(object)

    def __init__(self, protocol, can_poll, parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._can_poll = can_poll
        self._state = TelemetryState()
        self._generation = 0
        self._sample_due = 0.0
        self._status_due = 0.0
        self._status_index = 0
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._poll)

    def activate(self, firmware: str) -> None:
        self.disconnect()
        if firmware == "1.0.0-beta.1":
            self._publish(available=True)
            self._timer.start()
        else:
            self._publish(message="此固件版本的测量接口尚未验证")

    def disconnect(self) -> None:
        self._timer.stop()
        self._generation += 1
        self._sample_due = self._status_due = 0.0
        self._status_index = 0
        self._state = TelemetryState()
        self.changed.emit(self._state)

    def _publish(self, **changes):
        self._state = replace(self._state, **changes)
        self.changed.emit(self._state)

    def _poll(self):
        if self._state.busy or not self._can_poll() or not self._protocol.is_idle:
            return
        now = monotonic()
        if now >= self._sample_due:
            self._sample_due = now + 0.5
            self._poll_field("sample", "MEAS:ALL?", AnalogSample.parse)
        elif now >= self._status_due:
            fields = (
                ("role", "BUS:CC:ROLE?", BusRole.parse),
                ("protection", "BUS:VBUS:STAT?", Protection.parse),
                ("ovp", _THRESHOLDS["ovp"][0] + "?", number),
                ("ocp", _THRESHOLDS["ocp"][0] + "?", number),
                ("sink_error", "SINK:STATUS:ERROR?", lambda line: unsigned(line, 32)),
            )
            field, command, parse = fields[self._status_index]
            self._status_index = (self._status_index + 1) % len(fields)
            self._status_due = now + (1.5 if self._status_index == 0 else 0.1)
            if field != "sink_error" or (self._state.role and self._state.role.role == "SINK"):
                self._poll_field(field, command, parse)
            elif self._state.sink_error is not None:
                self._publish(sink_error=None)

    def _poll_field(self, field, command, parse):
        generation = self._generation

        def failed(error):
            if generation == self._generation:
                self._publish(**{field: None}, message=f"{command} · {error}")

        def received(line):
            if generation != self._generation:
                return
            value = parse(line)
            changes = {field: value}
            if not self._state.busy and self._state.message.startswith(command + " ·"):
                changes["message"] = ""
            self._publish(**changes)
            if field == "sample":
                self.sampled.emit(value)

        self._protocol.query_text(command, received, errback=failed)

    @Slot(str, float)
    def set_threshold(self, field: str, value: float):
        if field not in _THRESHOLDS or not self._state.available or getattr(self._state, field) is None:
            return
        command, maximum = _THRESHOLDS[field]
        if not 0 <= value <= maximum:
            self._publish(message=f"阈值范围为 0–{maximum}")
            return

        def confirm(line):
            actual = number(line)
            matches = isclose(actual, value, rel_tol=0, abs_tol=0.0005)
            self._publish(**{field: actual}, busy=False,
                          message=f"{field.upper()} 已读回" if matches else f"设备读回 {actual:g}，与设置值不同")

        self._write_and_read(f"{command} {value:.3f}", command + "?", confirm)

    @Slot()
    def reset_accumulator(self):
        if self._state.sample is None:
            return

        def confirm(line):
            time, charge, energy = line.split(",")
            elapsed, charge, energy = unsigned(time, 64), unsigned(charge, 32), unsigned(energy, 32)
            verified = elapsed < 2_000_000 and charge == energy == 0
            self._sample_due = 0.0
            self._publish(sample=None, busy=False, message=(
                "已读回累计量清零" if verified else f"复位读回 {elapsed} µs，{charge} mAh，{energy} mWh"
            ))

        self._write_and_read("MEAS:ACC:RESET", "MEAS:ACC?", confirm)

    @Slot()
    def reset_protection(self):
        if self._state.protection is None or self._state.protection.status not in ("OVP", "OCP"):
            return

        def confirm(line):
            actual = Protection.parse(line)
            self._publish(protection=actual, busy=False, message=f"VBUS 保护状态已读回 · {actual.status}")

        self._write_and_read("BUS:VBUS:RESET", "BUS:VBUS:STAT?", confirm)

    def _write_and_read(self, command, query, confirm):
        if not self._state.available or self._state.busy or not self._can_poll():
            return
        generation = self._generation
        self._publish(busy=True, message="等待设备读回")

        def failed(error):
            if generation == self._generation:
                self._publish(busy=False, message=str(error))

        def read_back():
            self._protocol.query_text(query, confirm, errback=failed)

        self._protocol.command(command, callback=read_back, errback=failed)
