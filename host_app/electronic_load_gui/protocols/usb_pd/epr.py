from struct import iter_unpack

from .diagnostics import ParseDiagnostic, ParseStatus
from .message_types import EPR_SOURCE_CAPABILITIES
from .models import EPRSourceCapabilities, ExtendedDirection, ReassembledExtendedMessage, ReassemblyStatus, SupplyType
from .pdo import MAX_EPR_PDO_POSITION, SPR_PDO_COUNT, decode_pdo
from .sop import SopKind


_EPR_FIXED_VOLTAGES = (28000, 36000, 48000)


def decode_epr_source_capabilities(message: ReassembledExtendedMessage) -> EPRSourceCapabilities | None:
    """Interpret complete words in the contiguous payload of EPR Source Capabilities (§6.5.15)."""
    if message.message_type != EPR_SOURCE_CAPABILITIES:
        return None
    payload = message.payload
    complete = message.status == ReassemblyStatus.COMPLETE
    problems = []
    if message.sop != SopKind.SOP or message.direction != ExtendedDirection.SOURCE:
        problems.append(ParseDiagnostic("epr", "epr_sender", "EPR Source Capabilities must come from the SOP Source."))
    if message.data_size % 4 or not SPR_PDO_COUNT <= message.data_size // 4 <= MAX_EPR_PDO_POSITION:
        problems.append(ParseDiagnostic("epr", "epr_capabilities_size", "EPR Capabilities requires 7–11 aligned PDO slots."))
    words = tuple(word for (word,) in iter_unpack("<I", payload[:len(payload) // 4 * 4]))
    spr = []
    epr = []
    padding_seen = False
    avs_seen = False
    last_fixed_voltage = 0
    for position, raw in enumerate(words, 1):
        if 1 < position <= SPR_PDO_COUNT and not raw:
            padding_seen = True
            spr.append(None)
            continue
        pdo = decode_pdo(raw, direction="source", index=position)
        problems.extend(pdo.diagnostics)
        if position <= SPR_PDO_COUNT:
            spr.append(pdo)
            if padding_seen:
                problems.append(ParseDiagnostic("epr", "epr_spr_padding", "SPR PDO follows a zero-filled SPR slot."))
            if pdo.supply_type == SupplyType.EPR_AVS or (pdo.supply_type == SupplyType.FIXED and pdo.voltage_max_mv > 20000):
                problems.append(ParseDiagnostic("epr", "epr_in_spr_position", "An EPR PDO appears in an SPR slot."))
        else:
            epr.append(pdo)
            if pdo.supply_type == SupplyType.FIXED and pdo.voltage_max_mv in _EPR_FIXED_VOLTAGES:
                if avs_seen or pdo.voltage_max_mv <= last_fixed_voltage:
                    problems.append(ParseDiagnostic("epr", "epr_pdo_order", "EPR Fixed PDOs must increase in voltage and precede AVS."))
                last_fixed_voltage = pdo.voltage_max_mv
            elif pdo.supply_type == SupplyType.EPR_AVS:
                if avs_seen:
                    problems.append(ParseDiagnostic("epr", "epr_pdo_order", "EPR Capabilities can contain only one EPR AVS APDO."))
                avs_seen = True
            else:
                problems.append(ParseDiagnostic("epr", "epr_pdo_type", "EPR slots require Fixed 28/36/48 V or EPR AVS."))
    if complete and epr and not avs_seen:
        problems.append(ParseDiagnostic("epr", "missing_epr_avs", "An EPR PDO tail requires an EPR AVS APDO."))
    status = ParseStatus.INVALID if problems else ParseStatus.VALID
    if not complete:
        problems.append(ParseDiagnostic("epr", "partial_epr_capabilities", "Only complete PDO words in the contiguous prefix are decoded."))
        if status == ParseStatus.VALID:
            status = ParseStatus.PARTIAL
    return EPRSourceCapabilities(words, tuple(spr), tuple(epr), status, tuple(problems))
