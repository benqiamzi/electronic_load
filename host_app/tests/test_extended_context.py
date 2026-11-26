import unittest
from dataclasses import replace
from random import Random

from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, parse_capture
from electronic_load_gui.protocols.usb_pd.models import ExtendedDirection, ReassemblyStatus
from electronic_load_gui.protocols.usb_pd.sop import SopKind

from test_extended import parse_extended
from test_pd_session import synthetic_reset
from test_reassembly import synthetic_chunk
from test_usb_pd import synthetic_message


class ExtendedContextTests(unittest.TestCase):
    def test_synthetic_simultaneous_addresses_types_and_directions_do_not_mix(self):
        engine = ExtendedMessageReassembler()
        streams = ({"code": 2}, {"code": 2, "sender": 0}, {"code": 8},
                   {"code": 2, "sop": "18180606"}, {"code": 2, "sop": "18061806"})
        for index, stream in enumerate(streams, 1):
            engine.consume(synthetic_chunk(bytes((index,)) * 28, 0, **stream))
        self.assertEqual(engine.active_count, len(streams))
        for index, stream in reversed(tuple(enumerate(streams, 1))):
            complete = engine.consume(synthetic_chunk(bytes((index,)) * 28, 1, **stream))
            self.assertEqual(complete.message.payload, bytes((index,)) * 28)

    def test_synthetic_reverse_request_range_and_already_seen_chunk(self):
        engine = ExtendedMessageReassembler()
        enough = bytes(60)
        engine.consume(synthetic_chunk(enough, 0))
        engine.consume(synthetic_chunk(enough, 2))
        for wrong in (parse_extended(2, chunk=2, request=True),
                      parse_extended(8, chunk=2, request=True, sender=0),
                      parse_extended(2, chunk=2, request=True, sender=0, sop="18180606")):
            self.assertEqual(engine.consume(wrong).status, ReassemblyStatus.CONTEXT_MISSING)
        out_of_range = engine.consume(parse_extended(2, chunk=3, request=True, sender=0))
        self.assertEqual(out_of_range.diagnostics[0].code, "extended_request_range")
        reverse = parse_extended(2, chunk=2, request=True, sender=0)
        response = engine.consume(reverse)
        self.assertEqual(response.requested_chunk, 2)
        self.assertIn(2, response.message.received_chunks)
        self.assertEqual(response.message.direction, ExtendedDirection.SOURCE)
        self.assertEqual(response.diagnostics[0].code, "extended_request_predecessor_missing")
        self.assertEqual(engine.consume(synthetic_chunk(enough, 1)).message.requests, (reverse,))

    def test_synthetic_timer_advances_by_capture_and_exposes_unanswered_request(self):
        engine = ExtendedMessageReassembler(timeout_us=100)
        data = bytes(30)
        engine.consume(synthetic_chunk(data, 0, timestamp=10))
        request = parse_extended(2, chunk=1, request=True, sender=0, timestamp=11)
        engine.consume(request)
        self.assertEqual(engine.expire(110), ())
        snapshot, = engine.expire(111)
        self.assertEqual(snapshot.missing_chunks, (1,))
        self.assertEqual(snapshot.requests, (request,))
        self.assertEqual(snapshot.diagnostics[-1].code, "extended_timeout")
        self.assertEqual((engine.active_count, engine.cached_bytes), (0, 0))
        late = engine.consume(synthetic_chunk(data, 1, timestamp=113))
        self.assertEqual(late.status, ReassemblyStatus.CONTEXT_MISSING)
        self.assertEqual(engine.active_count, 0)
        engine.consume(synthetic_chunk(data, 0, timestamp=120))
        control = parse_capture(replace(synthetic_message(0x83), start_timestamp_us=220))
        self.assertEqual(engine.consume(control).interrupted[0].diagnostics[-1].code, "extended_timeout")

    def test_synthetic_reset_boundaries_and_disconnect(self):
        engine = ExtendedMessageReassembler()
        data = bytes(30)
        for sop in ("18181811", "18180606", "18061806"):
            engine.consume(synthetic_chunk(data, 0, sop=sop))
        cable = engine.consume(synthetic_reset("07180706"))
        self.assertEqual({msg.sop for msg in cable.interrupted}, {SopKind.SOP_PRIME, SopKind.SOP_DOUBLE_PRIME})
        self.assertEqual(engine.active_count, 1)
        self.assertIsNone(engine.consume(synthetic_reset("07070719", decode_result=2)))
        data_reset = parse_capture(synthetic_message(0x8F))
        self.assertIsNone(engine.consume(data_reset))
        engine.consume(synthetic_chunk(data, 0, sop="18180606"))
        self.assertEqual(engine.consume(data_reset).interrupted[0].sop, SopKind.SOP_PRIME)
        soft = parse_capture(synthetic_message(0x8D))
        self.assertEqual(engine.consume(soft).interrupted[0].sop, SopKind.SOP)
        engine.consume(synthetic_chunk(data, 0))
        self.assertEqual(len(engine.consume(synthetic_reset("07070719")).interrupted), 1)
        engine.consume(synthetic_chunk(data, 0, timestamp=10_000))
        self.assertEqual(engine.disconnect()[0].diagnostics[-1].code, "extended_disconnect")
        orphan = engine.consume(synthetic_chunk(data, 1))
        self.assertEqual(orphan.status, ReassemblyStatus.CONTEXT_MISSING)

    def test_synthetic_limits_bound_retained_frames_and_requests(self):
        data = bytes(30)
        first = synthetic_chunk(data, 0)
        engine = ExtendedMessageReassembler(max_transfers=1)
        engine.consume(first)
        extra = engine.consume(synthetic_chunk(data, 0, code=8))
        self.assertEqual(extra.diagnostics[0].code, "extended_resource_limit")
        self.assertEqual(engine.active_count, 1)
        bounded = ExtendedMessageReassembler(max_cached_bytes=engine.cached_bytes)
        bounded.consume(first)
        request = parse_extended(2, chunk=1, request=True, sender=0)
        self.assertEqual(bounded.consume(request).diagnostics[0].code, "extended_resource_limit")
        self.assertEqual(bounded.cached_bytes, engine.cached_bytes)
        bounded.disconnect()
        self.assertEqual(bounded.cached_bytes, 0)

    def test_synthetic_unchunked_and_single_chunk_can_complete_at_cache_limit(self):
        engine = ExtendedMessageReassembler(max_transfers=1)
        engine.consume(synthetic_chunk(bytes(30), 0))
        single = engine.consume(parse_extended(8, b"single", chunk=0))
        self.assertEqual(single.message.payload, b"single")
        self.assertEqual(engine.active_count, 1)
        unchunked = engine.consume(parse_extended(2, b"unchunked"))
        self.assertEqual(unchunked.message.payload, b"unchunked")
        self.assertEqual(unchunked.interrupted[0].missing_chunks, (1,))
        self.assertEqual((engine.active_count, engine.cached_bytes), (0, 0))

    def test_synthetic_mixed_replay_and_corrupt_input_remain_bounded(self):
        rng = Random(76)
        engine = ExtendedMessageReassembler(timeout_us=40, max_transfers=3, max_cached_bytes=350)
        addresses = ("18181811", "18180606", "18061806")
        for timestamp in range(600):
            number = rng.randrange(3)
            record = synthetic_chunk(bytes((timestamp % 256,)) * 60, number, code=rng.choice((2, 8, 9)),
                                     sop=rng.choice(addresses), sender=rng.randrange(2),
                                     message_id=timestamp % 8, timestamp=timestamp).record
            if timestamp % 3 == 0:
                record = replace(record, decoded_data=record.decoded_data[:rng.randrange(len(record.decoded_data))])
            engine.consume(parse_capture(record))
            self.assertLessEqual(engine.active_count, 3)
            self.assertLessEqual(engine.cached_bytes, 350)
        engine.expire(700)
        self.assertEqual((engine.active_count, engine.cached_bytes), (0, 0))
