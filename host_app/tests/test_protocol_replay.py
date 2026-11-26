import unittest

from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from protocol_m7_fixtures import ProtocolReplay, parse_wire, read_fixture
from test_usb_pd import FIXTURES, reference_crc32


class CuktechMiniReplayTests(unittest.TestCase):
    def test_real_cuktech_mini_workspace_capture_replay(self):
        index = read_fixture("usb_pd_m7_cuktech10mini_real.json")
        self.assertEqual(index["provenance"], "real")
        self.assertEqual((index["state_before"], index["state_after"]), ("PE_SNK_READY", "PE_SNK_READY"))
        self.assertEqual((index["capture_before"], index["capture_after"]), ("OFF", "OFF"))
        self.assertEqual(index["epr_pdo_count"], 0)
        self.assertEqual(len(index["records"]), 48)
        indexed_lines = [line for query in index["inquiries"].values() for line in query["wire_lines"]]
        self.assertEqual(indexed_lines, list(range(1, 49)))
        wire_lines = (FIXTURES / index["wire_file"]).read_text(encoding="ascii").splitlines()
        wire = b"".join(bytes.fromhex(line) for line in wire_lines)
        replay = ProtocolReplay()
        observed = []
        for number, (sample, record) in enumerate(zip(index["records"], parse_wire(wire, index["capture_cycle_ns"]), strict=True), 1):
            with self.subTest(line=number, message=sample["message_type"]):
                self.assertEqual((sample["wire_line"], sample["provenance"]), (number, "real"))
                self.assertEqual(len(record.raw_payload), sample["payload_bytes"])
                self.assertEqual((record.start_timestamp_us, record.end_timestamp_us),
                                 (sample["start_timestamp_us"], sample["end_timestamp_us"]))
                self.assertEqual(record.sop_bytes.hex(), sample["sop_hex"])
                self.assertEqual(record.pulse_count, sample["pulse_count"])
                self.assertEqual(record.decode_result, sample["decode_result"])
                self.assertEqual(record.decoded_data.hex(), sample["decoded_hex"])
                result, power, discovery, extended = replay.consume(record)
                self.assertIs(result.record, record)
                self.assertEqual(result.message_type.name, sample["message_type"])
                self.assertEqual(result.sop.kind, SopKind.SOP)
                self.assertEqual(result.header.raw_value, int(sample["pd_header_hex"], 16))
                self.assertEqual(result.parse_status.value, sample["base_status"])
                self.assertIs(result.crc_valid, sample["crc_valid"])
                crc = int(sample["crc_wire_hex"], 16)
                self.assertEqual(int.from_bytes(record.decoded_data[-4:], "little"), crc)
                self.assertEqual(reference_crc32(record.decoded_data[:-4]), crc)
                if sample["crc_valid"]:
                    self.assertEqual((result.crc_received, result.crc_calculated), (crc, crc))
                if result.vdm is not None:
                    self.assertEqual(result.vdm.raw_header, int(sample["vdm_header_hex"], 16))
                    self.assertEqual(result.vdm.status.value, sample["vdm_status"])
                if result.extended_message is not None:
                    ext = result.extended_message
                    self.assertEqual(ext.header.raw, int(sample["extended_header_hex"], 16))
                    self.assertEqual(ext.header.data_size, sample["declared_data_bytes"])
                    self.assertEqual(ext.chunk_payload.hex(), sample["data_hex"])
                    self.assertEqual(ext.padding.hex(), sample["padding_hex"])
                    self.assertEqual(ext.status.value, sample["extended_status"])
                observed.append((result, power, discovery, extended))

        self.assertEqual(sum(result.crc_valid is True for result, *_ in observed), 47)
        power_types = index["inquiries"]["GET_SOURCE_CAP"]["wire_lines"]
        chain = [observed[line - 1] for line in power_types]
        self.assertEqual([item[0].message_type.name for item in chain if item[0].message_type.name != "GoodCRC"],
                         ["Get_Source_Cap", "Source_Capabilities", "Request", "Accept", "PS_RDY"])
        request = next(item[1].rdo for item in chain if item[0].message_type.name == "Request")
        self.assertEqual((request.status, request.object_position, request.selected_pdo.voltage_max_mv,
                          request.operating_current_ma), (ParseStatus.VALID, 1, 5000, 3000))
        self.assertEqual(len(replay.power.source_pdos()), 7)
        self.assertIsNone(replay.power.epr_source_capabilities())
        self.assertEqual(replay.discovery.svids(responder_role=1), (0x2717,))
        mismatched = next(item[2] for item in observed if item[2].diagnostics
                          and item[2].diagnostics[0].code == "vdm_discovery_response_mismatch")
        self.assertEqual((mismatched.request.vdm.svid, mismatched.result.vdm.svid), (0x2717, 0xFF01))
        self.assertIsNone(replay.discovery.modes(0xFF01, responder_role=1))

        completed = {result.message_type.name: analysis.message.payload for result, _, _, analysis in observed
                     if analysis is not None and analysis.status == ReassemblyStatus.COMPLETE}
        self.assertEqual({name: len(data) for name, data in completed.items()},
                         {"Source_Capabilities_Extended": 25, "Status": 7, "Get_Manufacturer_Info": 2})
        malformed = next(item for item in observed if item[0].message_type.name == "Security_Request")
        result, _, _, rejected = malformed
        self.assertIsNone(result.crc_valid)
        self.assertEqual(rejected.status, ReassemblyStatus.INVALID)
        self.assertEqual({item.code for item in rejected.diagnostics}, {"invalid_unchunked_header", "extended_length"})
        self.assertIsNone(rejected.message)
        for query in ('GET_MANUFACTURER_INFO,"PORT"', "GET_DIGESTS"):
            lines = index["inquiries"][query]["wire_lines"]
            self.assertIn("Not_Supported", {observed[line - 1][0].message_type.name for line in lines})
        self.assertEqual((replay.extended.active_count, replay.extended.cached_bytes), (0, 0))
