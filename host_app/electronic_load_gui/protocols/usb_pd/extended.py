from .diagnostics import ParseDiagnostic, ParseStatus
from .header import PDHeader
from .models import ExtendedHeader, ExtendedKind, ExtendedMessageInfo
from .sop import SopKind


# USB PD R3.2 V1.1 §6.2.1.2 and Tables 6.3 and 6.84.
EXTENDED_HEADER_SIZE = 2
MAX_EXTENDED_DATA_SIZE = 260
CHUNK_DATA_SIZE = 26
MAX_CHUNK_NUMBER = MAX_EXTENDED_DATA_SIZE // CHUNK_DATA_SIZE - 1
_CHUNKED = 1 << 15
_CHUNK_NUMBER_SHIFT = 11
_CHUNK_NUMBER_MASK = 0xF
_REQUEST_CHUNK = 1 << 10
_RESERVED = 1 << 9
_DATA_SIZE_MASK = 0x1FF
_OBJECT_BYTES = 4


def chunk_count(data_size: int) -> int:
    return max(1, (data_size + CHUNK_DATA_SIZE - 1) // CHUNK_DATA_SIZE)


def decode_extended_header(raw: bytes) -> ExtendedHeader | None:
    if len(raw) < EXTENDED_HEADER_SIZE:
        return None
    value = int.from_bytes(raw[:EXTENDED_HEADER_SIZE], "little")
    return ExtendedHeader(value, value & _DATA_SIZE_MASK, bool(value & _CHUNKED),
                          (value >> _CHUNK_NUMBER_SHIFT) & _CHUNK_NUMBER_MASK,
                          bool(value & _REQUEST_CHUNK), value & _RESERVED)


def decode_extended_message(header: PDHeader, raw_body: bytes, sop: SopKind) -> ExtendedMessageInfo:
    """Decode the bytes between the PD Header and CRC of one captured frame."""
    if not header.extended:
        raise ValueError("An Extended Message requires the PD Header Extended bit.")
    ext = decode_extended_header(raw_body)
    if ext is None:
        issue = ParseDiagnostic("extended", "short_extended_header", "Extended Header requires two bytes.")
        return ExtendedMessageInfo(header.message_type, None, None, b"", b"", raw_body,
                                   ParseStatus.PARTIAL, None, (issue,))

    problems = []
    if ext.reserved:
        problems.append(ParseDiagnostic("extended", "extended_reserved_bit", "Extended Header bit 9 is reserved."))
    if ext.data_size > MAX_EXTENDED_DATA_SIZE:
        problems.append(ParseDiagnostic("extended", "extended_data_size", f"Extended Data Size exceeds {MAX_EXTENDED_DATA_SIZE} bytes."))
    if ext.request_chunk:
        kind = ExtendedKind.REQUEST_CHUNK
        size = 0
        if not ext.chunked or ext.data_size or not 1 <= ext.chunk_number <= MAX_CHUNK_NUMBER:
            problems.append(ParseDiagnostic("extended", "invalid_chunk_request",
                                            f"Chunk Request requires Chunked, zero Data Size and chunk number 1–{MAX_CHUNK_NUMBER}."))
    elif ext.chunked:
        kind = ExtendedKind.CHUNK
        size = max(0, min(CHUNK_DATA_SIZE, ext.data_size - ext.chunk_number * CHUNK_DATA_SIZE))
        if ext.chunk_number > MAX_CHUNK_NUMBER or ext.chunk_number >= chunk_count(ext.data_size):
            problems.append(ParseDiagnostic("extended", "extended_chunk_number", "Chunk Number exceeds the range of this Data Size."))
    else:
        kind = ExtendedKind.UNCHUNKED
        size = ext.data_size
        if ext.chunk_number or header.num_data_objects or sop != SopKind.SOP:
            problems.append(ParseDiagnostic("extended", "invalid_unchunked_header", "Unchunked requires SOP, zero Chunk Number and zero Number of Data Objects."))

    data_end = EXTENDED_HEADER_SIZE + size
    wire_size = header.num_data_objects * _OBJECT_BYTES if ext.chunked else data_end
    expected_size = (data_end + _OBJECT_BYTES - 1) // _OBJECT_BYTES * _OBJECT_BYTES if ext.chunked else data_end
    if wire_size != expected_size:
        problems.append(ParseDiagnostic("extended", "extended_object_count", "Number of Data Objects disagrees with the chunk data and padding length."))
    data = raw_body[EXTENDED_HEADER_SIZE:data_end]
    padding = raw_body[data_end:] if ext.chunked else b""
    if any(padding):
        problems.append(ParseDiagnostic("extended", "extended_padding", "Chunk padding must contain only zero bytes."))
    if len(raw_body) > wire_size:
        problems.append(ParseDiagnostic("extended", "extended_length", "Capture has bytes beyond the declared Extended Message body."))
    if len(raw_body) < wire_size:
        problems.append(ParseDiagnostic("extended", "truncated_extended_data", "Capture ends before the declared Extended Message body."))
        status = ParseStatus.PARTIAL
    else:
        status = ParseStatus.INVALID if problems else ParseStatus.VALID
    return ExtendedMessageInfo(header.message_type, ext, kind, data, padding, raw_body, status, wire_size, tuple(problems))
