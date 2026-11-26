from dataclasses import replace
import json
import unittest

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import CaptureRecordParser
from electronic_load_gui.protocols.usb_pd import PDSessionContext, VDMContext, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import VDMCommandType
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from test_pd_session import synthetic_capabilities, synthetic_request, synthetic_reset
from test_usb_pd import FIXTURES, reference_crc32, synthetic_message
from test_vdm import synthetic_vdm_fixture, synthetic_vdm_record


def synthetic_vdm(*words, **header):
    return parse_capture(synthetic_vdm_record(*words, **header))


_FULL_PAGE = (0x01010102, 0x01030104, 0x01050106, 0x01070108, 0x0109010A, 0x010B010C)


class VDMContextTests(unittest.TestCase):
    def setUp(self):
        self.context = VDMContext()
        self.port = parse_capture(synthetic_vdm_fixture("discover_identity_drd_ack"))
        self.cable = parse_capture(synthetic_vdm_fixture("discover_identity_passive_cable_ack"))

    def test_synthetic_port_cable_and_responder_role_isolation(self):
        dfp = synthetic_vdm(0xFF00A841, 0x01401209, 0, 0x12340100, 0x20000020, data_role=1)
        for identity in (self.port, self.cable, dfp):
            analysis = self.context.consume(identity)
            self.assertEqual(analysis.status, ParseStatus.VALID)
            self.assertIs(analysis.result, identity)
        self.assertIs(self.context.identity(), self.port)
        self.assertIs(self.context.identity(responder_role=1), dfp)
        self.assertIs(self.context.identity(SopKind.SOP_PRIME), self.cable)
        self.assertIsNone(self.context.identity(SopKind.SOP_DOUBLE_PRIME))

        self.context.consume(synthetic_vdm(0xFF00A842, 0xFF010000))
        self.context.consume(synthetic_vdm(0xFF00A842, 0x12090000, data_role=1))
        self.context.consume(synthetic_vdm(0xFF00A842, 0x28DE0000, sop="18180606"))
        self.assertEqual(self.context.svids(), (0xFF01,))
        self.assertEqual(self.context.svids(responder_role=1), (0x1209,))
        self.assertEqual(self.context.svids(SopKind.SOP_PRIME), (0x28DE,))

    def test_synthetic_discover_svid_pages_publish_on_termination(self):
        self.context.consume(self.port)
        first = synthetic_vdm(0xFF00A842, *_FULL_PAGE, message_id=1)
        self.context.consume(first)
        self.context.consume(first)
        self.assertIsNone(self.context.svids())
        end = synthetic_vdm(0xFF00A842, 0, message_id=2)
        self.assertEqual(self.context.consume(end).status, ParseStatus.VALID)
        self.assertEqual(self.context.svids(), tuple(range(0x0101, 0x010D)))
        self.assertEqual(self.context.svid_sources(), (first, end))
        self.assertEqual(self.context.consume(end).status, ParseStatus.VALID)
        self.assertEqual(self.context.svid_sources(), (first, end))

        replacement = synthetic_vdm(0xFF00A842, 0xFF010000, message_id=3)
        self.context.consume(replacement)
        self.assertEqual(self.context.svids(), (0xFF01,))
        self.assertEqual(self.context.svid_sources(), (replacement,))

    def test_synthetic_conflicting_svid_pages_keep_last_complete_snapshot(self):
        self.context.consume(self.port)
        older = synthetic_vdm(0xFF00A842, 0xFF010000)
        self.context.consume(older)
        self.context.consume(synthetic_vdm(0xFF00A842, *_FULL_PAGE, message_id=1))
        result = self.context.consume(synthetic_vdm(0xFF00A842, 0x01010000, message_id=2))
        self.assertEqual(result.status, ParseStatus.INVALID)
        self.assertEqual({d.code for d in result.diagnostics}, {"vdm_duplicate_svid_page"})
        self.assertEqual(self.context.svids(), (0xFF01,))
        self.assertEqual(self.context.svid_sources(), (older,))

    def test_synthetic_discover_modes_are_retained_by_svid_and_update_in_place(self):
        self.context.consume(self.port)
        self.context.consume(synthetic_vdm(0xFF00A842, 0xFF011209, 0))
        dp = synthetic_vdm(0xFF01A843, 0x100, 0x200)
        vendor = synthetic_vdm(0x1209A843, 0x300)
        cable = synthetic_vdm(0xFF01A843, 0x400, sop="18180606")
        for result in (dp, vendor, cable):
            self.context.consume(result)
        self.assertIs(self.context.modes(0xFF01), dp)
        self.assertIs(self.context.modes(0x1209), vendor)
        self.assertIs(self.context.modes(0xFF01, SopKind.SOP_PRIME), cable)
        newer_dp = synthetic_vdm(0xFF01A843, 0x444)
        self.assertEqual(self.context.consume(newer_dp).status, ParseStatus.VALID)
        self.assertIs(self.context.modes(0xFF01), newer_dp)
        self.assertIs(self.context.modes(0x1209), vendor)
        self.context.consume(synthetic_vdm(0xFF00A842, 0xFF010000))
        self.assertIsNone(self.context.modes(0x1209))
        self.assertIs(self.context.modes(0xFF01), newer_dp)
        self.assertIs(self.context.modes(0xFF01, SopKind.SOP_PRIME), cable)

    def test_synthetic_mode_events_reference_modes_without_inferring_active_state(self):
        modes = synthetic_vdm(0xFF01A843, 0x100, 0x200)
        self.context.consume(modes)
        for header, role in ((0xFF01AA04, 1), (0xFF01AA84, 0), (0xFF01AA06, 0), (0xFF01AA05, 1)):
            result = synthetic_vdm(header, data_role=role)
            with self.subTest(header=header):
                analysis = self.context.consume(result)
                self.assertEqual(analysis.status, ParseStatus.VALID)
                self.assertIs(analysis.mode, modes.vdm.vdos[1])
                self.assertIs(analysis.result, result)
        self.assertEqual([event.vdm.command_type for event in self.context.mode_events(svid=0xFF01)],
                         [VDMCommandType.INITIATOR, VDMCommandType.NAK, VDMCommandType.INITIATOR, VDMCommandType.INITIATOR])
        exit_all = self.context.consume(synthetic_vdm(0xFF01AF05, data_role=1))
        self.assertEqual(exit_all.status, ParseStatus.VALID)
        self.assertIsNone(exit_all.mode)
        bad_position = self.context.consume(synthetic_vdm(0xFF01AB04, data_role=1))
        self.assertEqual(bad_position.status, ParseStatus.INVALID)
        self.assertEqual({d.code for d in bad_position.diagnostics}, {"vdm_mode_not_advertised"})

    def test_synthetic_missing_observations_and_unsuccessful_discovery(self):
        cases = (
            (synthetic_vdm(0xFF00A842, 0xFF010000), "No valid Identity"),
            (synthetic_vdm(0x1209A843, 0x100), "SVID list"),
            (synthetic_vdm(0xFF01A906), "No valid Discover Modes"),
            (synthetic_vdm(0xFF00A842, 0), "terminating SVID page"),
        )
        for result, detail in cases:
            with self.subTest(detail=detail):
                analysis = self.context.consume(result)
                self.assertEqual(analysis.status, ParseStatus.CONTEXT_MISSING)
                self.assertEqual({d.code for d in analysis.diagnostics}, {"vdm_context_missing"})
                self.assertIn(detail, analysis.diagnostics[0].message)
        replay = self.context.consume(cases[0][0])
        self.assertEqual(replay.status, ParseStatus.CONTEXT_MISSING)
        self.assertIn("No valid Identity", replay.diagnostics[0].message)
        older = self.context.modes(0x1209)
        for code in (0x80, 0xC0):
            for header in (0xFF00A801, 0xFF00A802, 0x1209A803):
                self.context.consume(synthetic_vdm(header | code))
        self.assertIsNone(self.context.identity())
        self.assertEqual(self.context.svids(), (0xFF01,))
        self.assertIs(self.context.modes(0x1209), older)

    def test_synthetic_validated_svid_restart_and_soft_reset_keep_completed_state(self):
        self.context.consume(self.port)
        last = synthetic_vdm(0xFF00A842, 0xFF010000)
        self.context.consume(last)
        request = synthetic_vdm(0xFF00A802, data_role=1)
        first = synthetic_vdm(0xFF00A842, *_FULL_PAGE, message_id=1)
        end = synthetic_vdm(0xFF00A842, 0, message_id=2)
        for restart in (parse_capture(synthetic_message(0x008D)), synthetic_vdm(0xFF00A801, data_role=1)):
            self.context.consume(first)
            self.context.consume(restart)
            self.assertIs(self.context.identity(), self.port)
            self.context.consume(request)
            self.assertEqual(self.context.consume(end).status, ParseStatus.CONTEXT_MISSING)
            self.assertEqual(self.context.svid_sources(), (last,))
        self.context.consume(first)
        self.context.consume(parse_capture(synthetic_message(0x008D, sop="18180606")))
        self.context.consume(end)
        self.assertEqual(self.context.svids(), tuple(range(0x0101, 0x010D)))

    def test_synthetic_reset_disconnect_and_pdo_context_are_independent(self):
        power = PDSessionContext()
        caps = synthetic_capabilities((100 << 10) | 300)
        power.consume(caps)
        self.context.consume(self.port)
        self.context.consume(self.cable)
        self.context.consume(synthetic_vdm(0x1209A106, sop="18061806"))
        self.context.consume(synthetic_vdm(0xFF01A906))
        self.context.consume(synthetic_reset("07180706"))
        self.assertIs(self.context.identity(), self.port)
        self.assertIsNone(self.context.identity(SopKind.SOP_PRIME))
        self.assertEqual(self.context.mode_events(SopKind.SOP_DOUBLE_PRIME), ())
        self.assertEqual(len(self.context.mode_events()), 1)
        self.context.consume(self.cable)
        self.context.consume(parse_capture(synthetic_message(0x008F)))  # Data_Reset_Complete.
        self.assertIsNone(self.context.identity(SopKind.SOP_PRIME))
        self.assertIs(self.context.identity(), self.port)
        self.assertEqual(self.context.mode_events(), ())
        self.context.consume(synthetic_reset("07070719"))
        self.assertIsNone(self.context.identity())
        self.context.consume(self.port)
        self.context.disconnect()
        self.assertIsNone(self.context.identity())
        self.assertIs(power.consume(synthetic_request()).rdo.selected_pdo, caps.pdos[0])

    def test_synthetic_bad_crc_does_not_change_observations(self):
        self.context.consume(self.port)
        record = self.port.record
        corrupted = replace(record, decoded_data=record.decoded_data[:-4] + b"\x00" * 4)
        result = parse_capture(corrupted)
        self.assertIs(result.crc_valid, False)
        self.context.consume(result)
        self.context.consume(synthetic_reset("07070719", decode_result=2))
        self.assertIs(self.context.identity(), self.port)

    def test_synthetic_identity_updates_invalidate_only_that_responders_discoveries(self):
        self.context.consume(self.port)
        self.context.consume(self.cable)
        self.context.consume(synthetic_vdm(0xFF00A842, 0xFF010000))
        self.context.consume(synthetic_vdm(0xFF01A843, 0x100))
        self.context.consume(self.port)
        self.assertEqual(self.context.svids(), (0xFF01,))
        newer = synthetic_vdm(0xFF00A041, 0x00401209, 0, 0x00010100)
        self.context.consume(newer)
        self.assertIs(self.context.identity(), newer)
        self.assertIsNone(self.context.svids())
        self.assertIsNone(self.context.modes(0xFF01))
        self.assertIs(self.context.identity(SopKind.SOP_PRIME), self.cable)

    def test_synthetic_accepted_data_role_swap_clears_old_role_keys(self):
        self.context.consume(self.port)
        self.context.consume(self.cable)
        swap = parse_capture(synthetic_message(0x0089))
        self.context.consume(swap)
        self.context.consume(parse_capture(synthetic_message(0x0084)))  # Reject.
        self.assertIs(self.context.identity(), self.port)
        self.context.consume(swap)
        self.context.consume(parse_capture(synthetic_message(0x00A1)))  # GoodCRC.
        self.context.consume(parse_capture(synthetic_message(0x00A3)))  # Accept.
        self.assertIsNone(self.context.identity())
        self.assertIs(self.context.identity(SopKind.SOP_PRIME), self.cable)

    def test_synthetic_event_history_is_bounded_per_address(self):
        context = VDMContext(event_limit=2)
        for message_id in range(3):
            context.consume(synthetic_vdm(0xFF01A906, message_id=message_id))
        self.assertEqual([event.header.message_id for event in context.mode_events()], [1, 2])

    def test_synthetic_pending_discovery_rejects_wrong_command_and_svid(self):
        request = synthetic_vdm(0x1209A803, data_role=1)
        self.context.consume(request)
        self.context.consume(parse_capture(synthetic_message(0x0081)))  # GoodCRC.
        # An unrelated cable reply does not close the observed port query.
        cable = synthetic_vdm(0x1209A843, 0x321, sop="18180606")
        self.assertIsNone(self.context.consume(cable).request)
        for reply in (synthetic_vdm(0xFF01A043, 0x432), synthetic_vdm(0xFF00A042, 0x12090000)):
            analysis = self.context.consume(reply)
            self.assertEqual(analysis.status, ParseStatus.INVALID)
            self.assertIs(analysis.request, request)
            self.assertIs(analysis.result, reply)
            self.assertEqual(analysis.diagnostics[0].code, "vdm_discovery_response_mismatch")
        self.assertIsNone(self.context.modes(0xFF01))
        self.assertIsNone(self.context.svids())
        match = synthetic_vdm(0x1209A043, 0x543)
        self.assertIs(self.context.consume(match).request, request)  # Version downgrade is valid.
        self.assertIs(self.context.modes(0x1209), match)
        self.assertIs(self.context.modes(0x1209, SopKind.SOP_PRIME), cable)

    def test_synthetic_interrupted_discovery_allows_later_response_only_replay(self):
        request = synthetic_vdm(0x1209A803, data_role=1)
        reply = synthetic_vdm(0xFF01A843, 0x543)
        self.context.consume(request)
        self.context.consume(parse_capture(synthetic_message(0x0090)))  # Not_Supported.
        analysis = self.context.consume(reply)
        self.assertIsNone(analysis.request)
        self.assertIs(self.context.modes(0xFF01), reply)


