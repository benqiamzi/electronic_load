from dataclasses import dataclass

from ...devices.drpd.capture_record import CaptureRecord, FirmwareEvent
from .diagnostics import ParseDiagnostic, ParseStatus
from .header import PDHeader
from .sop import SopInfo


@dataclass(frozen=True, slots=True)
class PDMessageResult:
    record: CaptureRecord
    sop: SopInfo
    header: PDHeader
    body: bytes | None
    header_status: ParseStatus
    body_status: ParseStatus
    parse_status: ParseStatus
    diagnostics: tuple[ParseDiagnostic, ...]

    @property
    def raw_decoded_data(self) -> bytes:
        return self.record.decoded_data

    @property
    def firmware_decode_result(self) -> int:
        return self.record.decode_result


@dataclass(frozen=True, slots=True)
class ResetResult:
    record: CaptureRecord
    sop: SopInfo


@dataclass(frozen=True, slots=True)
class FirmwareEventResult:
    record: FirmwareEvent


@dataclass(frozen=True, slots=True)
class ParseFailureResult:
    record: CaptureRecord
    sop: SopInfo
    parse_status: ParseStatus
    diagnostics: tuple[ParseDiagnostic, ...]


CaptureResult = PDMessageResult | ResetResult | FirmwareEventResult | ParseFailureResult
