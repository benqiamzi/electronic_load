import json
import unittest
from dataclasses import replace

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import CaptureRecordParser
from electronic_load_gui.protocols.usb_pd import PDSessionContext, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import SupplyType
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from test_usb_pd import FIXTURES, reference_crc32, synthetic_message


def synthetic_capabilities(*words: int, sop: str = "18181811", source: bool = True):
    message = 0x181 if source else 0x084
    return parse_capture(synthetic_message((len(words) << 12) | message, words, sop=sop))


def synthetic_request(position: int = 1, units: int = 100, *, sop: str = "18181811"):
    raw = (position << 28) | (units << 10) | units
    return parse_capture(synthetic_message(0x1082, (raw,), sop=sop))


def synthetic_reset(sop: str, *, decode_result: int = 0):
    record = synthetic_message(0, sop=sop)
    return parse_capture(replace(record, decoded_data=b"", decode_result=decode_result))


class PDSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.session = PDSessionContext()
        self.source = synthetic_capabilities((100 << 10) | 300, (180 << 10) | 200)

    def test_synthetic_replace_snapshot_and_resolve_object_positions(self) -> None:
        self.session.consume(self.source)
        request = synthetic_request(2, 150)
        analysis = self.session.consume(request)
        self.assertIs(analysis.result, request)
        self.assertIs(analysis.rdo.selected_pdo, self.source.pdos[1])
        self.assertEqual(analysis.rdo.status, ParseStatus.VALID)
        self.assertEqual(request.rdo.status, ParseStatus.CONTEXT_MISSING)

        newer = synthetic_capabilities((100 << 10) | 100)
        self.session.consume(newer)
        self.assertIs(self.session.source_pdos(), newer.pdos)
        missing = self.session.consume(request).rdo
        self.assertEqual(missing.status, ParseStatus.INVALID)
        self.assertEqual(missing.raw, request.data_objects[0])
        self.assertEqual({d.code for d in missing.diagnostics}, {"position_not_advertised"})
        too_high = self.session.consume(synthetic_request(1, 101)).rdo
        self.assertEqual(too_high.status, ParseStatus.INVALID)
        self.assertIs(too_high.selected_pdo, newer.pdos[0])

    def test_synthetic_missing_context_and_non_pdo_messages(self) -> None:
        request = synthetic_request()
        self.assertIs(self.session.consume(request).rdo, request.rdo)
        self.session.consume(synthetic_capabilities((100 << 10) | 100, source=False))
        for message in (0x83, 0x86):  # Accept and PS_RDY.
            result = parse_capture(synthetic_message(message))
            self.assertIsNone(self.session.consume(result).rdo)
        self.assertEqual(self.session.consume(request).rdo.status, ParseStatus.CONTEXT_MISSING)

    def test_synthetic_cable_packets_cannot_populate_or_use_port_capabilities(self) -> None:
        self.session.consume(self.source)
        for pattern, sop in (("18180606", SopKind.SOP_PRIME), ("18061806", SopKind.SOP_DOUBLE_PRIME)):
            with self.subTest(sop=sop):
                cable = synthetic_capabilities((100 << 10) | 70, sop=pattern)
                self.assertEqual(cable.message_type.status, ParseStatus.INVALID)
                self.session.consume(cable)
                self.assertEqual(self.session.source_pdos(sop), ())
                self.assertIsNone(self.session.consume(synthetic_request(sop=pattern)).rdo)
        self.assertIs(self.session.consume(synthetic_request()).rdo.selected_pdo, self.source.pdos[0])

    def test_synthetic_invalid_frames_cannot_update_state_or_resolve(self) -> None:
        self.session.consume(self.source)
        request = synthetic_request()
        for parsed in (synthetic_capabilities((100 << 10) | 20), request, parse_capture(synthetic_message(0x8D))):
            with self.subTest(message=parsed.message_type.name):
                raw = parsed.raw_decoded_data
                for record in (replace(parsed.record, decode_result=2),
                               replace(parsed.record, decoded_data=raw[:-1] + bytes((raw[-1] ^ 1,)))):
                    invalid = parse_capture(record)
                    self.assertIsNone(self.session.consume(invalid).rdo)
                    self.assertIs(self.session.source_pdos(), self.source.pdos)
        malformed = parse_capture(synthetic_message(0x2082, (1, 2)))
        self.assertIsNone(self.session.consume(malformed).rdo)
        self.assertIs(self.session.source_pdos(), self.source.pdos)

    def test_synthetic_semantic_diagnostics_do_not_shift_pdo_positions(self) -> None:
        source = synthetic_capabilities((100 << 10) | 300, 0xF1234567, (180 << 10) | 200)
        self.session.consume(source)
        self.assertIs(self.session.consume(synthetic_request(3)).rdo.selected_pdo, source.pdos[2])
        self.assertEqual(self.session.consume(synthetic_request(2)).rdo.status, ParseStatus.UNSUPPORTED)
        bad = synthetic_capabilities((100 << 10) | 300, (1 << 29) | (180 << 10) | 200)
        self.session.consume(bad)
        analysis = self.session.consume(synthetic_request(2))
        self.assertEqual(analysis.rdo.status, ParseStatus.INVALID)
        self.assertIs(analysis.rdo.selected_pdo, bad.pdos[1])
        self.assertEqual({d.code for d in analysis.rdo.diagnostics}, {"invalid_pdo"})

    def test_synthetic_soft_reset_clears_only_its_address(self) -> None:
        self.session.consume(self.source)
        for pattern in ("18180606", "18061806"):
            self.session.consume(parse_capture(synthetic_message(0x8D, sop=pattern)))
            self.assertIs(self.session.source_pdos(), self.source.pdos)
        self.session.consume(parse_capture(synthetic_message(0x8D)))
        self.assertEqual(self.session.consume(synthetic_request()).rdo.status, ParseStatus.CONTEXT_MISSING)

    def test_synthetic_hard_reset_clears_the_session_and_cable_reset_preserves_port(self) -> None:
        self.session.consume(self.source)
        for reset in (synthetic_reset("07180706"), synthetic_reset("07070719", decode_result=3)):
            self.session.consume(reset)
            self.assertIs(self.session.source_pdos(), self.source.pdos)
        self.session.consume(synthetic_reset("07070719"))
        self.assertEqual(self.session.consume(synthetic_request()).rdo.status, ParseStatus.CONTEXT_MISSING)

    def test_synthetic_disconnect_clears_each_independent_context(self) -> None:
        self.session.consume(self.source)
        other = PDSessionContext()
        self.assertEqual(other.consume(synthetic_request()).rdo.status, ParseStatus.CONTEXT_MISSING)
        self.session.disconnect()
        self.session.disconnect()
        self.assertEqual(self.session.source_pdos(), ())
        self.assertEqual(self.session.consume(synthetic_request()).rdo.status, ParseStatus.CONTEXT_MISSING)


