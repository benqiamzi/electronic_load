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


def format_current_command(amps: float) -> str:
    if not math.isfinite(amps) or not 0.0 <= amps <= 5.0:
        raise ValueError("恒流设定值必须在 0 A 到 5 A 之间")
    return f"SOUR:CURR {amps:.4f}"
