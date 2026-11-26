import unittest
from dataclasses import replace

from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, parse_capture
from electronic_load_gui.protocols.usb_pd.extended import CHUNK_DATA_SIZE, MAX_EXTENDED_DATA_SIZE
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus

from test_extended import parse_extended, synthetic_extended


def synthetic_chunk(payload, number, *, code=2, **header):
    start = CHUNK_DATA_SIZE * number
    return parse_extended(code, payload[start:start + CHUNK_DATA_SIZE], chunk=number, total=len(payload), **header)


class ReassemblyTests(unittest.TestCase):
    def test_synthetic_two_chunks_and_associated_request(self):
        payload = bytes(range(30))
        reassembler = ExtendedMessageReassembler()
        first = synthetic_chunk(payload, 0, message_id=6, timestamp=20)
        request = parse_extended(2, chunk=1, request=True, sender=0, message_id=3, timestamp=22)
        last = synthetic_chunk(payload, 1, message_id=7, timestamp=24)
        first_analysis = reassembler.consume(first)
        self.assertEqual(first_analysis.status, ReassemblyStatus.PENDING)
        self.assertEqual(first_analysis.message.missing_chunks, (1,))
        self.assertEqual(reassembler.consume(request).requested_chunk, 1)
        complete = reassembler.consume(last)
        self.assertEqual((complete.status, complete.message.payload), (ReassemblyStatus.COMPLETE, payload))
        self.assertEqual(complete.message.frames, (first, last))
        self.assertEqual(complete.message.requests, (request,))
        self.assertEqual(complete.message.missing_chunks, ())
        self.assertEqual(complete.message.diagnostics, ())
        self.assertEqual((reassembler.active_count, reassembler.cached_bytes), (0, 0))

    def test_synthetic_all_ten_chunks_reassemble_out_of_order(self):
        reassembler = ExtendedMessageReassembler()
        payload = bytes(n % 256 for n in range(MAX_EXTENDED_DATA_SIZE))
        numbers = (9, 0, 2, 4, 6, 8, 1, 3, 5, 7)
        for arrival, number in enumerate(numbers):
            analysis = reassembler.consume(synthetic_chunk(payload, number, message_id=number % 8, timestamp=arrival))
            if arrival == 0:
                self.assertEqual(analysis.status, ReassemblyStatus.CONTEXT_MISSING)
                self.assertEqual(analysis.message.payload, b"")
                self.assertIn("extended_chunk_order", {item.code for item in analysis.diagnostics})
        self.assertEqual(analysis.status, ReassemblyStatus.COMPLETE)
        self.assertEqual(analysis.message.payload, payload)
        self.assertEqual(analysis.message.received_chunks, tuple(range(10)))
        self.assertEqual({item.code for item in analysis.message.diagnostics},
                         {"extended_chunk_order", "extended_request_unobserved"})

    def test_synthetic_duplicate_active_and_completed_chunks(self):
        reassembler = ExtendedMessageReassembler()
        payload = bytes(range(30))
        first = synthetic_chunk(payload, 0)
        last = synthetic_chunk(payload, 1, message_id=1)
        reassembler.consume(first)
        duplicate = reassembler.consume(first)
        self.assertEqual({issue.code for issue in duplicate.diagnostics}, {"extended_duplicate_chunk"})
        self.assertEqual(duplicate.message.received_chunks, (0,))
        self.assertEqual(reassembler.consume(last).message.payload, payload)
        duplicate_last = reassembler.consume(last)
        self.assertEqual({issue.code for issue in duplicate_last.diagnostics}, {"extended_duplicate_chunk"})
        self.assertIsNone(duplicate_last.message)
        self.assertEqual(reassembler.active_count, 0)
        changed = reassembler.consume(synthetic_chunk(bytes(30), 1, message_id=2))
        self.assertEqual(changed.status, ReassemblyStatus.CONTEXT_MISSING)

    def test_synthetic_conflict_preserves_preceding_frames_and_new_zero_starts_stream(self):
        for conflicting in (synthetic_chunk(bytes((1,)) * 29, 1), synthetic_chunk(bytes((1,)) * 30, 0)):
            with self.subTest(info=conflicting.extended_message.header):
                reassembler = ExtendedMessageReassembler()
                first = synthetic_chunk(bytes(30), 0)
                reassembler.consume(first)
                invalid = reassembler.consume(conflicting)
                self.assertEqual(invalid.status, ReassemblyStatus.INVALID)
                self.assertEqual(invalid.message.frames, (first,))
                self.assertIn("extended_chunk_conflict", {d.code for d in invalid.diagnostics})
                self.assertEqual(reassembler.cached_bytes, 0)
        reassembler = ExtendedMessageReassembler()
        reassembler.consume(synthetic_chunk(bytes(30), 0, message_id=0))
        data = bytes((9,)) * 30
        restart = reassembler.consume(synthetic_chunk(data, 0, message_id=2))
        self.assertEqual(restart.interrupted[0].diagnostics[-1].code, "extended_restarted")
        self.assertEqual(reassembler.consume(synthetic_chunk(data, 1, message_id=3)).message.payload, data)

    def test_synthetic_truncated_chunk_cannot_complete_transfer(self):
        reassembler = ExtendedMessageReassembler()
        data = bytes(range(30))
        reassembler.consume(synthetic_chunk(data, 0))
        record = synthetic_extended(2, data[26:], total=30, chunk=1)
        bad = parse_capture(replace(record, decoded_data=record.decoded_data[:-5]))
        self.assertEqual(reassembler.consume(bad).status, ReassemblyStatus.PARTIAL)
        snapshot, = reassembler.expire(1_000_000)
        self.assertEqual(snapshot.missing_chunks, (1,))
        self.assertEqual(snapshot.payload, data[:26])
