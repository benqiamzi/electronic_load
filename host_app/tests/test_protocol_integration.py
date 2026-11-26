import unittest

from electronic_load_gui.protocols.usb_pd import parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus, SupplyType, VDMType
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from protocol_m7_fixtures import ProtocolReplay, capture_wire, parse_wire, synthetic_mixed_wire


class ProtocolIntegrationTests(unittest.TestCase):
    def test_synthetic_mixed_cdc_replay_keeps_contexts_independent(self):
        labels, wire, expected = synthetic_mixed_wire()
        replay = ProtocolReplay()
        results = {}
        for label, record in zip(labels, parse_wire(wire, fragment_size=17), strict=True):
            result, power, discovery, extended = replay.consume(record)
            results[label] = result, power, discovery, extended
            self.assertIs(result.record, record)
            self.assertEqual(result, parse_capture(record))
            self.assertIn(b"\x0a\x00\x0d\x00", record.raw_payload)
            if label == "cable_reset":
                self.assertEqual([item.sop for item in extended.interrupted], [SopKind.SOP_PRIME])
                self.assertEqual(replay.extended.active_count, 1)
                self.assertIsNotNone(replay.discovery.identity())
                self.assertEqual(len(replay.power.source_pdos()), 3)
            elif label == "soft_reset":
                self.assertEqual(replay.power.source_pdos(), ())
                self.assertIsNone(replay.power.epr_source_capabilities())
                self.assertIsNotNone(replay.discovery.identity())
            elif label == "hard_reset":
                self.assertIsNone(replay.discovery.identity())
                self.assertEqual(replay.extended.cached_bytes, 0)

        caps = results["source"][0]
        self.assertEqual([pdo.supply_type for pdo in caps.pdos], [SupplyType.FIXED, SupplyType.FIXED, SupplyType.SPR_AVS])
        self.assertIs(results["request"][1].rdo.selected_pdo, caps.pdos[0])
        self.assertEqual(results["request"][1].rdo.operating_current_ma, expected["request_ma"])
        self.assertEqual(results["accept"][0].message_type.name, "Accept")
        mode = results["enter_mode"][2].mode
        self.assertEqual(mode.raw, int(expected["mode_raw"], 16))
        self.assertIs(mode, results["modes"][0].vdm.vdos[0])
        self.assertEqual(results["svids"][0].vdm.discovered_svids, (0xFF01,))
        self.assertEqual(results["unstructured"][0].vdm.vdm_type, VDMType.UNSTRUCTURED)
        self.assertEqual(results["unknown_vdm"][0].vdm.status, ParseStatus.INVALID)
        self.assertEqual(results["unchunked"][3].message.payload, b"\x01\x02\x03")
        self.assertEqual(results["unknown_extended"][3].message.payload, b"\x12\x34")

        pending = results["epr_chunk_zero"][3]
        completed = results["epr_chunk_one"][3]
        reverse = results["epr_chunk_request"][0]
        self.assertEqual(pending.epr.status, ParseStatus.PARTIAL)
        self.assertEqual(results["epr_chunk_request"][3].requested_chunk, 1)
        self.assertEqual(completed.status, ReassemblyStatus.COMPLETE)
        self.assertEqual(completed.message.frames, (pending.result, completed.result))
        self.assertEqual(completed.message.requests, (reverse,))
        self.assertEqual(len(completed.epr.slots), expected["epr_slots"])
        for kind in ("epr_avs", "epr_fixed", "spr_avs"):
            rdo = results[kind][1].rdo
            self.assertEqual(rdo.status, ParseStatus.VALID)
            self.assertEqual(rdo.operating_current_ma, expected[f"{kind}_ma"])
            if f"{kind}_mv" in expected:
                self.assertEqual(rdo.operating_voltage_mv, expected[f"{kind}_mv"])
        self.assertEqual(results["epr_after_reset"][1].rdo.status, ParseStatus.CONTEXT_MISSING)
        self.assertEqual(replay.extended.active_count, 0)

    def test_synthetic_lossless_reencoding_of_capture_records(self):
        _, wire, _ = synthetic_mixed_wire()
        records = tuple(parse_wire(wire, fragment_size=1))
        self.assertEqual(b"".join(capture_wire(record) for record in records), wire)