class RealNegotiationReplayTests(unittest.TestCase):
    def test_real_source_capabilities_and_request_replay(self) -> None:
        source_index = json.loads((FIXTURES / "usb_pd_real.json").read_text(encoding="utf-8"))
        source = next(record for record in source_index["records"] if record["kind"] == "source_capabilities")
        lines = (FIXTURES / source["wire_file"]).read_text(encoding="ascii").splitlines()
        (payload,) = BinaryBlockParser().feed(bytes.fromhex(lines[source["wire_line"] - 1]))
        source_record = CaptureRecordParser.parse(payload, source_index["capture_cycle_ns"])
        caps = parse_capture(source_record)
        expected = (
            (0x0A01912C, SupplyType.FIXED, 5000, 5000, 3000),
            (0x0002D12C, SupplyType.FIXED, 9000, 9000, 3000),
            (0x0003C12C, SupplyType.FIXED, 12000, 12000, 3000),
            (0x0004B12C, SupplyType.FIXED, 15000, 15000, 3000),
            (0x000641F4, SupplyType.FIXED, 20000, 20000, 5000),
            (0xC8DC3264, SupplyType.PPS, 5000, 11000, 5000),
            (0xC9903264, SupplyType.PPS, 5000, 20000, 5000),
        )
        self.assertIs(caps.crc_valid, True)
        self.assertEqual(len(caps.pdos), 7)
        self.assertEqual(caps.data_objects, tuple(row[0] for row in expected))
        for index, (pdo, row) in enumerate(zip(caps.pdos, expected, strict=True), 1):
            with self.subTest(index=index):
                self.assertEqual(pdo.index, index)
                self.assertEqual(pdo.status, ParseStatus.VALID)
                self.assertEqual((pdo.raw, pdo.supply_type, pdo.voltage_min_mv, pdo.voltage_max_mv, pdo.current_max_ma), row)
                self.assertIs(pdo.pps_power_limited, True if index > 5 else None)

        sample = json.loads((FIXTURES / "usb_pd_request_real.json").read_text(encoding="utf-8"))
        (payload,) = BinaryBlockParser().feed(bytes.fromhex(sample["wire_hex"]))
        record = CaptureRecordParser.parse(payload, sample["capture_cycle_ns"])
        request = parse_capture(record)
        self.assertEqual(sample["provenance"], "real")
        self.assertEqual(sample["source_capabilities_start_timestamp_us"], source_record.start_timestamp_us)
        self.assertEqual((record.start_timestamp_us, record.end_timestamp_us),
                         (sample["start_timestamp_us"], sample["end_timestamp_us"]))
        self.assertLess(source_record.end_timestamp_us, record.start_timestamp_us)
        self.assertEqual(record.pulse_count, sample["pulse_count"])
        self.assertEqual(len(record.raw_payload), sample["payload_bytes"])
        self.assertEqual(record.decoded_data.hex(), sample["decoded_hex"])
        self.assertEqual(request.header.raw_value, 0x1482)
        self.assertEqual(request.crc_received, 0xA7070B60)
        self.assertEqual(reference_crc32(record.decoded_data[:-4]), request.crc_received)
        self.assertIs(request.crc_valid, True)
        self.assertEqual(request.data_objects, (0x1144B12C,))
        self.assertEqual(request.rdo.status, ParseStatus.CONTEXT_MISSING)

        session = PDSessionContext()
        session.consume(caps)
        analysis = session.consume(request)
        self.assertIs(analysis.result.record, record)
        self.assertEqual(analysis.rdo.status, ParseStatus.VALID)
        self.assertEqual((analysis.rdo.raw, analysis.rdo.object_position), (0x1144B12C, 1))
        self.assertIs(analysis.rdo.selected_pdo, caps.pdos[0])
        self.assertEqual(analysis.rdo.selected_pdo.voltage_max_mv, 5000)
        self.assertEqual((analysis.rdo.operating_current_ma, analysis.rdo.maximum_operating_current_ma), (3000, 3000))
        self.assertIsNone(analysis.rdo.operating_voltage_mv)
