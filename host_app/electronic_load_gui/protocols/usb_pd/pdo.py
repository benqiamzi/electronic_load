from dataclasses import replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import PDODirection, PDOInfo, SupplyType


SPR_PDO_COUNT = 7
MAX_EPR_PDO_POSITION = 11

_FIXED_SHARED_FLAGS = {
    29: "dual_role_power", 27: "unconstrained_power",
    26: "usb_communications_capable", 25: "dual_role_data",
}
_FIXED_LEGACY_SOURCE_FLAGS = {**_FIXED_SHARED_FLAGS, 28: "usb_suspend_supported"}
_FIXED_SOURCE_FLAGS = {
    **_FIXED_LEGACY_SOURCE_FLAGS,
    24: "unchunked_extended_messages_supported", 23: "epr_capable",
}
_FIXED_SINK_FLAGS = {**_FIXED_SHARED_FLAGS, 28: "higher_capability"}
_APDO_TYPES = {0: SupplyType.PPS, 1: SupplyType.EPR_AVS, 2: SupplyType.SPR_AVS}


def _decode_fixed(pdo: PDOInfo, revision: int) -> PDOInfo:
    raw = pdo.raw
    voltage = ((raw >> 10) & 0x3FF) * 50
    current = (raw & 0x3FF) * 10
    port_flags = voltage == 5000 and pdo.index in (None, 1)
    if pdo.direction == PDODirection.SOURCE:
        flags = _FIXED_SOURCE_FLAGS if revision == 2 else _FIXED_LEGACY_SOURCE_FLAGS
        flags = flags if port_flags else {}
        pdo = replace(pdo, current_max_ma=current, peak_current_code=(raw >> 20) & 3)
        allowed = 3 << 20
    else:
        flags = _FIXED_SINK_FLAGS if port_flags else {}
        frs = ((raw >> 23) & 3) if port_flags and revision == 2 else None
        pdo = replace(pdo, operating_current_ma=current, fast_role_swap_current_code=frs)
        allowed = 3 << 23 if frs is not None else 0
    allowed |= sum(1 << bit for bit in flags)
    return replace(
        pdo, voltage_min_mv=voltage, voltage_max_mv=voltage,
        capabilities=frozenset(name for bit, name in flags.items() if raw & (1 << bit)),
        reserved_bits=raw & 0x3FF00000 & ~allowed,
    )


def _decode_apdo(pdo: PDOInfo) -> PDOInfo:
    raw = pdo.raw
    source = pdo.direction == PDODirection.SOURCE
    if pdo.supply_type == SupplyType.PPS:
        reserved = (3 << 25) | (1 << 16) | (1 << 7)
        if not source:
            reserved |= 1 << 27
        return replace(
            pdo, voltage_min_mv=((raw >> 8) & 0xFF) * 100,
            voltage_max_mv=((raw >> 17) & 0xFF) * 100,
            current_max_ma=(raw & 0x7F) * 50,
            pps_power_limited=bool(raw & (1 << 27)) if source else None,
            reserved_bits=raw & reserved,
        )
    peak = ((raw >> 26) & 3) if source else None
    if pdo.supply_type == SupplyType.SPR_AVS:
        current_20v = (raw & 0x3FF) * 10
        reserved = (0x3F if source else 0xFF) << 20
        return replace(
            pdo, voltage_min_mv=9000, voltage_max_mv=20000 if current_20v else 15000,
            current_max_15v_ma=((raw >> 10) & 0x3FF) * 10,
            current_max_20v_ma=current_20v,
            peak_current_code=peak, reserved_bits=raw & reserved,
        )
    if pdo.supply_type == SupplyType.EPR_AVS:
        reserved = (1 << 16) | (0 if source else 3 << 26)
        return replace(
            pdo, voltage_min_mv=((raw >> 8) & 0xFF) * 100,
            voltage_max_mv=((raw >> 17) & 0x1FF) * 100,
            pdp_mw=(raw & 0xFF) * 1000, peak_current_code=peak,
            reserved_bits=raw & reserved,
        )
    return pdo


def decode_pdo(
    raw: int, *, direction: PDODirection | str, revision: int = 2, index: int | None = None,
) -> PDOInfo:
    """Decode one PDO (USB PD R3.2 V1.1, §6.4.1). Index is one-based when known."""
    if not 0 <= raw <= 0xFFFFFFFF:
        raise ValueError("PDO requires an unsigned 32-bit word.")
    if revision not in (1, 2):
        raise ValueError("PDO decoding requires wire revision 1 (PD 2.0) or 2 (PD 3.x).")
    direction = PDODirection(direction)
    kind = raw >> 30
    subtype = (raw >> 28) & 3 if kind == 3 else None
    supply_type = (SupplyType.FIXED, SupplyType.BATTERY, SupplyType.VARIABLE)[kind] if kind < 3 else (
        _APDO_TYPES.get(subtype, SupplyType.UNKNOWN_APDO)
    )
    pdo = PDOInfo(raw, index, direction, supply_type, apdo_subtype=subtype)
    problems = []
    if kind == 0:
        pdo = _decode_fixed(pdo, revision)
    elif kind < 3:
        amount = raw & 0x3FF
        pdo = replace(pdo, voltage_min_mv=((raw >> 10) & 0x3FF) * 50,
                      voltage_max_mv=((raw >> 20) & 0x3FF) * 50)
        if kind == 1 and direction == PDODirection.SOURCE:
            pdo = replace(pdo, power_max_mw=amount * 250)
        elif kind == 1:
            pdo = replace(pdo, operating_power_mw=amount * 250)
        elif direction == PDODirection.SOURCE:
            pdo = replace(pdo, current_max_ma=amount * 10)
        else:
            pdo = replace(pdo, operating_current_ma=amount * 10)
    elif revision == 1:
        problems.append(ParseDiagnostic("pdo", "apdo_revision", "APDO requires USB PD 3.x."))
    else:
        pdo = _decode_apdo(pdo)

    if index == 1 and (supply_type != SupplyType.FIXED or pdo.voltage_min_mv != 5000):
        problems.append(ParseDiagnostic("pdo", "first_pdo", "The first PDO must be Fixed vSafe5V."))
    if pdo.reserved_bits:
        problems.append(ParseDiagnostic("pdo", "reserved_bits", f"PDO sets reserved bits {pdo.reserved_bits:#010x}."))
    if pdo.voltage_min_mv is not None and not 0 < pdo.voltage_min_mv <= pdo.voltage_max_mv:
        problems.append(ParseDiagnostic("pdo", "voltage_range", "PDO voltage range is zero or reversed."))
    if supply_type == SupplyType.PPS and pdo.voltage_max_mv is not None and pdo.voltage_max_mv > 21000:
        problems.append(ParseDiagnostic("pdo", "pps_voltage_limit", "SPR PPS maximum voltage exceeds 21 V."))
    if supply_type == SupplyType.EPR_AVS and pdo.voltage_min_mv is not None and (
        pdo.voltage_min_mv < 15000 or pdo.voltage_max_mv > 48000
    ):
        problems.append(ParseDiagnostic("pdo", "avs_voltage_limit", "EPR AVS voltage fields are outside 15–48 V."))

    status = ParseStatus.INVALID if problems else ParseStatus.VALID
    if supply_type == SupplyType.UNKNOWN_APDO:
        problems.append(ParseDiagnostic("pdo", "unsupported_apdo", f"APDO subtype {subtype} is reserved."))
        if status == ParseStatus.VALID:
            status = ParseStatus.UNSUPPORTED
    return replace(pdo, status=status, diagnostics=tuple(problems))
