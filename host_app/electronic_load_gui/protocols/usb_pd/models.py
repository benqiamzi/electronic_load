from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum, StrEnum

from ...devices.drpd.capture_record import CaptureRecord, FirmwareEvent
from .diagnostics import ParseDiagnostic, ParseStatus
from .header import PDHeader
from .message_types import MessageTypeInfo
from .sop import SopInfo


class SupplyType(StrEnum):
    FIXED = "fixed"
    BATTERY = "battery"
    VARIABLE = "variable"
    PPS = "pps"
    SPR_AVS = "spr_avs"
    EPR_AVS = "epr_avs"
    UNKNOWN_APDO = "unknown_apdo"


class PDODirection(StrEnum):
    SOURCE = "source"
    SINK = "sink"


@dataclass(frozen=True, slots=True)
class PDOInfo:
    raw: int
    index: int | None
    direction: PDODirection
    supply_type: SupplyType
    status: ParseStatus = ParseStatus.VALID
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    voltage_min_mv: int | None = None
    voltage_max_mv: int | None = None
    current_max_ma: int | None = None
    operating_current_ma: int | None = None
    power_max_mw: int | None = None
    operating_power_mw: int | None = None
    capabilities: frozenset[str] = frozenset()
    reserved_bits: int = 0
    peak_current_code: int | None = None
    fast_role_swap_current_code: int | None = None
    apdo_subtype: int | None = None
    pps_power_limited: bool | None = None
    current_max_15v_ma: int | None = None
    current_max_20v_ma: int | None = None
    pdp_mw: int | None = None


@dataclass(frozen=True, slots=True)
class RDOInfo:
    raw: int
    object_position: int
    status: ParseStatus
    request_type: SupplyType | None = None
    selected_pdo: PDOInfo | None = None
    give_back: bool | None = None
    capability_mismatch: bool = False
    usb_communications_capable: bool = False
    no_usb_suspend: bool = False
    unchunked_extended_messages_supported: bool | None = None
    epr_capable: bool | None = None
    reserved_bits: int = 0
    operating_current_ma: int | None = None
    maximum_operating_current_ma: int | None = None
    minimum_operating_current_ma: int | None = None
    operating_power_mw: int | None = None
    maximum_operating_power_mw: int | None = None
    minimum_operating_power_mw: int | None = None
    operating_voltage_mv: int | None = None
    diagnostics: tuple[ParseDiagnostic, ...] = ()


class VDMType(StrEnum):
    STRUCTURED = "structured"
    UNSTRUCTURED = "unstructured"


class VDMCommandType(IntEnum):
    INITIATOR = 0
    ACK = 1
    NAK = 2
    BUSY = 3


class VDMCommand(IntEnum):
    DISCOVER_IDENTITY = 1
    DISCOVER_SVIDS = 2
    DISCOVER_MODES = 3
    ENTER_MODE = 4
    EXIT_MODE = 5
    ATTENTION = 6


@dataclass(frozen=True, slots=True)
class VDOInfo:
    index: int
    raw: int
    category: str = "raw"
    mode_position: int | None = None
    decoded_fields: Mapping[str, object] | None = None
    vendor_fields: Mapping[str, object] | None = None
    diagnostics: tuple[ParseDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class VDMInfo:
    raw_header: int | None
    svid: int | None
    vdm_type: VDMType | None
    status: ParseStatus
    version_major: int | None = None
    version_minor: int | None = None
    object_position: int | None = None
    command_type: VDMCommandType | None = None
    command: int | None = None
    command_name: str | None = None
    reserved_bits: int = 0
    vendor_header_bits: int | None = None
    vdos: tuple[VDOInfo, ...] = ()
    discovered_svids: tuple[int, ...] | None = None
    svids_terminated: bool | None = None
    diagnostics: tuple[ParseDiagnostic, ...] = ()

    @property
    def structured_version(self) -> tuple[int, int] | None:
        if self.command is not None and self.command < 16:
            if self.version_major == 0 and self.version_minor == 0:
                return (1, 0)
            if self.version_major == 1 and self.version_minor in (0, 1):
                return (2, self.version_minor)
        return None


@dataclass(frozen=True, slots=True)
class PDMessageResult:
    record: CaptureRecord
    sop: SopInfo
    header: PDHeader
    message_type: MessageTypeInfo
    body: bytes | None
    data_objects: tuple[int, ...]
    header_status: ParseStatus
    body_status: ParseStatus
    parse_status: ParseStatus
    diagnostics: tuple[ParseDiagnostic, ...]
    crc_received: int | None = None
    crc_calculated: int | None = None
    crc_valid: bool | None = None
    pdos: tuple[PDOInfo, ...] = ()
    rdo: RDOInfo | None = None
    vdm: VDMInfo | None = None

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


@dataclass(frozen=True, slots=True)
class PDSessionAnalysis:
    result: CaptureResult
    rdo: RDOInfo | None = None
