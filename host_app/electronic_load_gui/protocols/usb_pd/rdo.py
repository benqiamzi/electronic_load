from dataclasses import replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import PDODirection, PDOInfo, RDOInfo, SupplyType


def _check_limits(
    operating: int, secondary: int, limit: int, unit: str, *, give_back: bool, mismatch: bool,
) -> list[ParseDiagnostic]:
    problems = []
    if operating > limit:
        problems.append(ParseDiagnostic("rdo", "operating_limit", f"Operating request exceeds {limit} {unit}."))
    if give_back and secondary > operating:
        problems.append(ParseDiagnostic("rdo", "minimum_exceeds_operating", "Minimum request exceeds operating request."))
    if not give_back and secondary < operating:
        problems.append(ParseDiagnostic("rdo", "maximum_below_operating", "Maximum request is below operating request."))
    if not give_back and secondary > limit and not mismatch:
        problems.append(ParseDiagnostic("rdo", "maximum_limit", f"Maximum request exceeds {limit} {unit}."))
    return problems


def decode_rdo(raw: int, selected_pdo: PDOInfo | None = None, *, revision: int = 2) -> RDOInfo:
    """Decode an SPR Request object using the layout of its selected Source PDO (§6.4.2)."""
    if not 0 <= raw <= 0xFFFFFFFF:
        raise ValueError("RDO requires an unsigned 32-bit word.")
    if revision not in (1, 2):
        raise ValueError("RDO decoding requires wire revision 1 (PD 2.0) or 2 (PD 3.x).")

    position = raw >> 28
    rdo = RDOInfo(
        raw, position, ParseStatus.VALID,
        capability_mismatch=bool(raw & (1 << 26)),
        usb_communications_capable=bool(raw & (1 << 25)),
        no_usb_suspend=bool(raw & (1 << 24)),
        unchunked_extended_messages_supported=bool(raw & (1 << 23)) if revision == 2 else None,
        epr_capable=bool(raw & (1 << 22)) if revision == 2 else None,
    )
    problems = []
    # B21 is reserved in all SPR layouts. B27 is deprecated or reserved in PD 3.x.
    reserved_mask = (1 << 21) | ((1 << 27) if revision == 2 else (3 << 22))
    if not 1 <= position <= 7:
        problems.append(ParseDiagnostic("rdo", "object_position", "SPR Request position must be from 1 to 7."))

    status = ParseStatus.VALID
    if selected_pdo is None:
        status = ParseStatus.CONTEXT_MISSING
    elif selected_pdo.direction != PDODirection.SOURCE or selected_pdo.index not in (None, position):
        problems.append(ParseDiagnostic("rdo", "pdo_selection", "The supplied PDO does not match the requested Source position."))
    elif 1 <= position <= 7:
        kind = selected_pdo.supply_type
        rdo = replace(rdo, selected_pdo=selected_pdo, request_type=kind)
        if selected_pdo.status == ParseStatus.INVALID:
            problems.append(ParseDiagnostic("rdo", "invalid_pdo", "The selected Source PDO has invalid fields."))
        elif kind == SupplyType.PPS and revision == 2:
            reserved_mask |= 3 << 7
            current = (raw & 0x7F) * 50
            voltage = ((raw >> 9) & 0xFFF) * 20
            rdo = replace(rdo, operating_current_ma=current, operating_voltage_mv=voltage)
            if current > selected_pdo.current_max_ma:
                problems.append(ParseDiagnostic("rdo", "operating_limit", "PPS operating current exceeds the advertised maximum."))
            if not selected_pdo.voltage_min_mv <= voltage <= selected_pdo.voltage_max_mv:
                problems.append(ParseDiagnostic("rdo", "voltage_range", "Requested PPS voltage is outside the advertised range."))
        elif kind in (SupplyType.FIXED, SupplyType.VARIABLE, SupplyType.BATTERY):
            reserved_mask |= 1 << 20
            give_back = bool(raw & (1 << 27))
            legacy_minimum = give_back and revision == 1
            battery = kind == SupplyType.BATTERY
            scale = 250 if battery else 10
            operating = ((raw >> 10) & 0x3FF) * scale
            secondary = (raw & 0x3FF) * scale
            rdo = replace(rdo, give_back=give_back)
            if battery:
                rdo = replace(rdo, operating_power_mw=operating,
                              maximum_operating_power_mw=None if legacy_minimum else secondary,
                              minimum_operating_power_mw=secondary if legacy_minimum else None)
                limit, unit = selected_pdo.power_max_mw, "mW"
            else:
                rdo = replace(rdo, operating_current_ma=operating,
                              maximum_operating_current_ma=None if legacy_minimum else secondary,
                              minimum_operating_current_ma=secondary if legacy_minimum else None)
                limit, unit = selected_pdo.current_max_ma, "mA"
            problems.extend(_check_limits(operating, secondary, limit, unit,
                                          give_back=legacy_minimum, mismatch=rdo.capability_mismatch))
        else:
            status = ParseStatus.UNSUPPORTED

    reserved = raw & reserved_mask
    if reserved:
        problems.append(ParseDiagnostic("rdo", "reserved_bits", f"RDO sets reserved or deprecated bits {reserved:#010x}."))
    if problems:
        status = ParseStatus.INVALID
    elif status == ParseStatus.CONTEXT_MISSING:
        problems.append(ParseDiagnostic("rdo", "context_missing", "No Source PDO is available for this Request."))
    elif status == ParseStatus.UNSUPPORTED:
        problems.append(ParseDiagnostic("rdo", "unsupported_request", "The selected PDO layout is outside SPR Request support."))
    elif revision == 2 and (rdo.maximum_operating_current_ma not in (None, rdo.operating_current_ma)
                            or rdo.maximum_operating_power_mw not in (None, rdo.operating_power_mw)):
        # The Header does not distinguish 3.0/3.1 from 3.2. Preserve legacy requests.
        problems.append(ParseDiagnostic("rdo", "legacy_maximum", "R3.2 requires the deprecated maximum field to equal the operating field."))
    return replace(rdo, status=status, reserved_bits=reserved, diagnostics=tuple(problems))
