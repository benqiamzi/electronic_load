from dataclasses import replace
from types import MappingProxyType

from .diagnostics import ParseDiagnostic, ParseStatus
from .models import VDMCommand, VDMCommandType, VDMInfo, VDMType, VDOInfo
from .sop import SopKind
from .vdo_decoders import VDODecodeContext, VDORegistry


_ID_CORE = ("id_header", "cert_stat", "product")
_CABLE_VDOS = {0: (), 3: ("passive_cable",), 4: ("active_cable_1", "active_cable_2"), 6: ("vpd",)}
_POSITION_COMMANDS = (VDMCommand.ENTER_MODE, VDMCommand.EXIT_MODE, VDMCommand.ATTENTION)


def _decode_id_header(raw: int, sop: SopKind, legacy: bool) -> tuple[dict[str, object], tuple[ParseDiagnostic, ...]]:
    product_type = (raw >> 27) & 7
    fields = {
        "usb_host_capable": bool(raw & (1 << 31)),
        "usb_device_capable": bool(raw & (1 << 30)),
        "modal_operation_supported": bool(raw & (1 << 26)),
        "usb_vid": raw & 0xFFFF,
        "product_type_ufp" if sop == SopKind.SOP else "product_type_cable": product_type,
    }
    reserved = raw & (0x3FF0000 if legacy else 0x1F0000)
    diagnostics = []
    if not legacy:
        connector = (raw >> 21) & 3
        fields["connector_type"] = connector
        if connector == 1:
            diagnostics.append(ParseDiagnostic("vdo", "vdo_connector_type", "ID Header Connector Type 1 is reserved."))
        if sop == SopKind.SOP:
            dfp = (raw >> 23) & 7
            fields["product_type_dfp"] = dfp
            invalid_type = product_type > 3 or dfp > 3
        else:
            reserved |= raw & (7 << 23)
            invalid_type = product_type not in _CABLE_VDOS
        if invalid_type:
            diagnostics.append(ParseDiagnostic("vdo", "vdo_product_type", "ID Header declares a reserved Product Type."))
    if reserved:
        diagnostics.append(ParseDiagnostic("vdo", "vdo_reserved_bits_nonzero", f"ID Header sets reserved bits {reserved:#010x}."))
    return fields, tuple(diagnostics)


def _identity_vdos(id_fields: dict[str, object], sop: SopKind) -> tuple[str, ...]:
    if sop == SopKind.SOP_PRIME:
        return _CABLE_VDOS[id_fields["product_type_cable"]]
    ufp = id_fields["product_type_ufp"] in (1, 2)
    dfp = id_fields["product_type_dfp"] != 0
    if ufp and dfp:
        return ("ufp", "identity_pad", "dfp")
    if ufp:
        return ("ufp",)
    if dfp:
        return ("dfp",)
    return ()


def _decode_identity(vdm: VDMInfo, sop: SopKind) -> VDMInfo:
    legacy = vdm.version_major == 0
    categories = _ID_CORE
    decoded = []
    issues = []
    layout_known = not legacy
    for vdo in vdm.vdos:
        category = categories[vdo.index - 1] if vdo.index <= len(categories) else "identity_extra"
        fields = None
        diagnostics = ()
        if category == "id_header":
            fields, diagnostics = _decode_id_header(vdo.raw, sop, legacy)
            if any(item.code == "vdo_product_type" for item in diagnostics):
                layout_known = False
            if layout_known:
                categories += _identity_vdos(fields, sop)
        elif category == "cert_stat":
            fields = {"xid": vdo.raw}
        elif category == "product":
            fields = {"usb_pid": vdo.raw >> 16, "bcd_device": vdo.raw & 0xFFFF}
        elif category == "identity_pad" and vdo.raw != 0:
            diagnostics = (ParseDiagnostic("vdo", "vdo_identity_pad", "The DRD identity Pad VDO must be zero."),)
        if category == "identity_extra" and not layout_known:
            category = "identity_type_raw"
        decoded.append(replace(vdo, category=category, decoded_fields=MappingProxyType(fields) if fields else None,
                               diagnostics=diagnostics))
        issues.extend(diagnostics)

    status = ParseStatus.INVALID if issues else ParseStatus.VALID
    if len(decoded) < len(categories):
        missing = ", ".join(categories[len(decoded):])
        issues.append(ParseDiagnostic("vdo", "vdo_truncated", f"Identity ACK is missing {missing}."))
        if status == ParseStatus.VALID:
            status = ParseStatus.PARTIAL
    if layout_known and len(decoded) > len(categories):
        issues.append(ParseDiagnostic("vdo", "vdo_unexpected_count", "Identity ACK contains extra VDOs."))
        status = ParseStatus.INVALID
    if legacy and len(decoded) > len(_ID_CORE):
        issues.append(ParseDiagnostic("vdo", "vdo_legacy_identity", "Legacy Product Type VDOs are retained as raw words."))
    return replace(vdm, status=status, vdos=tuple(decoded), diagnostics=vdm.diagnostics + tuple(issues))


