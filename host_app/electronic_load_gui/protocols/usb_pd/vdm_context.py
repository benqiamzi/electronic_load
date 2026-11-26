from collections import deque
from dataclasses import dataclass, field, replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import CaptureResult, PDMessageResult, ResetResult, VDMCommand, VDMCommandType, VDOInfo
from .sop import SopKind


@dataclass(frozen=True, slots=True)
class VDMAnalysis:
    result: CaptureResult
    status: ParseStatus | None = None
    mode: VDOInfo | None = None
    diagnostics: tuple[ParseDiagnostic, ...] = ()
    request: PDMessageResult | None = None


@dataclass(slots=True)
class _Discovery:
    identity: PDMessageResult | None = None
    request: PDMessageResult | None = None
    svids: tuple[int, ...] | None = None
    svid_sources: tuple[PDMessageResult, ...] = ()
    last_svid_reply: VDMAnalysis | None = None
    pending_svids: dict[int, None] = field(default_factory=dict)
    pending_sources: list[PDMessageResult] = field(default_factory=list)
    modes: dict[int, PDMessageResult] = field(default_factory=dict)

    def discard_pending(self) -> None:
        self.pending_svids.clear()
        self.pending_sources.clear()
        self.last_svid_reply = None


_MODE_EVENTS = (VDMCommand.ENTER_MODE, VDMCommand.EXIT_MODE, VDMCommand.ATTENTION)
_DISCOVERY_COMMANDS = (VDMCommand.DISCOVER_IDENTITY, VDMCommand.DISCOVER_SVIDS, VDMCommand.DISCOVER_MODES)


def _missing(result: PDMessageResult, message: str) -> VDMAnalysis:
    return VDMAnalysis(result, ParseStatus.CONTEXT_MISSING,
                       diagnostics=(ParseDiagnostic("vdm_context", "vdm_context_missing", message),))


