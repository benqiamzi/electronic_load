import json
import unittest
from dataclasses import replace

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import CaptureRecordParser
from electronic_load_gui.protocols.usb_pd import VDMContext, decode_vdm, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import VDMCommandType, VDMType
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from test_usb_pd import FIXTURES, reference_crc32, synthetic_message


def synthetic_vdm_record(*words, sop="18181811", data_role=0, cable_plug=None, message_id=0, revision=2):
    header = (len(words) << 12) | (message_id << 9) | (revision << 6) | (data_role << 5) | 0x0F
    if sop in ("18180606", "18061806"):
        if cable_plug is None:
            cable_plug = bool(words[0] & 0xC0)
        header |= int(cable_plug) << 8
    return synthetic_message(header, words, sop=sop)


def synthetic_vdm_fixture(kind):
    index = json.loads((FIXTURES / "usb_pd_vdm_synthetic.json").read_text(encoding="ascii"))
    sample = next(item for item in index["records"] if item["kind"] == kind)
    if index["provenance"] != "synthetic" or sample["provenance"] != "synthetic":
        raise ValueError("Expected a synthetic fixture.")
    words = tuple(int(word, 16) for word in sample["words_hex"])
    return synthetic_vdm_record(*words, sop=sample["sop_hex"])


class VDMTests(unittest.TestCase):
    def test_synthetic_structured_header_at_the_capture_entry_point(self):
        record = synthetic_vdm_record(0xFF01AA04, 0x12345678, data_role=1)
        result = parse_capture(record)
        self.assertIs(result.record, record)
        self.assertTrue(result.crc_valid)
        self.assertEqual(result.body.hex(), "04aa01ff78563412")
        self.assertEqual(result.data_objects, (0xFF01AA04, 0x12345678))
        vdm = result.vdm
        self.assertEqual((vdm.raw_header, vdm.svid, vdm.vdm_type), (0xFF01AA04, 0xFF01, VDMType.STRUCTURED))
        self.assertEqual((vdm.version_major, vdm.version_minor, vdm.structured_version), (1, 1, (2, 1)))
        self.assertEqual((vdm.object_position, vdm.command_type, vdm.command), (2, VDMCommandType.INITIATOR, 4))
        self.assertEqual(vdm.command_name, "Enter Mode")
        self.assertEqual(vdm.vdos[0].raw, 0x12345678)
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(vdm.reserved_bits, 0)

    def test_synthetic_unstructured_does_not_apply_structured_fields_or_reserved_mask(self):
        vdm = parse_capture(synthetic_vdm_fixture("unstructured")).vdm
        self.assertEqual((vdm.vdm_type, vdm.svid, vdm.vendor_header_bits), (VDMType.UNSTRUCTURED, 0x1209, 0x567E))
        for field in ("version_major", "version_minor", "structured_version", "object_position",
                      "command_type", "command", "command_name"):
            self.assertIsNone(getattr(vdm, field))
        self.assertEqual(vdm.reserved_bits, 0)
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(vdm.vdos[0].raw, 0x89ABCDEF)
        self.assertEqual(vdm.vdos[0].category, "unstructured_vendor")

    def test_synthetic_wire_versions_and_reserved_codes(self):
        for value, revision, expected, status in (
            (0x8001, 1, (1, 0), ParseStatus.VALID), (0x8001, 2, (1, 0), ParseStatus.VALID),
            (0xA001, 2, (2, 0), ParseStatus.VALID), (0xA801, 2, (2, 1), ParseStatus.VALID),
            (0xA001, 1, (2, 0), ParseStatus.INVALID), (0x9001, 2, None, ParseStatus.INVALID),
            (0xC001, 2, None, ParseStatus.INVALID), (0xB001, 2, None, ParseStatus.INVALID),
        ):
            with self.subTest(value=value, revision=revision):
                vdm = decode_vdm((0xFF000000 | value,), revision=revision)
                self.assertEqual((vdm.structured_version, vdm.status), (expected, status))

    def test_synthetic_commands_and_response_types(self):
        for cmd, name in enumerate(("Discover Identity", "Discover SVIDs", "Discover Modes", "Enter Mode",
                                    "Exit Mode", "Attention"), 1):
            position = 1 if cmd >= 4 else 0
            for command_type in VDMCommandType:
                with self.subTest(command=cmd, command_type=command_type):
                    # ACK payload for each discovery command is exercised in test_vdo.
                    vdm = decode_vdm((0xFF00A800 | (position << 8) | (command_type << 6) | cmd,))
                    self.assertEqual((vdm.command, vdm.command_name, vdm.command_type), (cmd, name, command_type))
                    forbidden = cmd == 6 and command_type != VDMCommandType.INITIATOR or (
                        cmd in (4, 5) and command_type == VDMCommandType.BUSY)
                    self.assertEqual("vdm_command_type" in {d.code for d in vdm.diagnostics}, forbidden)

    def test_synthetic_object_position_role_and_sop_rules(self):
        for command, position in ((1, 1), (3, 7), (4, 0), (4, 7), (5, 0), (6, 0), (6, 7)):
            with self.subTest(command=command, position=position):
                vdm = decode_vdm((0xFF00A800 | (position << 8) | command,))
                self.assertEqual(vdm.object_position, position)
                self.assertIn("vdm_invalid_object_position", {d.code for d in vdm.diagnostics})
        exit_all = decode_vdm((0xFF01AF05,), sop=SopKind.SOP_DOUBLE_PRIME)
        self.assertEqual((exit_all.object_position, exit_all.status), (7, ParseStatus.VALID))
        cable = decode_vdm((0xFF00A801,), sop=SopKind.SOP_PRIME)
        self.assertEqual(cable.status, ParseStatus.VALID)
        double_prime = decode_vdm((0xFF00A801,), sop=SopKind.SOP_DOUBLE_PRIME)
        self.assertIn("vdm_command_sop", {d.code for d in double_prime.diagnostics})
        wrong_cable = parse_capture(synthetic_vdm_record(0xFF00A882, sop="18180606", cable_plug=False))
        self.assertIn("vdm_cable_sender", {d.code for d in wrong_cable.vdm.diagnostics})
        wrong_role = parse_capture(synthetic_vdm_record(0xFF01A904, data_role=0))
        self.assertIn("vdm_data_role", {d.code for d in wrong_role.vdm.diagnostics})
        wrong_sid = decode_vdm((0x1209A801,))
        self.assertIn("vdm_invalid_svid", {d.code for d in wrong_sid.diagnostics})
        self.assertEqual(decode_vdm((0x0000A803,)).status, ParseStatus.INVALID)

    def test_synthetic_invalid_headers_keep_raw_fields_and_words(self):
        vdm = decode_vdm(())
        self.assertEqual(vdm.status, ParseStatus.PARTIAL)
        self.assertEqual({d.code for d in vdm.diagnostics}, {"vdm_missing_header"})
        for header, status, codes in (
            (0xFF00A820, ParseStatus.INVALID, {"vdm_unknown_command", "vdm_reserved_bits_nonzero"}),
            (0xFF00A80F, ParseStatus.INVALID, {"vdm_unknown_command"}),
            (0x1209BD19, ParseStatus.UNSUPPORTED,
             {"vdm_unknown_command", "vdm_unknown_svid", "vdo_decoder_unavailable"}),
        ):
            with self.subTest(header=header):
                vdm = decode_vdm((header, 0xFFFFFFFF))
                self.assertEqual((vdm.raw_header, vdm.status, vdm.vdos[0].raw), (header, status, 0xFFFFFFFF))
                self.assertEqual(vdm.command, header & 0x1F)
                self.assertEqual({d.code for d in vdm.diagnostics}, codes)
        oversized = decode_vdm((0x12090001,) + (0,) * 7)
        self.assertEqual((oversized.status, len(oversized.vdos)), (ParseStatus.INVALID, 7))

    def test_synthetic_transport_status_and_semantic_status_are_independent(self):
        record = synthetic_vdm_record(0xFF00A843)
        result = parse_capture(record)
        self.assertEqual(result.vdm.status, ParseStatus.INVALID)
        self.assertEqual(result.parse_status, ParseStatus.VALID)
        self.assertIs(result.crc_valid, True)
        crc_bad = parse_capture(replace(record, decoded_data=record.decoded_data[:-1] +
                                        bytes([record.decoded_data[-1] ^ 1])))
        self.assertIs(crc_bad.crc_valid, False)
        self.assertEqual(crc_bad.data_objects, result.data_objects)
        self.assertIsNone(crc_bad.vdm)
        cut = parse_capture(replace(record, decoded_data=record.decoded_data[:-1]))
        self.assertEqual(cut.parse_status, ParseStatus.PARTIAL)
        self.assertIn("message_length", {d.code for d in cut.diagnostics})
        self.assertIsNone(parse_capture(synthetic_message(0x0083)).vdm)