def _decode_svids(vdm: VDMInfo) -> VDMInfo:
    svids = []
    decoded = []
    terminated = False
    issues = []
    for vdo in vdm.vdos:
        high, low = vdo.raw >> 16, vdo.raw & 0xFFFF
        if terminated or (high == 0 and low != 0):
            issues.append(ParseDiagnostic("vdo", "vdo_svid_termination", "Unexpected SVID data after a zero terminator."))
        if not terminated and high:
            svids.append(high)
            if low:
                svids.append(low)
        terminated |= high == 0 or low == 0
        decoded.append(replace(vdo, category="svid_pair",
                               decoded_fields=MappingProxyType({"svid_high": high, "svid_low": low})))
    if len(set(svids)) != len(svids):
        issues.append(ParseDiagnostic("vdo", "vdo_duplicate_svid", "SVID ACK contains repeated entries."))
    if not terminated and len(vdm.vdos) != 6:
        issues.append(ParseDiagnostic("vdo", "vdo_svid_termination", "A nonterminal SVID ACK must carry twelve SVIDs."))
    return replace(vdm, status=ParseStatus.INVALID if issues else ParseStatus.VALID,
                   vdos=tuple(decoded), discovered_svids=tuple(svids), svids_terminated=terminated,
                   diagnostics=vdm.diagnostics + tuple(issues))


def _decode_vendor(vdm: VDMInfo, sop: SopKind, revision: int, registry: VDORegistry | None) -> VDMInfo:
    decoded = []
    issues = []
    for vdo in vdm.vdos:
        position = vdo.mode_position if vdo.mode_position is not None else vdm.object_position
        decoder = registry.get(vdm.svid, command=vdm.command, position=position) if registry else None
        fields = None
        diagnostic = None
        if decoder is None:
            diagnostic = ParseDiagnostic("vdo", "vdo_decoder_unavailable", "No decoder for this SVID and VDO context.")
        else:
            try:
                context = VDODecodeContext(sop, revision, vdm, vdo.index, position)
                value = decoder.decode(vdo.raw, context)
                if value is not None:
                    fields = MappingProxyType(dict(value))
            except Exception as error:
                diagnostic = ParseDiagnostic("vdo", "vdo_decoder_error", f"The registered decoder raised {type(error).__name__}.")
        if diagnostic is not None:
            issues.append(diagnostic)
            vdo = replace(vdo, diagnostics=(diagnostic,))
        decoded.append(replace(vdo, vendor_fields=fields))
    return replace(vdm, vdos=tuple(decoded), diagnostics=vdm.diagnostics + tuple(issues))


def decode_vdos(vdm: VDMInfo, sop: SopKind, revision: int, registry: VDORegistry | None) -> VDMInfo:
    """Decode the VDOs allowed by a validated VDM Header (USB PD R3.2 V1.1 §6.4.4.3)."""
    if vdm.vdm_type == VDMType.UNSTRUCTURED or vdm.command >= 16:
        category = "unstructured_vendor" if vdm.vdm_type == VDMType.UNSTRUCTURED else "svid_specific"
        vdm = replace(vdm, vdos=tuple(replace(vdo, category=category) for vdo in vdm.vdos))
        return _decode_vendor(vdm, sop, revision, registry)

    command = vdm.command
    ack = vdm.command_type == VDMCommandType.ACK
    if ack and command == VDMCommand.DISCOVER_IDENTITY:
        return _decode_identity(vdm, sop)

    if ack and command in (VDMCommand.DISCOVER_SVIDS, VDMCommand.DISCOVER_MODES):
        minimum, maximum = 1, 6
    elif vdm.command_type == VDMCommandType.INITIATOR and command in (VDMCommand.ENTER_MODE, VDMCommand.ATTENTION):
        minimum, maximum = 0, 1
    else:
        minimum = maximum = 0
    if not minimum <= len(vdm.vdos) <= maximum:
        issue = ParseDiagnostic("vdo", "vdo_unexpected_count", f"{vdm.command_name} expects {minimum}–{maximum} VDOs for this command type.")
        return replace(vdm, status=ParseStatus.INVALID, diagnostics=vdm.diagnostics + (issue,))
    if ack and command == VDMCommand.DISCOVER_SVIDS:
        return _decode_svids(vdm)
    if ack and command == VDMCommand.DISCOVER_MODES:
        vdm = replace(vdm, vdos=tuple(replace(vdo, category="mode", mode_position=vdo.index) for vdo in vdm.vdos))
    elif command in _POSITION_COMMANDS:
        vdm = replace(vdm, vdos=tuple(replace(vdo, category="mode_payload", mode_position=vdm.object_position)
                                      for vdo in vdm.vdos))
    return _decode_vendor(vdm, sop, revision, registry) if vdm.vdos else vdm
