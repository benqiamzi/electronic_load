import json
from dataclasses import replace
from pathlib import Path
import unittest

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import (
    CaptureRecord,
    CaptureRecordParser,
    FirmwareEvent,
)
from electronic_load_gui.protocols.usb_pd import parse_capture
from electronic_load_gui.protocols.usb_pd.crc import calculate_crc32
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.header import decode_header
from electronic_load_gui.protocols.usb_pd.models import (
    FirmwareEventResult,
    PDMessageResult,
    ParseFailureResult,
    ResetResult,
)
from electronic_load_gui.protocols.usb_pd.sop import SopKind, classify_sop


FIXTURES = Path(__file__).with_name("fixtures")


def reference_crc32(data: bytes) -> int:
    """Compute the reference in MSB register order with LSB input bits."""
    register = 0xFFFFFFFF
    for byte in data:
        for bit in range(8):
            feedback = ((register >> 31) ^ (byte >> bit)) & 1
            register = (register << 1) & 0xFFFFFFFF
            if feedback:
                register ^= 0x04C11DB7
    return int(f"{register:032b}"[::-1], 2) ^ 0xFFFFFFFF


class RealCaptureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        index = json.loads((FIXTURES / "usb_pd_real.json").read_text(encoding="utf-8"))
        cls.captures = {}
        for sample in index["records"]:
            lines = (FIXTURES / sample["wire_file"]).read_text(encoding="ascii").splitlines()
            wire = bytes.fromhex(lines[sample["wire_line"] - 1])
            (payload,) = BinaryBlockParser().feed(wire)
            record = CaptureRecordParser.parse(payload, index["capture_cycle_ns"])
            cls.captures[sample["kind"]] = sample, record

    def test_real_fixture_index_matches_original_records(self) -> None:
        for sample, record in self.captures.values():
            self.assertEqual(sample["provenance"], "real")
            self.assertEqual(sample["payload_bytes"], len(record.raw_payload))
            if isinstance(record, FirmwareEvent):
                self.assertEqual(record.timestamp_us, sample["timestamp_us"])
                self.assertEqual(record.event_type, sample["event_type"])
            elif isinstance(record, CaptureRecord):
                self.assertEqual(record.start_timestamp_us, sample["start_timestamp_us"])
                self.assertEqual(record.end_timestamp_us, sample["end_timestamp_us"])
                self.assertEqual(record.sop_bytes.hex(), sample["sop_hex"])
                self.assertEqual(record.pulse_count, sample["pulse_count"])
            else:
                self.fail(f"Unexpected fixture type {type(record).__name__}")

    def test_reference_crc_matches_the_wire(self) -> None:
        sample, record = self.captures["source_capabilities"]
        raw = record.decoded_data
        self.assertEqual(raw, bytes.fromhex(sample["decoded_hex"]))
        self.assertEqual(reference_crc32(b"123456789"), 0xCBF43926)
        self.assertEqual(reference_crc32(raw[:-4]), int(sample["crc_hex"], 16))
        self.assertEqual(reference_crc32(raw[:-4]), int.from_bytes(raw[-4:], "little"))
        self.assertEqual(calculate_crc32(raw[:-4]), reference_crc32(raw[:-4]))
        parsed = parse_capture(record)
        self.assertEqual(parsed.crc_received, 0x34737FBF)
        self.assertEqual(parsed.crc_calculated, 0x34737FBF)
        self.assertIs(parsed.crc_valid, True)

    def test_synthetic_one_byte_damage_does_not_change_firmware_status(self) -> None:
        _, record = self.captures["source_capabilities"]
        damaged = bytearray(record.decoded_data)
        damaged[2] ^= 0x01
        parsed = parse_capture(replace(record, decoded_data=bytes(damaged)))
        self.assertEqual(parsed.firmware_decode_result, 0)
        self.assertEqual(parsed.body_status, ParseStatus.VALID)
        self.assertEqual(parsed.crc_received, 0x34737FBF)
        self.assertEqual(parsed.crc_calculated, reference_crc32(damaged[:-4]))
        self.assertIs(parsed.crc_valid, False)
        self.assertEqual(parsed.parse_status, ParseStatus.INVALID)

    def test_synthetic_failed_or_incomplete_capture_has_unavailable_crc(self) -> None:
        _, record = self.captures["source_capabilities"]
        for fixture in (
            replace(record, decode_result=2),
            replace(record, decode_result=3, decoded_data=record.decoded_data[:5]),
            replace(record, decoded_data=record.decoded_data[:-4]),
        ):
            with self.subTest(firmware_result=fixture.decode_result, length=fixture.data_length):
                parsed = parse_capture(fixture)
                self.assertEqual(parsed.firmware_decode_result, fixture.decode_result)
                self.assertEqual(parsed.raw_decoded_data, fixture.decoded_data)
                self.assertIsNone(parsed.crc_received)
                self.assertIsNone(parsed.crc_calculated)
                self.assertIsNone(parsed.crc_valid)
                self.assertEqual(parsed.parse_status, ParseStatus.PARTIAL)

    def test_parse_real_source_header_and_body(self) -> None:
        sample, record = self.captures["source_capabilities"]
        result = parse_capture(record)
        self.assertIsInstance(result, PDMessageResult)
        self.assertIs(result.record, record)
        self.assertEqual(result.sop.kind, SopKind.SOP)
        self.assertEqual(result.sop.matched_symbols, 4)
        header = result.header
        self.assertEqual(header.raw_bytes, b"\xa1\x77")
        self.assertEqual(header.raw_value, int(sample["header_hex"], 16))
        self.assertEqual(header.message_type, 1)
        self.assertEqual(header.spec_revision, 2)
        self.assertEqual(header.message_id, 3)
        self.assertEqual(header.num_data_objects, 7)
        self.assertEqual((header.power_role, header.data_role, header.cable_plug), (1, 1, None))
        self.assertFalse(header.extended)
        self.assertEqual(result.body, record.decoded_data[2:-4])
        self.assertEqual(result.parse_status, ParseStatus.VALID)

    def test_real_reset_and_event_have_separate_results(self) -> None:
        for key, expected in (("hard_reset", ResetResult), ("firmware_event", FirmwareEventResult)):
            with self.subTest(key=key):
                _, record = self.captures[key]
                result = parse_capture(record)
                self.assertIsInstance(result, expected)
                self.assertIs(result.record, record)

    def test_synthetic_short_header_and_length_mismatch_preserve_data(self) -> None:
        _, record = self.captures["source_capabilities"]
        for raw, status in (
            (b"\xa1", ParseStatus.PARTIAL),
            (record.decoded_data[:-1], ParseStatus.PARTIAL),
            (record.decoded_data + b"\x00", ParseStatus.INVALID),
        ):
            with self.subTest(length=len(raw)):
                truncated = replace(record, decoded_data=raw)
                result = parse_capture(truncated)
                self.assertEqual(result.parse_status, status)
                self.assertIs(result.record, truncated)
                self.assertEqual(result.record.decoded_data, raw)
        self.assertIsInstance(parse_capture(replace(record, decoded_data=b"\xa1")), ParseFailureResult)

    def test_synthetic_unknown_sop_does_not_guess_a_header(self) -> None:
        _, record = self.captures["source_capabilities"]
        unknown = replace(record, sop_bytes=b"\x00" * 4)
        result = parse_capture(unknown)
        self.assertIsInstance(result, ParseFailureResult)
        self.assertEqual(result.parse_status, ParseStatus.UNKNOWN)
        self.assertIs(result.record, unknown)


