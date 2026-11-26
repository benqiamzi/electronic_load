import unittest

from electronic_load_gui.protocols.usb_pd import decode_pdo, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import PDODirection, SupplyType

from test_usb_pd import synthetic_message


class PDOTests(unittest.TestCase):
    def test_synthetic_fixed_source_and_sink_flags(self) -> None:
        raw = (1 << 29) | (1 << 28) | (1 << 26) | (3 << 23) | (100 << 10) | 150
        source = decode_pdo(raw, direction="source", index=1)
        sink = decode_pdo(raw, direction="sink", index=1)
        self.assertEqual(source.supply_type, SupplyType.FIXED)
        self.assertEqual((source.voltage_min_mv, source.voltage_max_mv), (5000, 5000))
        self.assertEqual(source.current_max_ma, 1500)
        self.assertIsNone(source.operating_current_ma)
        self.assertEqual(source.capabilities, {
            "dual_role_power", "usb_suspend_supported", "usb_communications_capable",
            "unchunked_extended_messages_supported", "epr_capable",
        })
        self.assertEqual(sink.operating_current_ma, 1500)
        self.assertIsNone(sink.current_max_ma)
        self.assertEqual(sink.capabilities, {"dual_role_power", "higher_capability", "usb_communications_capable"})
        self.assertEqual(sink.fast_role_swap_current_code, 3)
        self.assertEqual((source.status, sink.status), (ParseStatus.VALID, ParseStatus.VALID))
        for direction in PDODirection:
            self.assertEqual(decode_pdo(raw, direction=direction, revision=1).reserved_bits, 3 << 23)

    def test_synthetic_non_first_fixed_flags_and_peak_current(self) -> None:
        raw = (1 << 28) | (2 << 20) | (180 << 10) | 300
        source = decode_pdo(raw, direction="source", index=2)
        sink = decode_pdo(raw, direction="sink", index=2)
        self.assertEqual(source.peak_current_code, 2)
        self.assertEqual(source.reserved_bits, 1 << 28)
        self.assertEqual(sink.reserved_bits, (1 << 28) | (2 << 20))
        self.assertEqual((source.status, sink.status), (ParseStatus.INVALID, ParseStatus.INVALID))
        self.assertEqual(source.raw, raw)

    def test_synthetic_variable_and_battery_physical_units(self) -> None:
        for direction in PDODirection:
            with self.subTest(direction=direction):
                variable = decode_pdo((2 << 30) | (240 << 20) | (100 << 10) | 123, direction=direction)
                battery = decode_pdo((1 << 30) | (360 << 20) | (180 << 10) | 201, direction=direction)
                self.assertEqual((variable.supply_type, battery.supply_type), (SupplyType.VARIABLE, SupplyType.BATTERY))
                self.assertEqual((variable.voltage_min_mv, variable.voltage_max_mv), (5000, 12000))
                self.assertEqual((battery.voltage_min_mv, battery.voltage_max_mv), (9000, 18000))
                if direction == PDODirection.SOURCE:
                    self.assertEqual(variable.current_max_ma, 1230)
                    self.assertEqual(battery.power_max_mw, 50250)
                    self.assertIsNone(battery.operating_power_mw)
                else:
                    self.assertEqual(variable.operating_current_ma, 1230)
                    self.assertEqual(battery.operating_power_mw, 50250)
                    self.assertIsNone(battery.power_max_mw)
                self.assertEqual((variable.status, battery.status), (ParseStatus.VALID, ParseStatus.VALID))

    def test_synthetic_pps_directions_and_reserved_bits(self) -> None:
        raw = (3 << 30) | (110 << 17) | (50 << 8) | 60
        source = decode_pdo(raw | (1 << 27), direction="source")
        sink = decode_pdo(raw, direction="sink")
        for result in (source, sink):
            self.assertEqual(result.supply_type, SupplyType.PPS)
            self.assertEqual((result.voltage_min_mv, result.voltage_max_mv, result.current_max_ma), (5000, 11000, 3000))
            self.assertEqual(result.status, ParseStatus.VALID)
        self.assertIs(source.pps_power_limited, True)
        self.assertIsNone(sink.pps_power_limited)
        source_reserved = (3 << 25) | (1 << 16) | (1 << 7)
        self.assertEqual(decode_pdo(raw | source_reserved, direction="source").reserved_bits, source_reserved)
        self.assertEqual(decode_pdo(source.raw, direction="sink").reserved_bits, 1 << 27)
        self.assertIn("apdo_revision", {d.code for d in decode_pdo(raw, direction="source", revision=1).diagnostics})
        self.assertIn("pps_voltage_limit", {d.code for d in decode_pdo(raw | (1 << 24), direction="source").diagnostics})

    def test_synthetic_avs_fields_and_unknown_subtype(self) -> None:
        spr = (0xE << 28) | (2 << 26) | (240 << 10) | 400
        epr = (0xD << 28) | (1 << 26) | (480 << 17) | (150 << 8) | 240
        source_spr = decode_pdo(spr, direction="source")
        source_epr = decode_pdo(epr, direction="source")
        sink_spr = decode_pdo(spr & ~(3 << 26) & ~0x3FF, direction="sink")
        sink_epr = decode_pdo(epr & ~(3 << 26), direction="sink")
        self.assertEqual((source_spr.supply_type, source_epr.supply_type), (SupplyType.SPR_AVS, SupplyType.EPR_AVS))
        self.assertEqual((source_spr.voltage_min_mv, source_spr.voltage_max_mv), (9000, 20000))
        self.assertEqual((source_spr.current_max_15v_ma, source_spr.current_max_20v_ma), (2400, 4000))
        self.assertEqual((sink_spr.voltage_max_mv, sink_spr.current_max_20v_ma), (15000, 0))
        self.assertEqual((source_epr.voltage_min_mv, source_epr.voltage_max_mv, source_epr.pdp_mw), (15000, 48000, 240000))
        self.assertEqual(sink_epr.pdp_mw, 240000)
        self.assertEqual((source_spr.peak_current_code, source_epr.peak_current_code), (2, 1))
        self.assertIsNone(sink_spr.peak_current_code)
        self.assertIsNone(sink_epr.peak_current_code)
        self.assertEqual(decode_pdo(spr, direction="sink").reserved_bits, 2 << 26)
        self.assertEqual(decode_pdo(epr, direction="sink").reserved_bits, 1 << 26)
        unknown = decode_pdo(0xF1234567, direction="source")
        self.assertEqual(unknown.supply_type, SupplyType.UNKNOWN_APDO)
        self.assertIsNone(unknown.voltage_max_mv)
        self.assertEqual(unknown.raw, 0xF1234567)
        for result in (source_spr, source_epr, sink_spr, sink_epr):
            self.assertEqual(result.status, ParseStatus.VALID)
            self.assertEqual(result.diagnostics, ())
        self.assertEqual(unknown.status, ParseStatus.UNSUPPORTED)
        self.assertTrue(unknown.diagnostics)

    def test_synthetic_invalid_range_and_first_pdo(self) -> None:
        raw = (2 << 30) | (100 << 20) | (180 << 10) | 300
        invalid = decode_pdo(raw, direction="source", index=1)
        self.assertEqual(invalid.status, ParseStatus.INVALID)
        self.assertEqual({item.code for item in invalid.diagnostics}, {"first_pdo", "voltage_range"})
        self.assertEqual(decode_pdo(100 << 10, direction="source", index=1).status, ParseStatus.VALID)
        with self.assertRaises(ValueError):
            decode_pdo(1 << 32, direction="source")

    def test_synthetic_sink_capabilities_selects_sink_layout(self) -> None:
        record = synthetic_message(0x1084, ((1 << 28) | (100 << 10) | 125,))
        result = parse_capture(record)
        (pdo,) = result.pdos
        self.assertIs(result.record, record)
        self.assertIs(result.crc_valid, True)
        self.assertEqual(result.data_objects, (pdo.raw,))
        self.assertEqual((pdo.direction, pdo.index, pdo.operating_current_ma), (PDODirection.SINK, 1, 1250))
        self.assertEqual(pdo.capabilities, {"higher_capability"})
