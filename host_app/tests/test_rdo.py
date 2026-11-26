import unittest

from electronic_load_gui.protocols.usb_pd import decode_pdo, decode_rdo, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import SupplyType

from test_usb_pd import synthetic_message


class RDOTests(unittest.TestCase):
    def test_synthetic_fixed_and_variable_requests(self) -> None:
        fixed = decode_pdo((100 << 10) | 300, direction="source", index=1)
        variable = decode_pdo((2 << 30) | (240 << 20) | (100 << 10) | 300, direction="source", index=2)
        flags = (1 << 26) | (1 << 25) | (1 << 24) | (1 << 23) | (1 << 22)
        for pdo, kind in ((fixed, SupplyType.FIXED), (variable, SupplyType.VARIABLE)):
            with self.subTest(kind=kind):
                raw = (pdo.index << 28) | flags | (225 << 10) | 225
                rdo = decode_rdo(raw, pdo)
                self.assertEqual((rdo.raw, rdo.status, rdo.request_type), (raw, ParseStatus.VALID, kind))
                self.assertIs(rdo.selected_pdo, pdo)
                self.assertEqual((rdo.operating_current_ma, rdo.maximum_operating_current_ma), (2250, 2250))
                for flag in (rdo.capability_mismatch, rdo.usb_communications_capable, rdo.no_usb_suspend,
                             rdo.unchunked_extended_messages_supported, rdo.epr_capable):
                    self.assertTrue(flag)
                self.assertFalse(rdo.give_back)
                self.assertIsNone(rdo.operating_voltage_mv)

    def test_synthetic_battery_requests_use_power_limits(self) -> None:
        pdo = decode_pdo((1 << 30) | (240 << 20) | (100 << 10) | 200, direction="source", index=2)
        rdo = decode_rdo((2 << 28) | (161 << 10) | 161, pdo)
        self.assertEqual(rdo.request_type, SupplyType.BATTERY)
        self.assertEqual((rdo.operating_power_mw, rdo.maximum_operating_power_mw), (40250, 40250))
        self.assertIsNone(rdo.operating_current_ma)
        self.assertEqual(rdo.status, ParseStatus.VALID)
        excessive = decode_rdo((2 << 28) | (201 << 10) | 201, pdo)
        self.assertEqual(excessive.status, ParseStatus.INVALID)
        self.assertIn("operating_limit", {d.code for d in excessive.diagnostics})

    def test_synthetic_pps_requests_use_independent_voltage_and_current_steps(self) -> None:
        pdo = decode_pdo(0xC8DC3264, direction="source", index=6)
        rdo = decode_rdo((6 << 28) | (433 << 9) | 87, pdo)
        self.assertEqual(rdo.request_type, SupplyType.PPS)
        self.assertEqual((rdo.operating_voltage_mv, rdo.operating_current_ma), (8660, 4350))
        self.assertIsNone(rdo.give_back)
        self.assertIsNone(rdo.maximum_operating_current_ma)
        self.assertEqual(rdo.status, ParseStatus.VALID)
        for mv, expected in ((4980, ParseStatus.INVALID), (5000, ParseStatus.VALID),
                             (11000, ParseStatus.VALID), (11020, ParseStatus.INVALID)):
            with self.subTest(mv=mv):
                self.assertEqual(decode_rdo((6 << 28) | ((mv // 20) << 9) | 100, pdo).status, expected)
        excessive = decode_rdo((6 << 28) | (450 << 9) | 101, pdo)
        self.assertEqual({d.code for d in excessive.diagnostics}, {"operating_limit"})

    def test_synthetic_fixed_limits_and_legacy_maximum_with_mismatch(self) -> None:
        pdo = decode_pdo((100 << 10) | 300, direction="source")
        raw = (1 << 28) | (300 << 10) | 350
        legacy = decode_rdo(raw | (1 << 26), pdo)
        self.assertEqual(legacy.status, ParseStatus.VALID)
        self.assertEqual({d.code for d in legacy.diagnostics}, {"legacy_maximum"})
        self.assertEqual(decode_rdo(raw, pdo).status, ParseStatus.INVALID)
        excessive = decode_rdo((1 << 28) | (1 << 26) | (301 << 10) | 350, pdo)
        self.assertEqual({d.code for d in excessive.diagnostics}, {"operating_limit"})
        reversed_limits = decode_rdo((1 << 28) | (200 << 10) | 100, pdo)
        self.assertEqual({d.code for d in reversed_limits.diagnostics}, {"maximum_below_operating"})

    def test_synthetic_legacy_giveback_and_reserved_bits(self) -> None:
        pdo = decode_pdo((100 << 10) | 300, direction="source")
        raw = (1 << 28) | (1 << 27) | (200 << 10) | 100
        legacy = decode_rdo(raw, pdo, revision=1)
        self.assertTrue(legacy.give_back)
        self.assertEqual(legacy.minimum_operating_current_ma, 1000)
        self.assertIsNone(legacy.maximum_operating_current_ma)
        self.assertEqual(legacy.status, ParseStatus.VALID)
        current = decode_rdo(raw, pdo)
        self.assertEqual((current.status, current.reserved_bits), (ParseStatus.INVALID, 1 << 27))
        reserved = (3 << 20) | (3 << 22)
        legacy_reserved = decode_rdo(raw | reserved, pdo, revision=1)
        self.assertEqual(legacy_reserved.reserved_bits, reserved)
        pps = decode_pdo(0xC8DC3264, direction="source")
        reserved = (1 << 27) | (1 << 21) | (3 << 7)
        invalid = decode_rdo((1 << 28) | (400 << 9) | 50 | reserved, pps)
        self.assertEqual((invalid.reserved_bits, invalid.status), (reserved, ParseStatus.INVALID))

    def test_synthetic_missing_context_and_invalid_positions_keep_raw(self) -> None:
        for position, status in ((0, ParseStatus.INVALID), (1, ParseStatus.CONTEXT_MISSING),
                                 (7, ParseStatus.CONTEXT_MISSING), (8, ParseStatus.INVALID), (15, ParseStatus.INVALID)):
            with self.subTest(position=position):
                raw = (position << 28) | (1 << 24) | 0x12345
                rdo = decode_rdo(raw)
                self.assertEqual((rdo.raw, rdo.object_position, rdo.status), (raw, position, status))
                self.assertIsNone(rdo.request_type)
                self.assertIsNone(rdo.operating_current_ma)
                self.assertIsNone(rdo.operating_power_mw)
                self.assertIsNone(rdo.operating_voltage_mv)
                self.assertTrue(rdo.no_usb_suspend)
        with self.assertRaises(ValueError):
            decode_rdo(-1)

    def test_synthetic_mismatched_or_unsupported_pdo_cannot_infer_request_layout(self) -> None:
        raw = (2 << 28) | (300 << 10) | 300
        fixed = (100 << 10) | 300
        for pdo in (decode_pdo(fixed, direction="source", index=1), decode_pdo(fixed, direction="sink", index=2)):
            rdo = decode_rdo(raw, pdo)
            self.assertEqual(rdo.status, ParseStatus.INVALID)
            self.assertIsNone(rdo.selected_pdo)
            self.assertEqual({d.code for d in rdo.diagnostics}, {"pdo_selection"})
        avs = decode_pdo((0xE << 28) | (300 << 10), direction="source", index=2)
        rdo = decode_rdo(raw, avs)
        self.assertEqual(rdo.status, ParseStatus.UNSUPPORTED)
        self.assertIs(rdo.selected_pdo, avs)
        self.assertIsNone(rdo.operating_current_ma)

    def test_synthetic_stateless_request_preserves_base_parse_status(self) -> None:
        raw = (1 << 28) | (300 << 10) | 300
        result = parse_capture(synthetic_message(0x1082, (raw,)))
        self.assertEqual(result.parse_status, ParseStatus.VALID)
        self.assertIs(result.crc_valid, True)
        self.assertEqual(result.rdo.status, ParseStatus.CONTEXT_MISSING)
        self.assertEqual(result.rdo.raw, result.data_objects[0])
