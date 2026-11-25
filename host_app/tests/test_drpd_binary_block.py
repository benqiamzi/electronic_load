import unittest

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockError, BinaryBlockParser


class BinaryBlockTests(unittest.TestCase):
    def test_1020_byte_block_at_every_split(self) -> None:
        payload = bytes(range(255)) * 4
        frame = b"#41020" + payload + b"\n"
        for index in range(len(frame)):
            with self.subTest(index=index):
                parser = BinaryBlockParser()
                self.assertEqual(parser.feed(frame[:index]), [])
                self.assertEqual(parser.feed(frame[index:]), [payload])
                self.assertFalse(parser.has_pending_data)

    def test_coalesced_blocks_and_partial_next_header(self) -> None:
        parser = BinaryBlockParser()
        self.assertEqual(parser.feed(b"#10\n#13\r\n\x00\n#2"), [b"", b"\r\n\x00"])
        self.assertTrue(parser.has_pending_data)
        self.assertEqual(parser.feed(b"01Z\n"), [b"Z"])

    def test_incomplete_payload_and_missing_terminator(self) -> None:
        parser = BinaryBlockParser()
        self.assertEqual(parser.feed(b"#12\x00"), [])
        self.assertEqual(parser.feed(b"\n"), [])
        self.assertTrue(parser.has_pending_data)
        with self.assertRaises(BinaryBlockError):
            parser.feed(b"\r")
        self.assertFalse(parser.has_pending_data)

    def test_rejects_bad_headers_and_length_limit(self) -> None:
        parser = BinaryBlockParser(max_payload_bytes=2)
        for frame in (b"X", b"#0", b"#x", b"#2x", b"#214", b"#13"):
            with self.subTest(frame=frame):
                with self.assertRaises(BinaryBlockError):
                    parser.feed(frame)
                self.assertFalse(parser.has_pending_data)
        self.assertEqual(parser.feed(b"#12ab\n"), [b"ab"])
