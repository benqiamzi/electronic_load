import json
import unittest

from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, PDSessionContext, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus, SupplyType

from test_extended import parse_extended
from test_pd_session import synthetic_capabilities, synthetic_reset
from test_reassembly import synthetic_chunk
from test_usb_pd import FIXTURES, synthetic_message


def synthetic_epr_profile():
    index = json.loads((FIXTURES / "usb_pd_extended_synthetic.json").read_text(encoding="utf-8"))
    assert index["provenance"] == "synthetic"
    return next(item for item in index["cases"] if item["kind"] == "epr_capabilities")


def synthetic_epr_payload(words):
    return b"".join(word.to_bytes(4, "little") for word in words)


def synthetic_epr_request(rdo, pdo, *, transmitter=0):
    return parse_capture(synthetic_message(0x2089 | (transmitter << 8), (rdo, pdo)))


class EPRTests(unittest.TestCase):
    def setUp(self):
        self.sample = synthetic_epr_profile()
        self.words = tuple(int(word, 16) for word in self.sample["pdo_hex"])
        self.payload = synthetic_epr_payload(self.words)
        self.engine = ExtendedMessageReassembler()
        self.session = PDSessionContext()

    def _complete(self, words=None, *, sender=1):
        payload = self.payload if words is None else synthetic_epr_payload(words)
        return self.engine.consume(parse_extended(17, payload, sender=sender))

    def test_synthetic_chunked_capabilities_and_progress(self):
        first = self.engine.consume(synthetic_chunk(self.payload, 0, code=17))
        self.assertEqual(first.result.message_type.name, "EPR_Source_Capabilities")
        self.assertEqual(first.epr.status, ParseStatus.PARTIAL)
        self.assertEqual(first.epr.raw_objects, self.words[:6])
        self.session.consume_extended(first)
        self.assertIsNone(self.session.epr_source_capabilities())
        final = self.engine.consume(synthetic_chunk(self.payload, 1, code=17, message_id=1))
        self.assertEqual((final.status, final.epr.status), (ReassemblyStatus.COMPLETE, ParseStatus.VALID))
        self.assertEqual(final.epr.raw_objects, self.words)
        self.assertEqual(final.epr.spr_slots[3:], (None,) * 4)
        fixed, avs = final.epr.epr_pdos
        self.assertEqual((fixed.index, fixed.supply_type, fixed.voltage_max_mv, fixed.current_max_ma),
                         (8, SupplyType.FIXED, 28000, 3000))
        self.assertEqual((avs.index, avs.supply_type, avs.voltage_min_mv, avs.voltage_max_mv, avs.pdp_mw),
                         (9, SupplyType.EPR_AVS, 15000, 28000, 120000))
        self.session.consume_extended(final)
        self.assertIs(self.session.epr_source_capabilities(), final.epr)

    def test_synthetic_epr_request_echo_and_dynamic_current_ceiling(self):
        raw = int(self.sample["epr_rdo_hex"], 16)
        echo = int(self.sample["echo_pdo_hex"], 16)
        request = synthetic_epr_request(raw, echo)
        self.assertEqual(request.data_objects, (raw, echo))
        self.assertIs(request.crc_valid, True)
        self.assertEqual(self.session.consume(request).rdo.status, ParseStatus.CONTEXT_MISSING)
        self.assertIsNone(request.rdo.operating_voltage_mv)
        self.session.consume_extended(self._complete())
        rdo = self.session.consume(request).rdo
        self.assertEqual((rdo.status, rdo.selected_pdo.index, rdo.pdo_echo), (ParseStatus.VALID, 9, echo))
        self.assertEqual((rdo.operating_voltage_mv, rdo.operating_current_ma), (28000, 4250))
        fixed_request = (8 << 28) | (1 << 22) | (250 << 10) | 250
        fixed = self.session.consume(synthetic_epr_request(fixed_request, self.words[7])).rdo
        self.assertEqual((fixed.status, fixed.selected_pdo.index, fixed.operating_current_ma), (ParseStatus.VALID, 8, 2500))
        self.assertEqual(fixed.selected_pdo.voltage_max_mv, 28000)
        for word, code in ((raw + 1, "operating_limit"),
                           ((raw & ~(0xFFF << 9)) | (1200 << 9), "voltage_range"),
                           (raw - (1 << 9), "avs_voltage_step")):
            with self.subTest(code=code):
                result = synthetic_epr_request(word, echo)
                decoded = self.session.consume(result).rdo
                self.assertEqual(decoded.status, ParseStatus.INVALID)
                self.assertIn(code, {issue.code for issue in decoded.diagnostics})
        mismatch = self.session.consume(synthetic_epr_request(raw, echo ^ 1)).rdo
        self.assertEqual(mismatch.diagnostics[0].code, "epr_pdo_echo_mismatch")
        self.assertIsNone(mismatch.operating_current_ma)
        other_sender = self.session.consume(synthetic_epr_request(raw, echo, transmitter=1)).rdo
        self.assertEqual(other_sender.diagnostics[-1].code, "epr_request_sender")

    def test_synthetic_spr_and_epr_contexts_and_spr_avs_ranges(self):
        fixed = (1 << 28) | (100 << 10) | 100
        request = synthetic_epr_request(fixed, self.words[0])
        self.session.consume(synthetic_capabilities((100 << 10) | 300, self.words[1], self.words[2]))
        self.assertEqual(self.session.consume(request).rdo.status, ParseStatus.CONTEXT_MISSING)
        self.session.consume_extended(self._complete())
        self.assertEqual(self.session.consume(request).rdo.operating_current_ma, 1000)
        self.assertEqual(self.session.source_pdos()[0].raw, (100 << 10) | 300)
        for voltage, current, valid in ((15000, 3000, True), (15100, 1500, True), (15100, 1550, False)):
            raw = (3 << 28) | ((voltage // 25) << 9) | (current // 50)
            ordinary = parse_capture(synthetic_message(0x1082, (raw,)))
            for candidate in (ordinary, synthetic_epr_request(raw, self.words[2])):
                decoded = self.session.consume(candidate).rdo
                self.assertEqual(decoded.status, ParseStatus.VALID if valid else ParseStatus.INVALID)
                self.assertEqual((decoded.request_type, decoded.operating_voltage_mv), (SupplyType.SPR_AVS, voltage))

    def test_synthetic_reserved_positions_frame_count_and_invalid_capability_updates(self):
        self.session.consume_extended(self._complete())
        initial = self.session.epr_source_capabilities()
        for position in (0, 4, 7, 10, 12, 15):
            raw = (position << 28) | (100 << 10) | 100
            self.assertEqual(self.session.consume(synthetic_epr_request(raw, 0)).rdo.status, ParseStatus.INVALID)
        malformed = parse_capture(synthetic_message(0x1089, (0x90000000,)))
        self.assertIsNone(malformed.rdo)
        self.assertIn("epr_request_object_count", {d.code for d in malformed.diagnostics})
        bad_layout = (self.words[:8], self.words[:2] + (0, self.words[2]) + self.words[4:],
                      self.words[:7] + (self.words[8], self.words[7]), self.words[:6])
        for words in bad_layout:
            invalid = self._complete(words)
            self.assertEqual(invalid.epr.status, ParseStatus.INVALID)
            self.session.consume_extended(invalid)
            self.assertIs(self.session.epr_source_capabilities(), initial)
        unaligned = self.engine.consume(parse_extended(17, self.payload + b"\x01"))
        self.assertEqual(unaligned.epr.status, ParseStatus.INVALID)
        wrong_source = self._complete(sender=0)
        self.assertIn("epr_sender", {d.code for d in wrong_source.epr.diagnostics})

    def test_synthetic_capability_refresh_and_lifecycle(self):
        initial = self._complete()
        self.session.consume_extended(initial)
        old_request = synthetic_epr_request(int(self.sample["epr_rdo_hex"], 16), self.words[8])
        newer = self._complete((*self.words[:8], self.words[8] + 5))
        self.session.consume_extended(newer)
        self.assertIs(self.session.epr_source_capabilities(), newer.epr)
        self.assertEqual(self.session.consume(old_request).rdo.diagnostics[0].code, "epr_pdo_echo_mismatch")
        for reset in (synthetic_reset("07180706"), parse_capture(synthetic_message(0x8D, sop="18180606"))):
            self.session.consume(reset)
            self.assertIs(self.session.epr_source_capabilities(), newer.epr)
        for reset in (synthetic_reset("07070719"), parse_capture(synthetic_message(0x8D)),
                      parse_capture(synthetic_message(0x108A, (0x05000000,)))):
            self.session.consume(reset)
            self.assertIsNone(self.session.epr_source_capabilities())
            self.session.consume_extended(newer)
        self.session.disconnect()
        self.assertIsNone(self.session.epr_source_capabilities())

    def test_synthetic_epr_caps_can_report_only_spr_slots_at_exit(self):
        caps = self._complete(self.words[:7]).epr
        self.assertEqual(caps.status, ParseStatus.VALID)
        self.assertEqual(caps.epr_pdos, ())
        self.assertEqual(len(caps.slots), 7)
