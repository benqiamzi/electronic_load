import json
import unittest
from dataclasses import replace

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import CaptureRecord, CaptureRecordParser
from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.extended import CHUNK_DATA_SIZE, MAX_EXTENDED_DATA_SIZE
from electronic_load_gui.protocols.usb_pd.models import ExtendedKind, ReassemblyStatus

from test_usb_pd import FIXTURES, reference_crc32


def synthetic_extended(code, data=b"", *, chunk=None, total=None, request=False, sender=1, sop="18181811",
                       message_id=0, timestamp=0, extended_bits=0, object_count=None, padding=None):
    value = (len(data) if total is None else total) | extended_bits
    if chunk is not None:
        value |= 0x8000 | (chunk << 11)
    if request:
        value |= 0x400
    if padding is None:
        padding = bytes(-(2 + len(data)) % 4) if chunk is not None else b""
    body = value.to_bytes(2, "little") + data + padding
    count = (len(body) // 4 if chunk is not None else 0) if object_count is None else object_count
    pd_header = 0x8080 | (message_id << 9) | (sender << 8) | (count << 12) | code
    payload = pd_header.to_bytes(2, "little") + body
    raw = payload + reference_crc32(payload).to_bytes(4, "little")
    return CaptureRecord(timestamp, timestamp, 0, bytes.fromhex(sop), (), raw, b"", 10)


def parse_extended(*args, **kwargs):
    return parse_capture(synthetic_extended(*args, **kwargs))


class ExtendedFrameTests(unittest.TestCase):
    def test_synthetic_header_and_padding_vectors(self):
        index = json.loads((FIXTURES / "usb_pd_extended_synthetic.json").read_text(encoding="utf-8"))
        self.assertEqual(index["provenance"], "synthetic")
        minimum, maximum, first, request, last, _ = index["cases"]
        fields = (
            (minimum, parse_extended(1), 0, 0, ExtendedKind.UNCHUNKED),
            (maximum, parse_extended(1, bytes(MAX_EXTENDED_DATA_SIZE)), 0, MAX_EXTENDED_DATA_SIZE, ExtendedKind.UNCHUNKED),
            (first, parse_extended(9, bytes(range(26)), chunk=0, total=30), 0, 30, ExtendedKind.CHUNK),
            (request, parse_extended(9, chunk=1, request=True, sender=0), 1, 0, ExtendedKind.REQUEST_CHUNK),
            (last, parse_extended(9, bytes(range(26, 30)), chunk=1, total=30, message_id=1), 1, 30, ExtendedKind.CHUNK),
        )
        for sample, result, number, size, kind in fields:
            with self.subTest(sample=sample["kind"]):
                info = result.extended_message
                self.assertEqual(result.header.raw_bytes.hex(), sample["pd_header"])
                self.assertEqual(info.raw_body[:2].hex(), sample["extended_header"])
                self.assertEqual((info.header.chunk_number, info.header.data_size, info.kind), (number, size, kind))
                self.assertIs(result.crc_valid, True)
                self.assertEqual(info.status, ParseStatus.VALID)
                self.assertEqual(result.body, info.raw_body)
                self.assertEqual(result.data_objects, ())
                if "padding_hex" in sample:
                    self.assertEqual(info.padding.hex(), sample["padding_hex"])

    def test_synthetic_unchunked_minimum_odd_and_maximum_have_no_padding(self):
        for size in (0, 3, 27, MAX_EXTENDED_DATA_SIZE):
            with self.subTest(size=size):
                data = bytes(n % 256 for n in range(size))
                result = parse_extended(1, data)
                info = result.extended_message
                self.assertEqual(info.kind, ExtendedKind.UNCHUNKED)
                self.assertEqual(info.chunk_payload, data)
                self.assertEqual(info.padding, b"")
                self.assertEqual(result.parse_status, ParseStatus.UNSUPPORTED)
                self.assertTrue(result.crc_valid)
                assembled = ExtendedMessageReassembler().consume(result)
                self.assertEqual(assembled.status, ReassemblyStatus.COMPLETE)
                self.assertEqual(assembled.message.payload, data)

    def test_synthetic_body_and_crc_errors_preserve_capture(self):
        valid = synthetic_extended(2, b"abcd", chunk=0)
        for raw, expected, code in (
            (valid.decoded_data[:2], ParseStatus.PARTIAL, "short_extended_header"),
            (valid.decoded_data[:-3], ParseStatus.PARTIAL, "truncated_extended_data"),
            (valid.decoded_data + b"\x00", ParseStatus.INVALID, "extended_length"),
        ):
            with self.subTest(code=code):
                record = replace(valid, decoded_data=raw)
                result = parse_capture(record)
                self.assertIs(result.record, record)
                self.assertEqual(result.parse_status, expected)
                self.assertIsNone(result.crc_valid)
                self.assertIn(code, {issue.code for issue in result.diagnostics})
        bad = parse_capture(replace(valid, decoded_data=valid.decoded_data[:-1] + bytes((valid.decoded_data[-1] ^ 1,))))
        self.assertEqual(bad.extended_message.status, ParseStatus.VALID)
        self.assertFalse(bad.crc_valid)
        self.assertEqual(ExtendedMessageReassembler().consume(bad).status, ReassemblyStatus.INVALID)

    def test_synthetic_reserved_lengths_and_request_combinations(self):
        for options, code in (
            ({"extended_bits": 0x200}, "extended_reserved_bit"),
            ({"total": 261}, "extended_data_size"),
            ({"chunk": 10}, "extended_chunk_number"),
            ({"chunk": 1, "total": 26}, "extended_chunk_number"),
            ({"request": True}, "invalid_chunk_request"),
            ({"request": True, "chunk": 0}, "invalid_chunk_request"),
            ({"request": True, "chunk": 1, "total": 10}, "invalid_chunk_request"),
            ({"chunk": 0, "object_count": 2}, "extended_object_count"),
            ({"chunk": 0, "padding": b"\x01\x00"}, "extended_padding"),
            ({"object_count": 1}, "invalid_unchunked_header"),
            ({"sop": "18180606"}, "invalid_unchunked_header"),
        ):
            with self.subTest(options=options):
                result = parse_extended(2, **options)
                self.assertIn(code, {item.code for item in result.extended_message.diagnostics})
                self.assertNotEqual(result.extended_message.status, ParseStatus.VALID)
        last = parse_extended(2, bytes(CHUNK_DATA_SIZE), chunk=9, total=MAX_EXTENDED_DATA_SIZE)
        self.assertEqual(last.extended_message.status, ParseStatus.VALID)
        self.assertIs(last.crc_valid, True)

    def test_synthetic_unknown_type_keeps_extended_payload_and_bad_sop_is_invalid(self):
        unknown = parse_extended(31, b"reserved")
        self.assertEqual(unknown.message_type.status, ParseStatus.UNKNOWN)
        self.assertIn("unknown_extended_type", {issue.code for issue in unknown.diagnostics})
        self.assertEqual(ExtendedMessageReassembler().consume(unknown).message.payload, b"reserved")
        cable = parse_extended(17, b"\x00", chunk=0, sop="18180606")
        self.assertEqual(cable.message_type.status, ParseStatus.INVALID)
        self.assertEqual(ExtendedMessageReassembler().consume(cable).status, ReassemblyStatus.INVALID)


class RealExtendedReplayTests(unittest.TestCase):
    def test_real_extended_source_capabilities_status_and_manufacturer_query(self):
        index = json.loads((FIXTURES / "usb_pd_extended_real.json").read_text(encoding="utf-8"))
        self.assertEqual(index["provenance"], "real")
        expected = {"Source_Capabilities_Extended": (25, 1, 0x253923B7), "Status": (7, 3, 0x29C8CF7B),
                    "Get_Manufacturer_Info": (2, 0, 0xE311A27D)}
        seen = set()
        reassembler = ExtendedMessageReassembler()
        for sample in index["records"]:
            with self.subTest(sample=sample["message_type"]):
                self.assertEqual(sample["provenance"], "real")
                (block,) = BinaryBlockParser().feed(bytes.fromhex(sample["wire_hex"]))
                record = CaptureRecordParser.parse(block, index["capture_cycle_ns"])
                self.assertEqual(record.raw_payload, block)
                self.assertEqual(len(block), sample["payload_bytes"])
                self.assertEqual(record.pulse_count, sample["pulse_count"])
                self.assertEqual(record.start_timestamp_us, sample["start_timestamp_us"])
                self.assertEqual(record.end_timestamp_us, sample["end_timestamp_us"])
                self.assertEqual(record.decoded_data.hex(), sample["decoded_hex"])
                result = parse_capture(record)
                name = result.message_type.name
                self.assertEqual(name, sample["message_type"])
                size, padding, crc = expected[name]
                seen.add(name)
                self.assertEqual(result.crc_received, crc)
                self.assertEqual(reference_crc32(record.decoded_data[:-4]), crc)
                self.assertTrue(result.crc_valid)
                info = result.extended_message
                self.assertEqual((info.kind, info.header.chunk_number), (ExtendedKind.CHUNK, 0))
                self.assertEqual(info.header.data_size, size)
                self.assertEqual(info.padding, bytes(padding))
                complete = reassembler.consume(result)
                self.assertEqual(complete.status, ReassemblyStatus.COMPLETE)
                self.assertEqual(complete.message.payload, bytes.fromhex(sample["data_hex"]))
                self.assertIs(complete.message.frames[0].record, record)
        self.assertEqual(seen, set(expected))
