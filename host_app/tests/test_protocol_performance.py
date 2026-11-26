import unittest

from protocol_benchmark import make_chunk_vectors, replay_chunks, replay_concurrent_chunks, replay_incomplete, replay_single
from test_extended import synthetic_extended
from test_usb_pd import synthetic_message


class ProtocolBenchmarkTests(unittest.TestCase):
    def test_synthetic_m6_load_shape_and_result_assertions(self):
        vectors = make_chunk_vectors()
        self.assertEqual(len(vectors), 4)
        for frames, payload in vectors:
            self.assertEqual((len(frames), len(payload)), (19, 260))
        measured = replay_chunks(vectors, 4)
        self.assertEqual((measured["complete"], measured["frames"]), (4, 76))
        self.assertEqual((measured["peak_cached_bytes"], measured["final_cached_bytes"]), (468, 0))

    def test_synthetic_supplemental_loads_release_contexts(self):
        addresses = ("18181811", "18180606", "18061806")
        concurrent = replay_concurrent_chunks(make_chunk_vectors(addresses), 2)
        self.assertEqual((concurrent["complete"], concurrent["frames"], concurrent["final_active"]), (6, 114, 0))
        incomplete = tuple(synthetic_extended(9, bytes(26), total=260, chunk=0, sop=sop) for sop in addresses)
        self.assertEqual(replay_incomplete(incomplete, 2)["expired"], 6)
        stats = replay_single((synthetic_message(0x83),), 3)
        self.assertEqual((stats["frames"], stats["final_cached_bytes"]), (3, 0))
