import math
import unittest

from electronic_load_gui.domain import (
    ResponseError,
    format_current_command,
    parse_device_error,
    parse_identity,
    parse_measurements,
    parse_status,
    parse_switch_state,
)


class DomainParsingTests(unittest.TestCase):
    def test_parse_measurements(self) -> None:
        result = parse_measurements("12.3456,1.2345,15.2407,42.30,43.10")
        self.assertAlmostEqual(result.voltage_v, 12.3456)
        self.assertAlmostEqual(result.current_a, 1.2345)
        self.assertAlmostEqual(result.power_w, 15.2407)
        self.assertAlmostEqual(result.left_temperature_c, 42.30)
        self.assertAlmostEqual(result.right_temperature_c, 43.10)

    def test_measurements_reject_wrong_field_count(self) -> None:
        with self.assertRaises(ResponseError):
            parse_measurements("12.0,1.0")

    def test_measurements_reject_non_finite_values(self) -> None:
        with self.assertRaises(ResponseError):
            parse_measurements("nan,1,2,3,4")

    def test_parse_status(self) -> None:
        result = parse_status("ENABLED,NONE,1.2000")
        self.assertEqual(result.state, "ENABLED")
        self.assertEqual(result.fault, "NONE")
        self.assertAlmostEqual(result.requested_current_a, 1.2)

    def test_parse_device_error(self) -> None:
        ok = parse_device_error('0,"No error"')
        failure = parse_device_error('-221,"Settings conflict"')
        self.assertFalse(ok.is_error)
        self.assertTrue(failure.is_error)
        self.assertEqual(failure.code, -221)

    def test_parse_identity_and_switch(self) -> None:
        self.assertEqual(
            parse_identity("ElectronicLoad,EL-F411,0,0.1.0"),
            "ElectronicLoad,EL-F411,0,0.1.0",
        )
        self.assertTrue(parse_switch_state("1"))
        self.assertFalse(parse_switch_state("0"))

    def test_format_current_command(self) -> None:
        self.assertEqual(format_current_command(1.2), "SOUR:CURR 1.2000")
        with self.assertRaises(ValueError):
            format_current_command(5.1)
        with self.assertRaises(ValueError):
            format_current_command(math.inf)


if __name__ == "__main__":
    unittest.main()