class RealVDMReplayTests(unittest.TestCase):
    def test_real_discover_identity_request_and_incomplete_ack(self):
        index = json.loads((FIXTURES / "usb_pd_vdm_real.json").read_text(encoding="ascii"))
        self.assertEqual(index["provenance"], "real")
        parsed = {}
        for row in index["records"]:
            with self.subTest(kind=row["kind"]):
                self.assertEqual(row["provenance"], "real")
                (payload,) = BinaryBlockParser().feed(bytes.fromhex(row["wire_hex"]))
                record = CaptureRecordParser.parse(payload, index["capture_cycle_ns"])
                self.assertEqual(record.raw_payload, payload)
                self.assertEqual(len(payload), row["payload_bytes"])
                self.assertEqual(record.pulse_count, row["pulse_count"])
                self.assertEqual(record.sop_bytes.hex(), row["sop_hex"])
                self.assertEqual((record.start_timestamp_us, record.end_timestamp_us),
                                 (row["start_timestamp_us"], row["end_timestamp_us"]))
                self.assertEqual(record.decoded_data.hex(), row["decoded_hex"])
                result = parse_capture(record)
                self.assertIs(result.record, record)
                self.assertEqual(result.sop.kind, SopKind.SOP)
                self.assertIs(result.crc_valid, True)
                self.assertEqual(result.crc_received, reference_crc32(record.decoded_data[:-4]))
                self.assertEqual(result.vdm.command_name, "Discover Identity")
                parsed[row["kind"]] = result
        request = parsed["discover_identity_request"]
        ack = parsed["discover_identity_ack"]
        self.assertLess(request.record.end_timestamp_us, ack.record.start_timestamp_us)
        self.assertEqual((request.crc_received, ack.crc_received), (0x06D1477C, 0x926D121C))
        self.assertEqual((request.vdm.raw_header, request.vdm.structured_version), (0xFF00A801, (2, 1)))
        self.assertEqual(request.vdm.command_type, VDMCommandType.INITIATOR)
        self.assertEqual((ack.vdm.raw_header, ack.vdm.structured_version), (0xFF00A041, (2, 0)))
        self.assertEqual(ack.vdm.command_type, VDMCommandType.ACK)
        self.assertEqual(ack.data_objects, (0xFF00A041, 0x05C02B01, 0x00000000, 0x0000A819))
        id_header, cert_stat, product = ack.vdm.vdos
        self.assertEqual(id_header.decoded_fields["usb_vid"], 0x2B01)
        self.assertEqual(id_header.decoded_fields["product_type_dfp"], 3)
        self.assertEqual(cert_stat.decoded_fields["xid"], 0)
        self.assertEqual(dict(product.decoded_fields), {"usb_pid": 0, "bcd_device": 0xA819})
        self.assertEqual(ack.vdm.status, ParseStatus.PARTIAL)
        self.assertEqual({d.code for d in ack.vdm.diagnostics}, {"vdo_truncated"})
        context = VDMContext()
        context.consume(request)
        self.assertEqual(context.consume(ack).status, ParseStatus.PARTIAL)
        self.assertIsNone(context.identity(responder_role=1))
