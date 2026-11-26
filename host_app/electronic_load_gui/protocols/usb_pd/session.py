from dataclasses import replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import (
    CaptureResult, EPRSourceCapabilities, ExtendedAnalysis, PDMessageResult, PDOInfo, PDSessionAnalysis, ResetResult, RDOInfo,
)
from .pdo import MAX_EPR_PDO_POSITION, SPR_PDO_COUNT
from .rdo import decode_rdo
from .sop import SopKind


class PDSessionContext:
    """Associate Requests with capabilities observed in order on one captured link."""

    def __init__(self) -> None:
        self._source_pdos: dict[SopKind, tuple[PDOInfo, ...]] = {}
        self._epr_source: EPRSourceCapabilities | None = None

    def reset(self) -> None:
        """Discard all observations when capture continuity is lost."""
        self._source_pdos.clear()
        self._epr_source = None

    def disconnect(self) -> None:
        self.reset()

    def source_pdos(self, sop: SopKind = SopKind.SOP) -> tuple[PDOInfo, ...]:
        return self._source_pdos.get(sop, ())

    def epr_source_capabilities(self) -> EPRSourceCapabilities | None:
        return self._epr_source

    def consume_extended(self, analysis: ExtendedAnalysis) -> None:
        """Cache only fully validated EPR Source Capabilities from the separate reassembler."""
        if analysis.epr is not None and analysis.epr.status == ParseStatus.VALID:
            self._epr_source = analysis.epr

    def _resolve_epr_request(self, result: PDMessageResult) -> RDOInfo:
        rdo = result.rdo
        if result.header.power_role != 0:
            issue = ParseDiagnostic("rdo", "epr_request_sender", "EPR_Request must be sent by the Sink.")
            return replace(rdo, status=ParseStatus.INVALID, diagnostics=rdo.diagnostics + (issue,))
        if rdo.status == ParseStatus.INVALID or self._epr_source is None:
            return rdo
        slots = self._epr_source.slots
        position = rdo.object_position
        if not 1 <= position <= min(MAX_EPR_PDO_POSITION, len(slots)) or slots[position - 1] is None:
            issue = ParseDiagnostic("rdo", "position_not_advertised", "The EPR request points to an empty or unadvertised slot.")
            return replace(rdo, status=ParseStatus.INVALID, diagnostics=(issue,))
        selected = slots[position - 1]
        if rdo.pdo_echo != selected.raw:
            issue = ParseDiagnostic("rdo", "epr_pdo_echo_mismatch", "EPR_Request PDO copy differs from the latest advertised PDO.")
            return replace(rdo, status=ParseStatus.INVALID, selected_pdo=selected, diagnostics=(issue,))
        return replace(decode_rdo(rdo.raw, selected, revision=result.header.spec_revision, epr=True), pdo_echo=rdo.pdo_echo)

    def consume(self, result: CaptureResult) -> PDSessionAnalysis:
        if isinstance(result, ResetResult):
            if result.sop.kind == SopKind.HARD_RESET:
                self.reset()
            elif result.sop.kind == SopKind.CABLE_RESET:
                self._source_pdos.pop(SopKind.SOP_PRIME, None)
                self._source_pdos.pop(SopKind.SOP_DOUBLE_PRIME, None)
            return PDSessionAnalysis(result)

        if not isinstance(result, PDMessageResult) or result.parse_status != ParseStatus.VALID or result.crc_valid is not True:
            return PDSessionAnalysis(result)

        sop = result.sop.kind
        name = result.message_type.name
        if name == "Soft_Reset":
            self._source_pdos.pop(sop, None)
            if sop == SopKind.SOP:
                self._epr_source = None
        elif name in ("PR_Swap", "FR_Swap") or (name == "EPR_Mode" and len(result.data_objects) == 1
                                                  and result.data_objects[0] >> 24 in (1, 4, 5)):
            self._epr_source = None
        elif name == "Source_Capabilities" and result.pdos:
            # Preserve positions when a CRC-valid capability message contains a bad PDO.
            self._source_pdos[sop] = result.pdos
        elif name == "EPR_Request" and result.rdo is not None:
            return PDSessionAnalysis(result, self._resolve_epr_request(result))
        elif name == "Request" and result.rdo is not None:
            rdo = result.rdo
            source_pdos = self.source_pdos(sop)
            position = rdo.object_position
            if source_pdos and 1 <= position <= SPR_PDO_COUNT:
                if position <= len(source_pdos):
                    rdo = decode_rdo(rdo.raw, source_pdos[position - 1], revision=result.header.spec_revision)
                else:
                    rdo = replace(rdo, status=ParseStatus.INVALID, diagnostics=(ParseDiagnostic(
                        "rdo", "position_not_advertised", f"Source advertised {len(source_pdos)} PDOs, requested {position}."
                    ),) + tuple(item for item in rdo.diagnostics if item.code != "context_missing"))
            return PDSessionAnalysis(result, rdo)
        return PDSessionAnalysis(result)
