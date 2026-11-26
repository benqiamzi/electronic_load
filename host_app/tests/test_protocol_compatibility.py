import ast
import unittest
from dataclasses import FrozenInstanceError, fields
from pathlib import Path

from electronic_load_gui.protocols.usb_pd import models, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseDiagnostic
from electronic_load_gui.protocols.usb_pd.vdm_context import VDMAnalysis

from test_extended import synthetic_extended
from test_pd_session import synthetic_capabilities
from test_vdm import synthetic_vdm_fixture


class ProtocolCompatibilityTests(unittest.TestCase):
    def test_public_model_fields_remain_read_only_and_available(self):
        required = {
            models.PDMessageResult: "record sop header message_type body data_objects header_status body_status parse_status diagnostics crc_received crc_calculated crc_valid pdos rdo vdm extended_message",
            models.PDOInfo: "raw index direction supply_type status diagnostics voltage_min_mv voltage_max_mv current_max_ma operating_current_ma power_max_mw operating_power_mw capabilities reserved_bits peak_current_code fast_role_swap_current_code apdo_subtype pps_power_limited current_max_15v_ma current_max_20v_ma pdp_mw",
            models.RDOInfo: "raw object_position status request_type selected_pdo give_back capability_mismatch usb_communications_capable no_usb_suspend unchunked_extended_messages_supported epr_capable reserved_bits operating_current_ma maximum_operating_current_ma minimum_operating_current_ma operating_power_mw maximum_operating_power_mw minimum_operating_power_mw operating_voltage_mv pdo_echo diagnostics",
            models.VDMInfo: "raw_header svid vdm_type status version_major version_minor object_position command_type command command_name reserved_bits vendor_header_bits vdos discovered_svids svids_terminated diagnostics",
            models.VDOInfo: "index raw category mode_position decoded_fields vendor_fields diagnostics",
            models.ExtendedHeader: "raw data_size chunked chunk_number request_chunk reserved",
            models.ExtendedMessageInfo: "message_type header kind chunk_payload padding raw_body status wire_body_size diagnostics",
            models.ReassembledExtendedMessage: "sop message_type direction data_size payload received_chunks missing_chunks status frames requests diagnostics",
            models.ExtendedAnalysis: "result status message requested_chunk diagnostics epr interrupted",
            models.EPRSourceCapabilities: "raw_objects spr_slots epr_pdos status diagnostics",
            models.PDSessionAnalysis: "result rdo",
            VDMAnalysis: "result status mode diagnostics request",
            ParseDiagnostic: "layer code message",
        }
        for model, names in required.items():
            with self.subTest(model=model.__name__):
                self.assertTrue(model.__dataclass_params__.frozen)
                self.assertLessEqual(set(names.split()), {field.name for field in fields(model)})
        result = synthetic_capabilities((100 << 10) | 300)
        with self.assertRaises(FrozenInstanceError):
            result.data_objects = ()
        with self.assertRaises(FrozenInstanceError):
            result.pdos[0].current_max_ma = 0
        identity = parse_capture(synthetic_vdm_fixture("discover_identity_drd_ack")).vdm.vdos[0]
        with self.assertRaises(TypeError):
            identity.decoded_fields["usb_vid"] = 0

    def test_single_frame_parsing_does_not_depend_on_previous_calls(self):
        record = synthetic_extended(17, bytes(28))
        first = parse_capture(record)
        parse_capture(synthetic_vdm_fixture("discover_modes_ack"))
        synthetic_capabilities((100 << 10) | 200)
        self.assertEqual(first, parse_capture(record))
        self.assertIs(first.record, record)
        self.assertEqual(first.raw_decoded_data, record.decoded_data)
        self.assertEqual(first.firmware_decode_result, record.decode_result)

    def test_protocol_source_accepts_python_311_grammar(self):
        root = Path(models.__file__).parent
        for path in root.rglob("*.py"):
            with self.subTest(path=path.name):
                ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 11))