class VDMContext:
    """Track verified discovery observations on one link, independently of power negotiation."""

    def __init__(self, *, event_limit: int = 128) -> None:
        if event_limit < 1:
            raise ValueError("VDM event history requires a positive capacity.")
        self._event_limit = event_limit
        self._discoveries: dict[tuple[SopKind, int | None], _Discovery] = {}
        self._events: dict[SopKind, deque[PDMessageResult]] = {}
        self._data_role_swap_pending = False

    def _discovery(self, sop: SopKind, responder_role: int) -> _Discovery | None:
        return self._discoveries.get((sop, responder_role if sop == SopKind.SOP else None))

    def identity(self, sop: SopKind = SopKind.SOP, *, responder_role: int = 0) -> PDMessageResult | None:
        observed = self._discovery(sop, responder_role)
        return observed.identity if observed else None

    def svids(self, sop: SopKind = SopKind.SOP, *, responder_role: int = 0) -> tuple[int, ...] | None:
        observed = self._discovery(sop, responder_role)
        return observed.svids if observed else None

    def svid_sources(self, sop: SopKind = SopKind.SOP, *, responder_role: int = 0) -> tuple[PDMessageResult, ...]:
        observed = self._discovery(sop, responder_role)
        return observed.svid_sources if observed else ()

    def modes(self, svid: int, sop: SopKind = SopKind.SOP, *, responder_role: int = 0) -> PDMessageResult | None:
        observed = self._discovery(sop, responder_role)
        return observed.modes.get(svid) if observed else None

    def mode_events(self, sop: SopKind = SopKind.SOP, *, svid: int | None = None) -> tuple[PDMessageResult, ...]:
        return tuple(event for event in self._events.get(sop, ()) if svid is None or event.vdm.svid == svid)

    def reset(self, sop: SopKind | None = None) -> None:
        """Forget all observations, or only those for the specified address."""
        if sop in (None, SopKind.SOP):
            self._data_role_swap_pending = False
        if sop is None:
            self._discoveries.clear()
            self._events.clear()
            return
        for key in tuple(self._discoveries):
            if key[0] == sop:
                del self._discoveries[key]
        self._events.pop(sop, None)

    def disconnect(self) -> None:
        self.reset()

    def _record_svids(self, result: PDMessageResult, observed: _Discovery) -> VDMAnalysis:
        page = result.vdm.discovered_svids
        last = observed.last_svid_reply
        same_page = last is not None and last.result.data_objects == result.data_objects
        if same_page and (observed.pending_sources or last.result.header.message_id == result.header.message_id):
            return replace(last, result=result)
        if any(svid in observed.pending_svids for svid in page):
            observed.discard_pending()
            issue = ParseDiagnostic("vdm_context", "vdm_duplicate_svid_page", "Distinct SVID pages overlap.")
            return VDMAnalysis(result, ParseStatus.INVALID, diagnostics=(issue,))
        if not page and not observed.pending_sources:
            return _missing(result, "The terminating SVID page has no observed preceding page.")

        observed.pending_svids.update(dict.fromkeys(page))
        observed.pending_sources.append(result)
        if result.vdm.svids_terminated:
            observed.svids = tuple(observed.pending_svids)
            observed.svid_sources = tuple(observed.pending_sources)
            observed.modes = {svid: frame for svid, frame in observed.modes.items() if svid in observed.pending_svids}
            observed.discard_pending()
        analysis = (VDMAnalysis(result, ParseStatus.VALID) if observed.identity is not None else
                    _missing(result, "No valid Identity ACK was observed from this responder."))
        observed.last_svid_reply = analysis
        return analysis

    def _record_event(self, result: PDMessageResult) -> VDMAnalysis:
        sop, vdm = result.sop.kind, result.vdm
        if sop not in self._events:
            self._events[sop] = deque(maxlen=self._event_limit)
        self._events[sop].append(result)
        # A port mode is selected for entry by the DFP from the UFP's list.
        modes = self.modes(vdm.svid, sop)
        if modes is None:
            return _missing(result, "No valid Discover Modes ACK was observed for this address and SVID.")
        position = vdm.object_position
        if vdm.command == VDMCommand.EXIT_MODE and position == 7:
            return VDMAnalysis(result, ParseStatus.VALID)
        if position > len(modes.vdm.vdos):
            issue = ParseDiagnostic("vdm_context", "vdm_mode_not_advertised", "Object Position is outside the observed Mode list.")
            return VDMAnalysis(result, ParseStatus.INVALID, diagnostics=(issue,))
        return VDMAnalysis(result, ParseStatus.VALID, mode=modes.vdm.vdos[position - 1])

    def _record_discovery(self, result: PDMessageResult) -> VDMAnalysis:
        sop, vdm = result.sop.kind, result.vdm
        if vdm.status not in (ParseStatus.VALID, ParseStatus.PARTIAL):
            return VDMAnalysis(result, vdm.status)
        initiator = vdm.command_type == VDMCommandType.INITIATOR
        role = result.header.data_role
        if initiator and sop == SopKind.SOP:
            role = 1 - role
        key = (sop, role)
        observed = self._discoveries.get(key)
        if initiator:
            if observed is None:
                observed = _Discovery()
                self._discoveries[key] = observed
            if vdm.command == VDMCommand.DISCOVER_IDENTITY:
                observed.discard_pending()
            observed.request = result
            return VDMAnalysis(result, vdm.status)

        request = observed.request if observed is not None else None
        if request is not None:
            if (request.vdm.command, request.vdm.svid) != (vdm.command, vdm.svid):
                issue = ParseDiagnostic(
                    "vdm_context", "vdm_discovery_response_mismatch",
                    f"Observed {vdm.command_name} response for SVID {vdm.svid:#06x} while waiting for "
                    f"{request.vdm.command_name} for SVID {request.vdm.svid:#06x}.",
                )
                return VDMAnalysis(result, ParseStatus.INVALID, diagnostics=(issue,), request=request)
            observed.request = None
        analysis = self._apply_discovery_response(result, key, observed)
        if request is None:
            return analysis
        request_version = request.vdm.structured_version
        response_version = vdm.structured_version
        diagnostics = analysis.diagnostics
        if request_version is not None and response_version is not None and response_version > request_version:
            # The observed response still identifies the command and SVID unambiguously.
            diagnostics += (ParseDiagnostic(
                "vdm_context", "vdm_discovery_response_version",
                f"Response uses SVDM {response_version[0]}.{response_version[1]} above "
                f"the request's {request_version[0]}.{request_version[1]}.",
            ),)
        return replace(analysis, request=request, diagnostics=diagnostics)

    def _apply_discovery_response(
        self, result: PDMessageResult, key: tuple[SopKind, int | None], observed: _Discovery | None,
    ) -> VDMAnalysis:
        vdm = result.vdm
        if vdm.command_type != VDMCommandType.ACK or vdm.status != ParseStatus.VALID:
            if vdm.command == VDMCommand.DISCOVER_SVIDS and vdm.command_type == VDMCommandType.NAK and observed is not None:
                observed.discard_pending()
            return VDMAnalysis(result, vdm.status)

        if (vdm.command == VDMCommand.DISCOVER_IDENTITY and observed is not None and observed.identity is not None
                and observed.identity.data_objects[1:] != result.data_objects[1:]):
            # A different Identity payload invalidates downstream discoveries for this responder.
            observed = None
        if observed is None:
            observed = _Discovery()
            self._discoveries[key] = observed
        if vdm.command == VDMCommand.DISCOVER_IDENTITY:
            observed.identity = result
        elif vdm.command == VDMCommand.DISCOVER_SVIDS:
            return self._record_svids(result, observed)
        else:
            observed.modes[vdm.svid] = result
            if observed.svids is None or vdm.svid not in observed.svids:
                return _missing(result, "The responder's observed SVID list does not cover this SVID.")
        return VDMAnalysis(result, ParseStatus.VALID)

    def consume(self, result: CaptureResult) -> VDMAnalysis:
        if isinstance(result, ResetResult):
            if result.sop.kind == SopKind.HARD_RESET:
                self.reset()
            elif result.sop.kind == SopKind.CABLE_RESET:
                self.reset(SopKind.SOP_PRIME)
                self.reset(SopKind.SOP_DOUBLE_PRIME)
            return VDMAnalysis(result)
        if not isinstance(result, PDMessageResult) or result.parse_status != ParseStatus.VALID or result.crc_valid is not True:
            return VDMAnalysis(result)

        sop = result.sop.kind
        name = result.message_type.name
        if sop == SopKind.SOP and name != "GoodCRC":
            if self._data_role_swap_pending and name == "Accept":
                # The previous role keys can no longer identify their original responders.
                self.reset(SopKind.SOP)
            self._data_role_swap_pending = name == "DR_Swap"
        if name not in ("GoodCRC", "Vendor_Defined"):
            for key, observed in self._discoveries.items():
                if key[0] == sop:
                    observed.request = None
                    if name == "Soft_Reset":
                        observed.discard_pending()
        if name == "Data_Reset_Complete":
            self.reset(SopKind.SOP_PRIME)
            self.reset(SopKind.SOP_DOUBLE_PRIME)
            self._events.pop(SopKind.SOP, None)

        vdm = result.vdm
        if vdm is not None and vdm.command in _DISCOVERY_COMMANDS:
            return self._record_discovery(result)
        if vdm is None or vdm.status != ParseStatus.VALID:
            return VDMAnalysis(result, vdm.status if vdm is not None else None)
        if vdm.command in _MODE_EVENTS:
            return self._record_event(result)
        return VDMAnalysis(result, ParseStatus.VALID)
