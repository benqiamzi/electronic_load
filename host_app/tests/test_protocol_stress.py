from dataclasses import replace
import os
from random import Random
import unittest

from electronic_load_gui.devices.drpd.capture_record import CaptureRecord
from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, VDMContext, VDORegistry, parse_capture
from electronic_load_gui.protocols.usb_pd.diagnostics import ParseStatus
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus

from protocol_benchmark import make_chunk_vectors, replay_chunks
from protocol_m7_fixtures import ProtocolReplay, parse_wire, synthetic_mixed_wire
from test_extended import parse_extended
from test_pd_session import synthetic_reset
from test_reassembly import synthetic_chunk
from test_usb_pd import synthetic_message
from test_vdm import synthetic_vdm_record
from test_vdm_context import _FULL_PAGE


FULL = os.environ.get("M7_FULL_STRESS") == "1"


class ProtocolStressTests(unittest.TestCase):
    def test_synthetic_long_mixed_replay(self):
        labels, wire, _ = synthetic_mixed_wire()
        records = tuple(parse_wire(wire))
        replay = ProtocolReplay()
        count = 100000 if FULL else 440
        complete = 0
        for number in range(count):
            offset = number % len(records)
            record = replace(records[offset], start_timestamp_us=number * 500, end_timestamp_us=number * 500 + 250)
            result, _, _, extended = replay.consume(record)
            self.assertIs(result.record, record)
            if labels[offset] == "epr_chunk_one":
                self.assertEqual(extended.status, ReassemblyStatus.COMPLETE)
                self.assertEqual(extended.epr.status, ParseStatus.VALID)
                complete += 1
        self.assertEqual(complete, (count + len(records) - labels.index("epr_chunk_one") - 1) // len(records))
        replay.power.disconnect()
        replay.discovery.disconnect()
        replay.extended.disconnect()
        self.assertIsNone(replay.discovery.identity())
        self.assertIsNone(replay.power.epr_source_capabilities())
        self.assertEqual((replay.extended.active_count, replay.extended.cached_bytes), (0, 0))

    def test_synthetic_random_bytes_and_short_bodies_preserve_original_capture(self):
        rng = Random(0x7632)
        addresses = tuple(bytes.fromhex(word) for word in
                          ("18181811", "18180606", "18061806", "07180706", "07070719", "00000000"))
        count = 100000 if FULL else 1200
        replay = ProtocolReplay()
        for number in range(count):
            if number % 4:
                raw = rng.randbytes(rng.randrange(0, 74))
            else:
                raw = b"\x8f\x90" + rng.randbytes(rng.randrange(0, 8))
            record = CaptureRecord(number * 20, number * 20, rng.choice((0, 0, 0, 1, 2, 3)),
                                   rng.choice(addresses), (), raw, b"", 10.0)
            result, _, _, _ = replay.consume(record)
            self.assertIs(result.record, record)
        self.assertEqual((replay.extended.active_count, replay.extended.cached_bytes), (0, 0))

    def test_synthetic_complete_transfer_pressure(self):
        count = 10000 if FULL else 40
        results = replay_chunks(make_chunk_vectors(), count)
        self.assertEqual((results["complete"], results["frames"]), (count, count * 19))
        self.assertEqual((results["final_active"], results["final_cached_bytes"]), (0, 0))

    def test_synthetic_duplicate_conflict_and_out_of_order_pressure(self):
        engine = ExtendedMessageReassembler()
        count = 10000 if FULL else 60
        for number in range(count):
            value = number % 256
            data = bytes((value,)) * 55
            records = tuple(synthetic_chunk(data, i, message_id=i).record for i in range(3))
            base = number * 100
            def send(index, offset):
                return engine.consume(parse_capture(replace(records[index], start_timestamp_us=base + offset)))
            self.assertEqual(send(2, 1).status, ReassemblyStatus.CONTEXT_MISSING)
            self.assertEqual(send(0, 2).status, ReassemblyStatus.PENDING)
            duplicate = send(2, 3)
            self.assertIn("extended_duplicate_chunk", {d.code for d in duplicate.diagnostics})
            if number % 2 == 0:
                finished = send(1, 4)
                self.assertEqual((finished.status, finished.message.payload), (ReassemblyStatus.COMPLETE, data))
            else:
                conflict = synthetic_chunk(bytes(((value + 1) % 256,)) * 55, 2, timestamp=base + 4)
                self.assertEqual(engine.consume(conflict).status, ReassemblyStatus.INVALID)
                self.assertEqual(send(1, 5).status, ReassemblyStatus.CONTEXT_MISSING)
            self.assertEqual((engine.active_count, engine.cached_bytes), (0, 0))
            engine.reset()

    def test_synthetic_reset_disconnect_and_role_change_cycles(self):
        engine = ExtendedMessageReassembler(timeout_us=50, max_transfers=3, max_cached_bytes=200)
        addresses = ("18181811", "18180606", "18061806")
        cycles = 1000 if FULL else 20
        for i in range(cycles):
            timestamp = i * 100
            for sop in addresses:
                engine.consume(synthetic_chunk(bytes(30), 0, sop=sop, timestamp=timestamp))
            limited = engine.consume(synthetic_chunk(bytes(30), 0, code=8, timestamp=timestamp))
            self.assertIn("extended_resource_limit", {d.code for d in limited.diagnostics})
            self.assertEqual(engine.active_count, 3)
            self.assertLessEqual(engine.cached_bytes, 200)
            swap = parse_capture(replace(synthetic_message(0x8A), start_timestamp_us=timestamp + 1))
            self.assertEqual(len(engine.consume(swap).interrupted), 1)
            if i % 3 == 0:
                self.assertEqual(len(engine.consume(synthetic_reset("07180706")).interrupted), 2)
            elif i % 3 == 1:
                self.assertEqual(len(engine.expire(timestamp + 50)), 2)
            else:
                self.assertEqual(len(engine.disconnect()), 2)
            self.assertEqual((engine.active_count, engine.cached_bytes), (0, 0))
            self.assertEqual(engine.disconnect(), ())

    def test_synthetic_decoder_failure_keeps_following_frames_available(self):
        class Broken:
            def decode(self, raw, context):
                raise ValueError("synthetic translator failure")

        registry = VDORegistry()
        registry.register(0xFF01, Broken())
        data = parse_capture(synthetic_vdm_record(0xFF01A843, 0x11223344), vdo_registry=registry)
        self.assertEqual(data.vdm.vdos[0].raw, 0x11223344)
        self.assertEqual(data.vdm.vdos[0].diagnostics[0].code, "vdo_decoder_error")
        fallback = parse_extended(30, b"opaque")
        self.assertEqual(ExtendedMessageReassembler().consume(fallback).message.payload, b"opaque")

    def test_synthetic_corrupt_svid_continuation_cannot_publish_a_truncated_list(self):
        context = VDMContext()
        prior = parse_capture(synthetic_vdm_record(0xFF00A842, 0xFF010000))
        first = parse_capture(synthetic_vdm_record(0xFF00A842, *_FULL_PAGE, message_id=1))
        malformed = parse_capture(synthetic_vdm_record(0xFF00A842, 0x23455678, message_id=2))
        last = parse_capture(synthetic_vdm_record(0xFF00A842, 0xABCD0000, message_id=3))
        context.consume(prior)
        context.consume(first)
        self.assertIs(malformed.crc_valid, True)
        self.assertEqual(malformed.vdm.status, ParseStatus.INVALID)
        context.consume(malformed)
        discarded = context.consume(last)
        self.assertEqual(discarded.status, ParseStatus.CONTEXT_MISSING)
        self.assertEqual(discarded.diagnostics[0].code, "vdm_context_missing")
        self.assertEqual(context.svids(), (0xFF01,))
        self.assertEqual(context.svid_sources(), (prior,))
        self.assertEqual(context.consume(last).status, ParseStatus.CONTEXT_MISSING)
        refresh = parse_capture(synthetic_vdm_record(0xFF00A842, 0x12090000, message_id=4))
        context.consume(refresh)
        self.assertEqual(context.svids(), (0x1209,))
