import json
from pathlib import Path
import unittest

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import (
    CaptureRecord,
    CaptureRecordParser,
    FirmwareEvent,
)


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
