from __future__ import annotations

from dataclasses import dataclass
import math
import re


class ResponseError(ValueError):
    """Raised when a device response cannot be parsed."""


@dataclass(frozen=True, slots=True)
class MeasurementSnapshot:
    voltage_v: float
    current_a: float
    power_w: float
    left_temperature_c: float
    right_temperature_c: float
    received_monotonic_s: float = 0.0


@dataclass(frozen=True, slots=True)
class DeviceStatus:
    state: str
    fault: str
    requested_current_a: float


@dataclass(frozen=True, slots=True)
class DacVoltages:
    channel_1_v: float
    channel_2_v: float


@dataclass(frozen=True, slots=True)
class ProtectionThresholds:
    voltage_v: float
    current_a: float
    power_w: float
    temperature_c: float
    temperature_enabled: bool = False

    def values(self) -> tuple[float, float, float, float]:
        return self.voltage_v, self.current_a, self.power_w, self.temperature_c


PROTECTION_RANGES = ((0.01, 30.0), (0.01, 2.75), (0.01, 50.0), (30.0, 80.0))
CHANNEL_MODES = ("A", "B", "BOTH")


@dataclass(frozen=True, slots=True)
class DeviceError:
    code: int
    message: str

    @property
    def is_error(self) -> bool:
        return self.code != 0


def _finite_float(value: str, field: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ResponseError(f"{field} 不是有效数字: {value!r}") from exc
    if not math.isfinite(parsed):
        raise ResponseError(f"{field} 不是有限数值")
    return parsed


def parse_measurements(line: str) -> MeasurementSnapshot:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) != 5:
        raise ResponseError(f"测量响应应包含 5 项，实际为 {len(fields)} 项: {line!r}")
    return MeasurementSnapshot(
        voltage_v=_finite_float(fields[0], "电压"),
        current_a=_finite_float(fields[1], "电流"),
        power_w=_finite_float(fields[2], "功率"),
        left_temperature_c=_finite_float(fields[3], "左侧温度"),
        right_temperature_c=_finite_float(fields[4], "右侧温度"),
    )


def parse_status(line: str) -> DeviceStatus:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) != 3 or not fields[0] or not fields[1]:
        raise ResponseError(f"状态响应格式错误: {line!r}")
    return DeviceStatus(
        state=fields[0],
        fault=fields[1],
        requested_current_a=_finite_float(fields[2], "设定电流"),
    )


_ERROR_PATTERN = re.compile(r'^\s*(-?\d+)\s*,\s*"(.*)"\s*$')


def parse_device_error(line: str) -> DeviceError:
    match = _ERROR_PATTERN.match(line)
    if match is None:
        raise ResponseError(f"错误响应格式错误: {line!r}")
    return DeviceError(code=int(match.group(1)), message=match.group(2))


def parse_identity(line: str) -> str:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) < 4 or any(not field for field in fields[:2]):
        raise ResponseError(f"设备标识响应格式错误: {line!r}")
    return ",".join(fields)


def parse_switch_state(line: str) -> bool:
    value = line.strip()
    if value == "1":
        return True
    if value == "0":
        return False
    raise ResponseError(f"输入状态应为 0 或 1，实际为: {line!r}")


def parse_current(line: str) -> float:
    return _finite_float(line.strip(), "设定电流")


def parse_channel_mode(line: str) -> str:
    mode = line.strip().upper()
    if mode not in CHANNEL_MODES:
        raise ResponseError(f"输出通道模式应为 A、B 或 BOTH，实际为: {line!r}")
    return mode


def parse_fan_duty(line: str) -> float:
    duty = _finite_float(line.strip(), "风扇占空比")
    if not 0.0 <= duty <= 100.0:
        raise ResponseError(f"风扇占空比超出 0～100% 范围: {line!r}")
    return duty


def parse_dac_voltages(line: str) -> DacVoltages:
    fields = [field.strip() for field in line.split(",")]
    if len(fields) != 2:
        raise ResponseError(f"DAC 响应应包含 2 项，实际为 {len(fields)} 项: {line!r}")
    channel_1 = _finite_float(fields[0], "DAC1 电压")
    channel_2 = _finite_float(fields[1], "DAC2 电压")
    if not 0.0 <= channel_1 <= 2.5001 or not 0.0 <= channel_2 <= 2.5001:
        raise ResponseError(f"DAC 电压超出 0～2.5 V 范围: {line!r}")
    return DacVoltages(channel_1_v=channel_1, channel_2_v=channel_2)


def parse_protection_thresholds(line: str) -> ProtectionThresholds:
    if line.startswith("ERROR,"):
        raise ResponseError(line.partition(",")[2])
    fields = line.split(",")
    if len(fields) != 5:
        raise ResponseError(f"保护阈值响应格式错误: {line!r}")
    values = tuple(_finite_float(field, "保护阈值") for field in fields[:4])
    if not all(low <= value <= high for value, (low, high) in zip(values, PROTECTION_RANGES)):
        raise ResponseError(f"设备返回的保护阈值超出允许范围: {line!r}")
    return ProtectionThresholds(*values, temperature_enabled=parse_switch_state(fields[4]))


def format_protection_command(thresholds: ProtectionThresholds) -> str:
    values = thresholds.values()
    if not all(low <= value <= high for value, (low, high) in zip(values, PROTECTION_RANGES)):
        raise ValueError("保护阈值超出允许范围")
    return "SYST:PROT " + ",".join(f"{value:.4f}" for value in values)


def format_current_command(amps: float) -> str:
    if not math.isfinite(amps) or not 0.0 <= amps <= 2.5:
        raise ValueError("总恒流设定值必须在 0 A 到 2.5 A 之间")
    return f"SOUR:CURR {amps:.4f}"


def format_channel_mode_command(mode: str) -> str:
    normalized = mode.strip().upper()
    if normalized not in CHANNEL_MODES:
        raise ValueError("输出通道模式必须为 A、B 或 BOTH")
    return f"SOUR:CHAN {normalized}"


def format_fan_duty_command(duty_percent: float) -> str:
    if not math.isfinite(duty_percent) or not 0.0 <= duty_percent <= 100.0:
        raise ValueError("风扇占空比必须在 0% 到 100% 之间")
    return f"FAN:DUTY {duty_percent:.1f}"


def format_dac_voltage_command(channel: int, volts: float) -> str:
    if channel not in (1, 2):
        raise ValueError("DAC 通道必须为 1 或 2")
    if not math.isfinite(volts) or not 0.0 <= volts <= 2.5:
        raise ValueError("DAC 电压必须在 0 V 到 2.5 V 之间")
    return f"DIAG:DAC:VOLT {channel},{volts:.5f}"
