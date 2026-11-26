from dataclasses import replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import CaptureResult, PDMessageResult, PDOInfo, PDSessionAnalysis, ResetResult
from .rdo import decode_rdo
from .sop import SopKind


class PDSessionContext:
    """Associate Requests with capabilities observed in order on one captured link."""

    def __init__(self) -> None:
        self._source_pdos: dict[SopKind, tuple[PDOInfo, ...]] = {}

    def reset(self) -> None:
        """Discard all observations when capture continuity is lost."""
        self._source_pdos.clear()

    def disconnect(self) -> None:
        self.reset()

    def source_pdos(self, sop: SopKind = SopKind.SOP) -> tuple[PDOInfo, ...]:
        return self._source_pdos.get(sop, ())

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
        elif name == "Source_Capabilities" and result.pdos:
            # Preserve positions when a CRC-valid capability message contains a bad PDO.
            self._source_pdos[sop] = result.pdos
        elif name == "Request" and result.rdo is not None:
            rdo = result.rdo
            source_pdos = self.source_pdos(sop)
            position = rdo.object_position
            if source_pdos and 1 <= position <= 7:
                if position <= len(source_pdos):
                    rdo = decode_rdo(rdo.raw, source_pdos[position - 1], revision=result.header.spec_revision)
                else:
                    rdo = replace(rdo, status=ParseStatus.INVALID, diagnostics=(ParseDiagnostic(
                        "rdo", "position_not_advertised", f"Source advertised {len(source_pdos)} PDOs, requested {position}."
                    ),) + tuple(item for item in rdo.diagnostics if item.code != "context_missing"))
            return PDSessionAnalysis(result, rdo)
        return PDSessionAnalysis(result)
