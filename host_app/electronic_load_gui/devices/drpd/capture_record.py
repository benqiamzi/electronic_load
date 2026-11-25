from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from math import isfinite
from struct import Struct, unpack_from


_RECORD_HEADER = Struct("<QQI4sI")
_UINT32 = Struct("<I")
_MIN_RECORD_SIZE = _RECORD_HEADER.size + _UINT32.size
_HARD_RESET_SOP = b"\x07\x07\x07\x19"


class DecodeResult(IntEnum):
    SUCCESS = 0
    INVALID_K_CODE = 1
    CRC_ERROR = 2
    TIMEOUT = 3
    RUNT_PULSE = 4
    INCOMPLETE = 5
    FIRMWARE_EVENT = 0xFFFFFFFF


class CaptureRecordError(ValueError):
    """Capture payload does not match the firmware's record layout."""


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    start_timestamp_us: int
    end_timestamp_us: int
    decode_result: int
    sop_bytes: bytes
    pulse_widths: tuple[int, ...]
    decoded_data: bytes
    raw_payload: bytes
    cycle_time_ns: float

    @property
    def pulse_count(self) -> int:
        return len(self.pulse_widths)

    @property
    def data_length(self) -> int:
        return len(self.decoded_data)

    @property
    def pulse_widths_ns(self) -> tuple[float, ...]:
        return tuple(cycles * self.cycle_time_ns for cycles in self.pulse_widths)

    @property
    def is_hard_reset(self) -> bool:
        return (
            self.decode_result == DecodeResult.SUCCESS
            and self.sop_bytes == _HARD_RESET_SOP
            and not self.decoded_data
        )


@dataclass(frozen=True, slots=True)
class FirmwareEvent:
    timestamp_us: int
    event_type: int
    event_text: str
    event_text_bytes: bytes
    raw_payload: bytes
    text_encoding_valid: bool


class CaptureRecordParser:
    """Decode the little-endian record and retain its original bytes."""

    @staticmethod
    def parse(payload: bytes, cycle_time_ns: float) -> CaptureRecord | FirmwareEvent:
        if not isfinite(cycle_time_ns) or cycle_time_ns <= 0:
            raise CaptureRecordError("捕获周期必须是有限的正数")
        if len(payload) < _MIN_RECORD_SIZE:
            raise CaptureRecordError("捕获记录的固定字段不完整")

        start, end, result, sop, pulse_count = _RECORD_HEADER.unpack_from(payload)
        if pulse_count > (len(payload) - _MIN_RECORD_SIZE) // 2:
            raise CaptureRecordError("脉宽条目数超出捕获记录边界")
        length_offset = _RECORD_HEADER.size + 2 * pulse_count
        (data_length,) = _UINT32.unpack_from(payload, length_offset)
        data_start = length_offset + _UINT32.size
        if len(payload) - data_start != data_length:
            raise CaptureRecordError("解码数据长度与捕获记录长度不符")
        data = payload[data_start:]

        if result == DecodeResult.FIRMWARE_EVENT:
            if start != end or sop != bytes(4) or pulse_count or len(data) < _UINT32.size:
                raise CaptureRecordError("固件事件字段无效")
            (event_type,) = _UINT32.unpack_from(data)
            text_bytes = data[_UINT32.size:]
            try:
                text = text_bytes.decode("utf-8")
                valid = True
            except UnicodeDecodeError:
                text = text_bytes.decode("utf-8", errors="replace")
                valid = False
            return FirmwareEvent(start, event_type, text, text_bytes, payload, valid)

        widths = unpack_from(f"<{pulse_count}H", payload, _RECORD_HEADER.size)
        return CaptureRecord(start, end, result, sop, widths, data, payload, cycle_time_ns)
