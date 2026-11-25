from pathlib import Path
from struct import pack
import unittest

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import (
    CaptureRecord,
    CaptureRecordError,
    CaptureRecordParser,
    DecodeResult,
    FirmwareEvent,
)


def capture_payload(start, end, result, sop, pulses, data):
    return (pack("<QQI4sI", start, end, result, sop, len(pulses))
            + pack(f"<{len(pulses)}H", *pulses) + pack("<I", len(data)) + data)


class CaptureRecordTests(unittest.TestCase):
    def test_hardware_cdc_blocks_with_internal_line_endings(self) -> None:
        fixture = Path(__file__).with_name("fixtures") / "drpd_cdc_blocks.hex"
        wire_frames = [bytes.fromhex(line) for line in fixture.read_text(encoding="ascii").splitlines()]
        parser = BinaryBlockParser()
        records = []
        for frame in wire_frames:
            self.assertEqual(frame[-1:], b"\n")
            for offset in range(0, len(frame), 3):
                records.extend(parser.feed(frame[offset:offset + 3]))
        self.assertFalse(parser.has_pending_data)
        self.assertEqual(records, [frame[2 + int(chr(frame[1])):-1] for frame in wire_frames])
        self.assertTrue(all(value in b"".join(records) for value in (0, 10, 13)))
        event, reset, source = (CaptureRecordParser.parse(record, 10.0) for record in records)
        self.assertEqual(event.timestamp_us, 59755786)
        self.assertEqual(event.event_type, 9)
        self.assertIn("Source_Capabilities", event.event_text)
        self.assertTrue(reset.is_hard_reset)
        self.assertEqual((reset.start_timestamp_us, reset.end_timestamp_us), (154340668, 154340945))
        self.assertEqual(reset.pulse_count, 128)
        self.assertEqual(reset.pulse_widths[:4], (332, 164, 164, 332))
        self.assertEqual(source.sop_bytes, bytes.fromhex("18181811"))
        self.assertEqual((source.start_timestamp_us, source.end_timestamp_us), (32788569, 32789980))
        self.assertEqual(source.pulse_count, 681)
        self.assertEqual(source.data_length, 34)
        self.assertEqual(source.decoded_data, bytes.fromhex(
            "a1772c91010a2cd102002cc103002cb10400f44106006432dcc8643290c9bf7f7334"
        ))

    def test_documented_source_capabilities(self) -> None:
        # SOP, pulse count and message bytes from the MDY-12-EF capture report.
        # Its actual pulse values and timestamps were omitted from that report.
        start = 0x0102030405060708
        end = 0x0102030405060809
        sop = bytes.fromhex("18 18 18 11")
        pulses = tuple(range(483))
        data = bytes.fromhex("a1412c91010a2cd102002cb104004541060009fa4aea")
        payload = capture_payload(start, end, 0, sop, pulses, data)
        self.assertEqual(len(payload), 1020)
        record = CaptureRecordParser.parse(payload, 5.25)
        self.assertIsInstance(record, CaptureRecord)
        self.assertEqual((record.start_timestamp_us, record.end_timestamp_us), (start, end))
        self.assertEqual(record.decode_result, DecodeResult.SUCCESS)
        self.assertEqual(record.sop_bytes, sop)
        self.assertEqual(record.pulse_count, 483)
        self.assertEqual(record.pulse_widths, pulses)
        self.assertEqual(record.pulse_widths_ns, tuple(width * 5.25 for width in pulses))
        self.assertEqual(record.data_length, 22)
        self.assertEqual(record.decoded_data, data)
        self.assertEqual(record.raw_payload, payload)

    def test_hard_reset_and_failure_payloads(self) -> None:
        sop = bytes.fromhex("07 07 07 19")
        reset = capture_payload(55, 80, 0, sop, (0x100, 0xFFFF), b"")
        self.assertTrue(CaptureRecordParser.parse(reset, 10).is_hard_reset)
        for result in (1, 2, 3, 4, 5, 0xCAFEBABE):
            with self.subTest(result=result):
                payload = capture_payload(55, 80, result, sop, (0xFFFF,), b"\x0a\x0d\x00")
                record = CaptureRecordParser.parse(payload, 10)
                self.assertEqual(record.decode_result, result)
                self.assertEqual(record.decoded_data, b"\x0a\x0d\x00")
                self.assertFalse(record.is_hard_reset)

    def test_firmware_event_utf8_and_raw_invalid_text(self) -> None:
        for text_bytes, expected, valid in (("连接".encode(), "连接", True), (b"a\xff", "a\ufffd", False)):
            with self.subTest(valid=valid):
                payload = capture_payload(123, 123, 0xFFFFFFFF, bytes(4), (),
                                          pack("<I", 0x11223344) + text_bytes)
                event = CaptureRecordParser.parse(payload, 10)
                self.assertEqual(event, FirmwareEvent(123, 0x11223344, expected, text_bytes,
                                                      payload, valid))

    def test_checks_all_boundaries_before_unpacking(self) -> None:
        record = capture_payload(0, 2, 0, bytes(4), (108,), b"ABC")
        event_missing_number = capture_payload(1, 1, 0xFFFFFFFF, bytes(4), (), b"ABC")
        event_invalid_fields = capture_payload(0, 1, 0xFFFFFFFF, bytes(4), (), bytes(4))
        for payload in (
            record[:31], record[:24] + b"\xff" * 4 + record[28:], record[:-1], record + b"\x00",
            event_missing_number, event_invalid_fields,
        ):
            with self.subTest(payload=payload.hex()):
                with self.assertRaises(CaptureRecordError):
                    CaptureRecordParser.parse(payload, 10)
