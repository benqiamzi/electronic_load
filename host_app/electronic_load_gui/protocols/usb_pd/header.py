from dataclasses import dataclass

from .diagnostics import ParseDiagnostic
from .sop import SopKind


@dataclass(frozen=True, slots=True)
class PDHeader:
    raw_bytes: bytes
    raw_value: int
    message_type: int
    data_role: int | None
    spec_revision: int
    power_role: int | None
    cable_plug: bool | None
    message_id: int
    num_data_objects: int
    extended: bool


def decode_header(raw: bytes, sop: SopKind) -> tuple[PDHeader | None, tuple[ParseDiagnostic, ...]]:
    """Decode the first two bytes using USB PD R3.2 V1.1 Table 6.1."""
    if len(raw) < 2:
        return None, (ParseDiagnostic("header", "short_header", "PD Header requires two bytes."),)

    header_bytes = raw[:2]
    value = int.from_bytes(header_bytes, "little")
    revision = (value >> 6) & 0b11
    role_or_plug = (value >> 8) & 1
    extended = bool(value & 0x8000)
    is_port = sop == SopKind.SOP
    is_cable = sop in (SopKind.SOP_PRIME, SopKind.SOP_DOUBLE_PRIME)

    diagnostics = []
    if revision == 3:
        diagnostics.append(ParseDiagnostic("header", "reserved_revision", "Revision 0b11 is reserved."))
    if not is_port and value & 0x20:
        diagnostics.append(ParseDiagnostic("header", "reserved_data_role", "Bit 5 is reserved for this SOP."))
    if extended and revision < 2:
        diagnostics.append(ParseDiagnostic("header", "reserved_extended", "Extended messages require PD 3.x."))

    # §6.2.1.1.7 defines 1 as Cable Plug/VPD and 0 as DFP/UFP.
    return PDHeader(
        raw_bytes=header_bytes,
        raw_value=value,
        message_type=value & 0x1F,
        data_role=(value >> 5) & 1 if is_port else None,
        spec_revision=revision,
        power_role=role_or_plug if is_port else None,
        cable_plug=bool(role_or_plug) if is_cable else None,
        message_id=(value >> 9) & 0b111,
        num_data_objects=(value >> 12) & 0b111,
        extended=extended,
    ), tuple(diagnostics)