class RealVDMDiscoveryTests(unittest.TestCase):
    def _replay(self, name):
        fixture = json.loads((FIXTURES / "usb_pd_vdm_discovery_real.json").read_text(encoding="utf-8"))
        self.assertEqual(fixture["provenance"], "real")
        session = next(item for item in fixture["sessions"] if item["name"] == name)
        self.assertEqual(session["provenance"], "real")
        context = VDMContext()
        inquiries = {}
        for inquiry in session["inquiries"]:
            analyses = {}
            for sample in inquiry["records"]:
                self.assertEqual(sample["provenance"], "real")
                (payload,) = BinaryBlockParser().feed(bytes.fromhex(sample["wire_hex"]))
                record = CaptureRecordParser.parse(payload, session["capture_cycle_ns"])
                self.assertEqual(record.raw_payload, payload)
                self.assertEqual(len(payload), sample["payload_bytes"])
                self.assertEqual(record.pulse_count, sample["capture_pulse_count"])
                self.assertEqual((record.start_timestamp_us, record.end_timestamp_us),
                                 (sample["start_timestamp_us"], sample["end_timestamp_us"]))
                self.assertEqual(record.decoded_data.hex(), sample["decoded_hex"])
                result = parse_capture(record)
                self.assertIs(result.record, record)
                self.assertIs(result.crc_valid, True)
                self.assertEqual(result.crc_received, reference_crc32(record.decoded_data[:-4]))
                analysis = context.consume(result)
                if result.vdm is not None:
                    self.assertEqual(result.vdm.command_type.name, sample["kind"])
                else:
                    self.assertEqual(result.message_type.name, sample["kind"])
                analyses[sample["kind"]] = analysis
            inquiries[inquiry["command"]] = analyses
        return context, inquiries

    def test_real_advertised_svid_and_mismatched_modes_ack(self):
        context, inquiries = self._replay("advertised_2717")
        identity = inquiries["DISCOVER_IDENTITY"]
        self.assertIs(identity["ACK"].request, identity["INITIATOR"].result)
        self.assertEqual(identity["ACK"].status, ParseStatus.PARTIAL)
        svids = inquiries["DISCOVER_SVIDS"]
        self.assertIs(svids["ACK"].request, svids["INITIATOR"].result)
        self.assertEqual(svids["ACK"].result.vdm.discovered_svids, (0x2717,))
        self.assertTrue(svids["ACK"].result.vdm.svids_terminated)
        self.assertEqual(context.svids(responder_role=1), (0x2717,))

        modes = inquiries["DISCOVER_MODES,10007"]
        ack = modes["ACK"]
        self.assertEqual(modes["INITIATOR"].result.vdm.svid, 0x2717)
        self.assertEqual((ack.result.vdm.svid, ack.result.vdm.vdos[0].raw), (0xFF01, 0x00000405))
        self.assertEqual(ack.result.vdm.status, ParseStatus.VALID)
        self.assertIs(ack.request, modes["INITIATOR"].result)
        self.assertEqual(ack.status, ParseStatus.INVALID)
        self.assertEqual(ack.diagnostics[0].code, "vdm_discovery_response_mismatch")
        self.assertIn("Not_Supported", modes)
        for svid in (0x2717, 0xFF01):
            self.assertIsNone(context.modes(svid, responder_role=1))

    def test_real_explicit_modes_query_matches_ack_and_preserves_mode_word(self):
        context, inquiries = self._replay("direct_ff01")
        modes = inquiries["DISCOVER_MODES,65281"]
        request = modes["INITIATOR"].result
        ack = modes["ACK"]
        self.assertEqual((request.vdm.svid, ack.result.vdm.svid), (0xFF01, 0xFF01))
        self.assertEqual((request.vdm.structured_version, ack.result.vdm.structured_version), ((2, 0), (2, 1)))
        self.assertIs(ack.request, request)
        self.assertEqual(ack.result.vdm.status, ParseStatus.VALID)
        self.assertEqual(ack.status, ParseStatus.CONTEXT_MISSING)  # This session opened after SVID discovery.
        self.assertEqual({issue.code for issue in ack.diagnostics},
                         {"vdm_context_missing", "vdm_discovery_response_version"})
        self.assertIs(context.modes(0xFF01, responder_role=1), ack.result)
        (mode,) = ack.result.vdm.vdos
        self.assertEqual((mode.mode_position, mode.raw), (1, 0x00000405))
