from dataclasses import replace

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import VDMCommand, VDMCommandType, VDMInfo, VDMType, VDOInfo
from .sop import SopKind
from .vdo import decode_vdos
from .vdo_decoders import VDORegistry


PD_SID = 0xFF00
_DP_SID = 0xFF01
_COMMAND_NAMES = {
    VDMCommand.DISCOVER_IDENTITY: "Discover Identity",
    VDMCommand.DISCOVER_SVIDS: "Discover SVIDs",
    VDMCommand.DISCOVER_MODES: "Discover Modes",
    VDMCommand.ENTER_MODE: "Enter Mode",
    VDMCommand.EXIT_MODE: "Exit Mode",
    VDMCommand.ATTENTION: "Attention",
}
_DISCOVERY = (VDMCommand.DISCOVER_IDENTITY, VDMCommand.DISCOVER_SVIDS, VDMCommand.DISCOVER_MODES)
_MODE_TRANSITIONS = (VDMCommand.ENTER_MODE, VDMCommand.EXIT_MODE)


def _validate_structured(
    vdm: VDMInfo, sop: SopKind, revision: int, data_role: int | None, cable_plug: bool | None,
) -> list[ParseDiagnostic]:
    command = vdm.command
    command_type = vdm.command_type
    issues = []
    if vdm.reserved_bits:
        issues.append(ParseDiagnostic("vdm", "vdm_reserved_bits_nonzero", "Structured VDM Header sets reserved bit 5."))
    if vdm.version_major > 1 or (command < 16 and vdm.structured_version is None):
        issues.append(ParseDiagnostic("vdm", "vdm_reserved_version", "Structured VDM uses a reserved version code."))
    if revision == 1 and vdm.version_major != 0:
        issues.append(ParseDiagnostic("vdm", "vdm_version_revision", "USB PD 2.0 uses Structured VDM version 1.0."))

    if command < 16:
        position = vdm.object_position
        if command == VDMCommand.EXIT_MODE:
            position_valid = 1 <= position <= 7
        elif command in (VDMCommand.ENTER_MODE, VDMCommand.ATTENTION):
            position_valid = 1 <= position <= 6
        else:
            position_valid = position == 0
        if not position_valid:
            issues.append(ParseDiagnostic("vdm", "vdm_invalid_object_position", "Object Position is reserved for this VDM command."))
        if command in _DISCOVERY and sop not in (SopKind.SOP, SopKind.SOP_PRIME):
            issues.append(ParseDiagnostic("vdm", "vdm_command_sop", "Discovery commands use SOP or SOP′."))
        if command in (VDMCommand.DISCOVER_IDENTITY, VDMCommand.DISCOVER_SVIDS) and vdm.svid != PD_SID:
            issues.append(ParseDiagnostic("vdm", "vdm_invalid_svid", "Discover Identity and Discover SVIDs require PD SID 0xFF00."))
        if (command == VDMCommand.ATTENTION and command_type != VDMCommandType.INITIATOR
                or command in _MODE_TRANSITIONS and command_type == VDMCommandType.BUSY):
            issues.append(ParseDiagnostic("vdm", "vdm_command_type", "This VDM command does not allow the observed response type."))
        if command in _MODE_TRANSITIONS and sop == SopKind.SOP and data_role is not None:
            is_initiator = command_type == VDMCommandType.INITIATOR
            if data_role != int(is_initiator):
                issues.append(ParseDiagnostic("vdm", "vdm_data_role", "Enter and Exit Mode are initiated by the DFP toward the UFP."))
        if command in _DISCOVERY + _MODE_TRANSITIONS and cable_plug is not None:
            if cable_plug != (command_type != VDMCommandType.INITIATOR):
                issues.append(ParseDiagnostic("vdm", "vdm_cable_sender", "The Cable Plug bit disagrees with the VDM command type."))
    return issues


def decode_vdm(
    data_objects: tuple[int, ...], *, sop: SopKind | str = SopKind.SOP, revision: int = 2,
    data_role: int | None = None, cable_plug: bool | None = None, registry: VDORegistry | None = None,
) -> VDMInfo:
    """Decode a VDM without session state (USB PD R3.2 V1.1 Tables 6.28–6.32)."""
    if not data_objects:
        issue = ParseDiagnostic("vdm", "vdm_missing_header", "Vendor Defined Message requires a VDM Header object.")
        return VDMInfo(None, None, None, ParseStatus.PARTIAL, diagnostics=(issue,))
    if any(not 0 <= raw <= 0xFFFFFFFF for raw in data_objects):
        raise ValueError("VDM objects must be unsigned 32-bit words.")
    sop = SopKind(sop)
    raw_header, *payload = data_objects
    svid = raw_header >> 16
    structured = bool(raw_header & 0x8000)
    vdos = tuple(VDOInfo(index, raw) for index, raw in enumerate(payload, 1))
    issues = []
    if len(data_objects) > 7:
        issues.append(ParseDiagnostic("vdo", "vdo_unexpected_count", "A VDM may contain at most seven Data Objects."))
    if not svid:
        issues.append(ParseDiagnostic("vdm", "vdm_invalid_svid", "Zero is reserved for SVID termination."))
    if sop not in (SopKind.SOP, SopKind.SOP_PRIME, SopKind.SOP_DOUBLE_PRIME):
        issues.append(ParseDiagnostic("vdm", "vdm_command_sop", "This ordered set cannot carry a normal VDM."))
    status = ParseStatus.VALID
    if revision not in (1, 2):
        issues.append(ParseDiagnostic("vdm", "vdm_revision", "The PD Header revision is outside VDM decoding support."))
        status = ParseStatus.UNSUPPORTED if revision == 0 else ParseStatus.INVALID
    if structured:
        command = raw_header & 0x1F
        vdm = VDMInfo(
            raw_header, svid, VDMType.STRUCTURED, status,
            version_major=(raw_header >> 13) & 3, version_minor=(raw_header >> 11) & 3,
            object_position=(raw_header >> 8) & 7, command_type=VDMCommandType((raw_header >> 6) & 3),
            command=command, command_name=_COMMAND_NAMES.get(command), reserved_bits=raw_header & 0x20, vdos=vdos,
        )
        issues.extend(_validate_structured(vdm, sop, revision, data_role, cable_plug))
    else:
        vdm = VDMInfo(raw_header, svid, VDMType.UNSTRUCTURED, status, vendor_header_bits=raw_header & 0x7FFF, vdos=vdos)

    blocking = bool(issues)
    unknown_command = structured and vdm.command_name is None
    if unknown_command:
        issues.append(ParseDiagnostic("vdm", "vdm_unknown_command", f"No standard VDM command is defined for {vdm.command}."))
    if blocking or (unknown_command and vdm.command < 16):
        status = ParseStatus.UNSUPPORTED if status == ParseStatus.UNSUPPORTED else ParseStatus.INVALID
        return replace(vdm, status=status, diagnostics=tuple(issues))
    if unknown_command:
        status = ParseStatus.UNSUPPORTED
    if svid not in (PD_SID, _DP_SID):
        issues.append(ParseDiagnostic("vdm", "vdm_unknown_svid", f"SVID {svid:#06x} is outside the built-in PD SIDs."))
    return decode_vdos(replace(vdm, status=status, diagnostics=tuple(issues)), sop, revision, registry)