class HeaderAndSopTests(unittest.TestCase):
    def test_synthetic_alternate_ordered_sets(self) -> None:
        for text, expected in (
            ("18180606", SopKind.SOP_PRIME), ("18061806", SopKind.SOP_DOUBLE_PRIME),
            ("18191906", SopKind.SOP_PRIME_DEBUG), ("18190611", SopKind.SOP_DOUBLE_PRIME_DEBUG),
            ("07180706", SopKind.CABLE_RESET),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(classify_sop(bytes.fromhex(text)).kind, expected)

    def test_synthetic_sop_recovery_requires_a_unique_match(self) -> None:
        recovered = classify_sop(bytes.fromhex("181818ff"))
        self.assertEqual(recovered.kind, SopKind.SOP)
        self.assertEqual(recovered.matched_symbols, 3)
        ambiguous = classify_sop(bytes.fromhex("18181806"))
        self.assertEqual(ambiguous.kind, SopKind.UNKNOWN)
        self.assertGreater(len(ambiguous.candidates), 1)
        self.assertEqual(classify_sop(b"\x18").kind, SopKind.UNKNOWN)

    def test_synthetic_cable_header_bit_eight_and_reserved_fields(self) -> None:
        for plug in (0, 1):
            raw = (0x80 | (plug << 8)).to_bytes(2, "little")
            header, diagnostics = decode_header(raw, SopKind.SOP_DOUBLE_PRIME)
            self.assertIs(header.cable_plug, bool(plug))
            self.assertIsNone(header.power_role)
            self.assertIsNone(header.data_role)
            self.assertEqual(diagnostics, ())
        _, diagnostics = decode_header(b"\xe0\x00", SopKind.SOP_PRIME)
        self.assertEqual({item.code for item in diagnostics}, {"reserved_revision", "reserved_data_role"})

    def test_synthetic_header_id_and_object_count_are_independent(self) -> None:
        for message_id in range(8):
            for count in range(8):
                value = 0x80 | (message_id << 9) | (count << 12)
                header, diagnostics = decode_header(value.to_bytes(2, "little"), SopKind.SOP)
                self.assertEqual((header.message_id, header.num_data_objects), (message_id, count))
                self.assertEqual(diagnostics, ())
