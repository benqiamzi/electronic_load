from struct import iter_unpack

from ...devices.drpd.capture_record import CaptureRecord, DecodeResult, FirmwareEvent
from .crc import calculate_crc32
from .diagnostics import ParseDiagnostic, ParseStatus
from .header import PDHeader, decode_header
from .message_types import MessageCategory, classify_message
from .models import CaptureResult, FirmwareEventResult, PDMessageResult, PDODirection, ParseFailureResult, ResetResult
from .pdo import decode_pdo
from .rdo import decode_rdo
from .sop import SopKind, classify_sop
from .vdm import decode_vdm
from .vdo_decoders import VDORegistry


def _decode_body(raw: bytes, header: PDHeader) -> tuple[bytes | None, ParseStatus, ParseDiagnostic | None]:
    if header.extended:
        # The extended header determines the length of unchunked packets.
        return None, ParseStatus.UNSUPPORTED, ParseDiagnostic(
            "body", "extended_pending", "Extended message body decoding is pending."
        )
    expected = 2 + header.num_data_objects * 4 + 4
    if len(raw) != expected:
        status = ParseStatus.PARTIAL if len(raw) < expected else ParseStatus.INVALID
        return None, status, ParseDiagnostic(
            "body", "message_length", f"Expected {expected} captured bytes, received {len(raw)}."
        )
    return raw[2:-4], ParseStatus.VALID, None


def parse_capture(record: CaptureRecord | FirmwareEvent, *, vdo_registry: VDORegistry | None = None) -> CaptureResult:
    """Parse one offline capture and retain the original record in the result."""
    if isinstance(record, FirmwareEvent):
        return FirmwareEventResult(record)

    sop = classify_sop(record.sop_bytes)
    firmware_ok = record.decode_result == DecodeResult.SUCCESS
    diagnostics = []
    if not firmware_ok:
        diagnostics.append(ParseDiagnostic(
            "capture", "firmware_decode_failed", f"DRPD decode result {record.decode_result:#x}."
        ))
    if record.is_hard_reset or (sop.kind == SopKind.CABLE_RESET and firmware_ok and not record.decoded_data):
        return ResetResult(record, sop)
    if not sop.is_message:
        status = ParseStatus.UNKNOWN if sop.kind == SopKind.UNKNOWN else ParseStatus.UNSUPPORTED
        if sop.kind in (SopKind.HARD_RESET, SopKind.CABLE_RESET):
            status = ParseStatus.INVALID
        diagnostics.append(ParseDiagnostic("sop", "no_message_sop", f"No PD Header for {sop.kind}."))
        return ParseFailureResult(record, sop, status, tuple(diagnostics))
    if sop.matched_symbols == 3:
        diagnostics.append(ParseDiagnostic("sop", "recovered_sop", "Three K-code symbols match."))

    header, header_diagnostics = decode_header(record.decoded_data, sop.kind)
    diagnostics.extend(header_diagnostics)
    if header is None:
        return ParseFailureResult(record, sop, ParseStatus.PARTIAL, tuple(diagnostics))
    raw = record.decoded_data
    body, body_status, body_diagnostic = _decode_body(raw, header)
    if body_diagnostic is not None:
        diagnostics.append(body_diagnostic)
    message_type, type_diagnostic = classify_message(header, sop.kind)
    if type_diagnostic is not None:
        diagnostics.append(type_diagnostic)
    objects = ()
    if body is not None and message_type.category == MessageCategory.DATA:
        objects = tuple(word for (word,) in iter_unpack("<I", body))
        if message_type.name == "Request" and len(objects) != 1:
            body_status = ParseStatus.INVALID
            diagnostics.append(ParseDiagnostic("body", "request_object_count", "Request requires exactly one RDO."))

    received = calculated = valid = None
    if firmware_ok and body is not None:
        received = int.from_bytes(raw[-4:], "little")
        calculated = calculate_crc32(raw[:-4])
        valid = received == calculated
        if not valid:
            diagnostics.append(ParseDiagnostic("crc", "crc_mismatch", "Received CRC32 does not match the host calculation."))

    header_status = ParseStatus.INVALID if header_diagnostics else ParseStatus.VALID
    if ParseStatus.INVALID in (header_status, body_status, message_type.status) or valid is False:
        status = ParseStatus.INVALID
    elif not firmware_ok or body_status == ParseStatus.PARTIAL:
        status = ParseStatus.PARTIAL
    elif body_status == ParseStatus.VALID:
        status = message_type.status
    else:
        status = body_status

    pdos = ()
    rdo = None
    vdm = None
    if status == ParseStatus.VALID and valid is True:
        if message_type.name in ("Source_Capabilities", "Sink_Capabilities"):
            direction = PDODirection.SOURCE if message_type.name == "Source_Capabilities" else PDODirection.SINK
            pdos = tuple(decode_pdo(word, direction=direction, revision=header.spec_revision, index=index)
                         for index, word in enumerate(objects, 1))
        elif message_type.name == "Request":
            rdo = decode_rdo(objects[0], revision=header.spec_revision)
        elif message_type.name == "Vendor_Defined":
            vdm = decode_vdm(objects, sop=sop.kind, revision=header.spec_revision,
                             data_role=header.data_role, cable_plug=header.cable_plug, registry=vdo_registry)

    return PDMessageResult(
        record=record, sop=sop, header=header, message_type=message_type,
        body=body, data_objects=objects,
        header_status=header_status, body_status=body_status, parse_status=status,
        diagnostics=tuple(diagnostics), crc_received=received,
        crc_calculated=calculated, crc_valid=valid, pdos=pdos, rdo=rdo, vdm=vdm,
    )
