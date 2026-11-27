from dataclasses import dataclass
import logging

from ..devices.drpd.capture_record import CaptureRecord, FirmwareEvent
from ..protocols.usb_pd import ExtendedMessageReassembler, PDSessionContext, VDMContext, parse_capture
from ..protocols.usb_pd.diagnostics import ParseDiagnostic, ParseStatus
from ..protocols.usb_pd.models import CaptureResult, ExtendedAnalysis, PDMessageResult, PDSessionAnalysis
from ..protocols.usb_pd.vdm_context import VDMAnalysis


@dataclass(frozen=True, slots=True)
class AnalysisEvent:
    index: int
    record: CaptureRecord | FirmwareEvent
    provenance: str
    result: CaptureResult | None
    power: PDSessionAnalysis | None
    discovery: VDMAnalysis | None
    extended: ExtendedAnalysis | None
    diagnostics: tuple[ParseDiagnostic, ...]
    epr_observed: bool
    epr_pdo_count: int
    session_id: str = ""
    session_index: int = 0

    @property
    def timestamp_us(self) -> int:
        if isinstance(self.record, FirmwareEvent):
            return self.record.timestamp_us
        return self.record.start_timestamp_us

    @property
    def end_us(self) -> int:
        return getattr(self.record, "end_timestamp_us", self.timestamp_us)

    @property
    def sender(self) -> str:
        header = self.message.header if self.message is not None else None
        if header is not None:
            if header.power_role is not None:
                return "Source" if header.power_role else "Sink"
            if header.cable_plug is not None:
                return "Cable" if header.cable_plug else "Port"
        return ""

    @property
    def receiver(self) -> str:
        return {"Source": "Sink", "Sink": "Source", "Cable": "Port", "Port": "Cable"}.get(self.sender, "")

    @property
    def event_type(self) -> str:
        if isinstance(self.record, FirmwareEvent):
            return {1: "OVP", 2: "OCP", 3: "Detach", 4: "Source Found", 5: "Attach",
                    9: "Sink Error", 10: "Sync Trigger", 11: "Sink Warning"}.get(self.record.event_type, "Firmware Event")
        if self.sop in ("Hard Reset", "Cable Reset"):
            return self.sop
        if self.crc == "invalid" or self.record.decode_result:
            return "Protocol Error"
        return ""

    @property
    def message(self) -> PDMessageResult | None:
        return self.result if isinstance(self.result, PDMessageResult) else None

    @property
    def sop(self) -> str:
        sop = getattr(self.result, "sop", None)
        return sop.kind.value if sop is not None else ""

    @property
    def message_name(self) -> str:
        message = self.message
        if message is not None:
            return message.message_type.name or f"{message.message_type.category.value} 0x{message.message_type.code:02X}"
        if isinstance(self.record, FirmwareEvent):
            return "Firmware Event"
        if self.sop in ("Hard Reset", "Cable Reset"):
            return self.sop
        return "未解码"

    @property
    def crc(self) -> str:
        value = self.message.crc_valid if self.message is not None else None
        return "valid" if value is True else "invalid" if value is False else "unavailable"


class AnalysisService:
    """Own the ordered protocol contexts for one live or replay stream."""

    def __init__(self) -> None:
        self.power = PDSessionContext()
        self.discovery = VDMContext()
        self.extended = ExtendedMessageReassembler()
        self.epr_observed = False

    def reset(self) -> None:
        self.power.disconnect()
        self.discovery.disconnect()
        self.extended.disconnect()
        self.epr_observed = False

    def consume(self, index: int, record: CaptureRecord | FirmwareEvent, provenance: str,
                session_id: str = "", session_index: int = 0) -> AnalysisEvent:
        result = power = discovery = extended = None
        diagnostics = []
        try:
            result = parse_capture(record)
            power = self.power.consume(result)
            discovery = self.discovery.consume(result)
            extended = self.extended.consume(result)
            if isinstance(result, PDMessageResult) and result.message_type.name == "EPR_Source_Capabilities":
                header = result.extended_message.header if result.extended_message is not None else None
                if header is not None and not header.request_chunk:
                    self.epr_observed = True
            if extended is not None:
                self.power.consume_extended(extended)
                diagnostics.extend(extended.diagnostics)
                if extended.message is not None:
                    diagnostics.extend(extended.message.diagnostics)
                if extended.epr is not None:
                    diagnostics.extend(extended.epr.diagnostics)
                for partial in extended.interrupted:
                    diagnostics.extend(partial.diagnostics)
            diagnostics.extend(getattr(result, "diagnostics", ()))
            diagnostics.extend(discovery.diagnostics)
            if power.rdo is not None:
                diagnostics.extend(power.rdo.diagnostics)
            if isinstance(result, PDMessageResult):
                for pdo in result.pdos:
                    diagnostics.extend(pdo.diagnostics)
                if result.vdm is not None:
                    diagnostics.extend(result.vdm.diagnostics)
        except Exception as exc:
            logging.getLogger(__name__).exception("Protocol analysis failed for capture %d", index)
            self.reset()
            diagnostics.append(ParseDiagnostic("analysis", "analysis_error", f"{type(exc).__name__}: {exc}"))
        epr = self.power.epr_source_capabilities()
        return AnalysisEvent(index, record, provenance, result, power, discovery, extended,
                             tuple(dict.fromkeys(diagnostics)), self.epr_observed, len(epr.epr_pdos) if epr else 0,
                             session_id, session_index)


def event_state(event: AnalysisEvent) -> str:
    message = event.message
    if message is None:
        return getattr(event.result, "parse_status", ParseStatus.INVALID if event.result is None else ParseStatus.VALID)
    states = [message.parse_status]
    if event.power is not None and event.power.rdo is not None:
        states.append(event.power.rdo.status)
    if message.vdm is not None and event.discovery is not None:
        states.extend((message.vdm.status, event.discovery.status))
    if event.extended is not None:
        states.append(event.extended.status)
        if event.extended.epr is not None:
            states.append(event.extended.epr.status)
    for state in ("invalid", "partial", "context_missing", "pending", "unknown", "unsupported"):
        if state in states:
            return state
    return "complete" if "complete" in states else "valid"
