import unittest

from electronic_load_gui.protocols.usb_pd import VDORegistry, decode_vdm, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import VDMCommand
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from test_vdm import synthetic_vdm_fixture, synthetic_vdm_record


class SyntheticVendorDecoder:
    def __init__(self, name):
        self.name = name

    def decode(self, raw, context):
        return {"decoder": self.name, "test_value": raw & 0xFF, "sop": context.sop,
                "command": context.vdm.command, "position": context.mode_position,
                "vdo_index": context.vdo_index, "revision": context.revision}


class SyntheticBrokenDecoder:
    def decode(self, raw, context):
        raise RuntimeError("synthetic decoder failure")


class VDOTests(unittest.TestCase):
    def test_synthetic_identity_drd_fields_and_placement(self):
        vdm = parse_capture(synthetic_vdm_fixture("discover_identity_drd_ack")).vdm
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(tuple(item.category for item in vdm.vdos),
                         ("id_header", "cert_stat", "product", "ufp", "identity_pad", "dfp"))
        identity, cert, product, ufp, _, dfp = vdm.vdos
        self.assertEqual(dict(identity.decoded_fields), {
            "usb_vid": 0x1209, "usb_host_capable": True, "usb_device_capable": True,
            "modal_operation_supported": True, "product_type_ufp": 2, "product_type_dfp": 2,
            "connector_type": 2,
        })
        self.assertEqual(dict(cert.decoded_fields), {"xid": 0x12345678})
        self.assertEqual(dict(product.decoded_fields), {"usb_pid": 0x4321, "bcd_device": 0x0123})
        self.assertEqual((ufp.raw, dfp.raw), (0x60000001, 0x20000020))
        self.assertIsNone(ufp.decoded_fields)

    def test_synthetic_cable_product_type_layout(self):
        vdm = parse_capture(synthetic_vdm_fixture("discover_identity_passive_cable_ack")).vdm
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(vdm.vdos[0].decoded_fields["product_type_cable"], 3)
        self.assertNotIn("product_type_dfp", vdm.vdos[0].decoded_fields)
        self.assertEqual(vdm.vdos[-1].category, "passive_cable")

        for product_type, words, expected in (
            (4, (0x02482010, 0x11002000), ("active_cable_1", "active_cable_2")),
            (6, (0x00000001,), ("vpd",)),
        ):
            with self.subTest(product_type=product_type):
                identity = (product_type << 27) | (3 << 21) | 0x1209
                vdm = decode_vdm((0xFF00A041, identity, 0, 0x00010100, *words), sop=SopKind.SOP_PRIME)
                self.assertEqual(vdm.status, ParseStatus.VALID)
                self.assertEqual(tuple(vdo.category for vdo in vdm.vdos[3:]), expected)

    def test_synthetic_legacy_identity_does_not_guess_optional_layout(self):
        vdm = decode_vdm((0xFF008041, 0x18001209, 0, 0, 0xFFFFFFFE), sop=SopKind.SOP_PRIME, revision=1)
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(vdm.vdos[-1].category, "identity_type_raw")
        self.assertNotIn("connector_type", vdm.vdos[0].decoded_fields)
        self.assertIn("vdo_legacy_identity", {issue.code for issue in vdm.diagnostics})

    def test_synthetic_identity_truncated_extra_invalid_type_and_pad(self):
        for words, status, code in (
            ((0x00401209, 0), ParseStatus.PARTIAL, "vdo_truncated"),
            ((0x00401209, 0, 0, 0x12345678), ParseStatus.INVALID, "vdo_unexpected_count"),
            ((0xD5401209, 0, 0, 0x60000001, 0x20000020, 0), ParseStatus.INVALID, "vdo_identity_pad"),
            ((0x20401209, 0, 0, 0x12345678), ParseStatus.INVALID, "vdo_product_type"),
            ((0x00411209, 0, 0), ParseStatus.INVALID, "vdo_reserved_bits_nonzero"),
        ):
            with self.subTest(code=code):
                vdm = decode_vdm((0xFF00A841, *words))
                self.assertEqual(vdm.status, status)
                self.assertIn(code, {item.code for item in vdm.diagnostics})
                self.assertEqual(tuple(vdo.raw for vdo in vdm.vdos), words)

    def test_synthetic_svid_order_odd_even_and_full_pages(self):
        odd = parse_capture(synthetic_vdm_fixture("discover_svids_ack")).vdm
        self.assertEqual((odd.status, odd.discovered_svids, odd.svids_terminated),
                         (ParseStatus.VALID, (0xFF01, 0x1209, 0x28DE), True))
        even = decode_vdm((0xFF00A842, 0xABCD1209, 0x00000000))
        self.assertEqual((even.discovered_svids, even.svids_terminated), ((0xABCD, 0x1209), True))
        full = decode_vdm((0xFF00A842, 0x01010102, 0x01030104, 0x01050106,
                           0x01070108, 0x0109010A, 0x010B010C))
        self.assertEqual((full.status, full.discovered_svids, full.svids_terminated),
                         (ParseStatus.VALID, tuple(range(0x0101, 0x010D)), False))
        terminal = decode_vdm((0xFF00A842, 0))
        self.assertEqual((terminal.status, terminal.discovered_svids, terminal.svids_terminated),
                         (ParseStatus.VALID, (), True))
        self.assertEqual(dict(odd.vdos[0].decoded_fields), {"svid_high": 0xFF01, "svid_low": 0x1209})

    def test_synthetic_svid_bad_termination_and_duplicates(self):
        for words, issue in (
            ((0x0000FF01,), "vdo_svid_termination"),
            ((0xABCD0000, 0xFF010000), "vdo_svid_termination"),
            ((0xABCD1209,), "vdo_svid_termination"),
            ((0xABCDABCD, 0), "vdo_duplicate_svid"),
        ):
            with self.subTest(words=words):
                vdm = decode_vdm((0xFF00A842, *words))
                self.assertEqual(vdm.status, ParseStatus.INVALID)
                self.assertIn(issue, {d.code for d in vdm.diagnostics})
                self.assertEqual(tuple(vdo.raw for vdo in vdm.vdos), words)

    def test_synthetic_modes_and_mode_command_payloads_keep_object_positions(self):
        modes = parse_capture(synthetic_vdm_fixture("discover_modes_ack")).vdm
        self.assertEqual(modes.svid, 0xFF01)
        self.assertEqual(modes.status, ParseStatus.VALID)
        self.assertEqual([(vdo.mode_position, vdo.raw) for vdo in modes.vdos], [(1, 0x405), (2, 0x12345678)])
        self.assertTrue(all(vdo.category == "mode" and vdo.decoded_fields is None for vdo in modes.vdos))
        for header in (0x1209AA04, 0x1209AA06):
            vdm = decode_vdm((header, 0xAABBCCDD))
            self.assertEqual(vdm.status, ParseStatus.VALID)
            self.assertEqual((vdm.vdos[0].category, vdm.vdos[0].mode_position, vdm.vdos[0].raw),
                             ("mode_payload", 2, 0xAABBCCDD))
        exit_mode = decode_vdm((0x1209AA05,))
        self.assertEqual((exit_mode.status, exit_mode.object_position, exit_mode.vdos), (ParseStatus.VALID, 2, ()))

    def test_synthetic_vdo_counts_by_command_and_type(self):
        for header, words in (
            (0xFF00A801, (1,)), (0xFF00A842, ()), (0xFF01A843, ()), (0xFF00A882, (1,)),
            (0xFF00A8C3, (1,)), (0xFF01A904, (1, 2)), (0xFF01A944, (1,)),
            (0xFF01A905, (1,)), (0xFF01A906, (1, 2)),
        ):
            with self.subTest(header=header):
                vdm = decode_vdm((header, *words))
                self.assertEqual(vdm.status, ParseStatus.INVALID)
                self.assertIn("vdo_unexpected_count", {item.code for item in vdm.diagnostics})
                self.assertEqual(tuple(vdo.raw for vdo in vdm.vdos), words)

    def test_synthetic_registry_dispatch_precedence_and_fallback(self):
        registry = VDORegistry()
        registry.register(0x1209, SyntheticVendorDecoder("vendor"))
        registry.register(0x1209, SyntheticVendorDecoder("command"), command=VDMCommand.DISCOVER_MODES)
        registry.register(0x1209, SyntheticVendorDecoder("mode2"), command=VDMCommand.DISCOVER_MODES, position=2)
        record = synthetic_vdm_record(0x1209A843, 0xABCDEF01, 0xFEDCBA02, sop="18180606")
        decoded = parse_capture(record, vdo_registry=registry).vdm
        self.assertEqual([vdo.vendor_fields["decoder"] for vdo in decoded.vdos], ["command", "mode2"])
        self.assertEqual(dict(decoded.vdos[1].vendor_fields), {
            "decoder": "mode2", "test_value": 2, "sop": SopKind.SOP_PRIME,
            "command": 3, "position": 2, "vdo_index": 2, "revision": 2,
        })
        self.assertIsNone(decoded.vdos[0].decoded_fields)
        self.assertIsNone(parse_capture(record).vdm.vdos[0].vendor_fields)
        unrelated = decode_vdm((0x1234A843, 0xABCDEF01), registry=registry)
        self.assertEqual(unrelated.vdos[0].raw, 0xABCDEF01)
        self.assertIn("vdo_decoder_unavailable", {issue.code for issue in unrelated.diagnostics})
        unstructured = decode_vdm((0x12090003, 0x11), registry=registry)
        self.assertEqual(unstructured.vdos[0].vendor_fields["decoder"], "vendor")
        specific = decode_vdm((0x1209A819, 0x2C), registry=registry)
        self.assertEqual(specific.vdos[0].vendor_fields["test_value"], 0x2C)

    def test_synthetic_vendor_exception_preserves_core_decode_and_next_object(self):
        registry = VDORegistry()
        registry.register(0xFF01, SyntheticBrokenDecoder(), position=1)
        registry.register(0xFF01, SyntheticVendorDecoder("next"), position=2)
        vdm = parse_capture(synthetic_vdm_fixture("discover_modes_ack"), vdo_registry=registry).vdm
        self.assertEqual(vdm.status, ParseStatus.VALID)
        self.assertEqual(vdm.vdos[0].raw, 0x405)
        self.assertIsNone(vdm.vdos[0].vendor_fields)
        self.assertEqual({item.code for item in vdm.vdos[0].diagnostics}, {"vdo_decoder_error"})
        self.assertEqual(vdm.vdos[1].vendor_fields["decoder"], "next")
