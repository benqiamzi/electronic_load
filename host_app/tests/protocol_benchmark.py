"""Reproduce the M6 baseline and run M7 offline performance scenarios."""

import argparse
from dataclasses import replace
import json
from pathlib import Path
import platform
from statistics import median
import sys
from time import perf_counter
import tracemalloc

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, parse_capture
from electronic_load_gui.protocols.usb_pd.extended import CHUNK_DATA_SIZE, MAX_EXTENDED_DATA_SIZE
from electronic_load_gui.protocols.usb_pd.models import ReassemblyStatus

from test_extended import synthetic_extended
from test_usb_pd import synthetic_message
from test_vdm import synthetic_vdm_fixture


M6_TRANSFERS = 4000


def make_chunk_vectors(addresses=("18181811", "18180606", "18181811", "18180606")):
    variants = []
    for variant, sop in enumerate(addresses):
        data = bytes((index + variant) % 256 for index in range(MAX_EXTENDED_DATA_SIZE))
        frames = []
        for number, first in enumerate(range(0, MAX_EXTENDED_DATA_SIZE, CHUNK_DATA_SIZE)):
            if number:
                frames.append(synthetic_extended(9, chunk=number, request=True, sender=0,
                                                 sop=sop, message_id=(number - 1) % 8))
            frames.append(synthetic_extended(9, data[first:first + CHUNK_DATA_SIZE], chunk=number,
                                             total=MAX_EXTENDED_DATA_SIZE, sop=sop, message_id=number % 8))
        variants.append((tuple(frames), data))
    return tuple(variants)


def _stats(frames, elapsed, *, complete=0, payload=0, peak=0, engine=None):
    active = engine.active_count if engine is not None else 0
    cached = engine.cached_bytes if engine is not None else 0
    if active or cached:
        raise AssertionError(f"Replay ended with {active} active transfers and {cached} source bytes")
    return {"frames": frames, "complete": complete, "seconds": elapsed,
            "frames_per_second": frames / elapsed, "us_per_frame": elapsed * 1e6 / frames,
            "payload_kib_per_second": payload / 1024 / elapsed, "peak_cached_bytes": peak,
            "final_active": active, "final_cached_bytes": cached}


def replay_chunks(variants, transfers):
    engine = ExtendedMessageReassembler()
    timestamp = 0
    peak = 0
    start = perf_counter()
    for number in range(transfers):
        frames, expected = variants[number % len(variants)]
        for frame in frames:
            timestamp += 200
            record = replace(frame, start_timestamp_us=timestamp, end_timestamp_us=timestamp)
            analysis = engine.consume(parse_capture(record))
            peak = max(peak, engine.cached_bytes)
        if analysis.status != ReassemblyStatus.COMPLETE or analysis.message.payload != expected:
            raise AssertionError(f"Payload mismatch in transfer {number}")
    elapsed = perf_counter() - start
    return _stats(transfers * len(variants[0][0]), elapsed, complete=transfers,
                  payload=transfers * MAX_EXTENDED_DATA_SIZE, peak=peak, engine=engine)


def replay_concurrent_chunks(variants, batches):
    engine = ExtendedMessageReassembler()
    timestamp = 0
    peak = 0
    complete = 0
    start = perf_counter()
    for batch in range(batches):
        # A fresh start per batch makes the same captured Message IDs reusable.
        engine.reset()
        for offset, row in enumerate(zip(*(frames for frames, _ in variants), strict=True)):
            for frame, (_, expected) in zip(row, variants, strict=True):
                timestamp += 200
                record = replace(frame, start_timestamp_us=timestamp, end_timestamp_us=timestamp)
                analysis = engine.consume(parse_capture(record))
                peak = max(peak, engine.cached_bytes)
                if offset == len(variants[0][0]) - 1:
                    if analysis.status != ReassemblyStatus.COMPLETE or analysis.message.payload != expected:
                        raise AssertionError(f"Payload mismatch in concurrent batch {batch}")
                    complete += 1
    elapsed = perf_counter() - start
    return _stats(complete * len(variants[0][0]), elapsed, complete=complete,
                  payload=complete * MAX_EXTENDED_DATA_SIZE, peak=peak, engine=engine)


def replay_single(records, count, *, extended=False):
    engine = ExtendedMessageReassembler() if extended else None
    complete = 0
    payload = 0
    start = perf_counter()
    for number in range(count):
        parsed = parse_capture(records[number % len(records)])
        if parsed.crc_valid is not True:
            raise AssertionError("Invalid benchmark capture")
        if engine is not None:
            analysis = engine.consume(parsed)
            if analysis.status != ReassemblyStatus.COMPLETE or analysis.message is None:
                raise AssertionError("Single Extended frame did not complete")
            complete += 1
            payload += len(analysis.message.payload)
    return _stats(count, perf_counter() - start, complete=complete, payload=payload, engine=engine)


def replay_incomplete(records, batches):
    engine = ExtendedMessageReassembler(timeout_us=100)
    expired = 0
    peak = 0
    start = perf_counter()
    for batch in range(batches):
        timestamp = batch * 200
        for frame in records:
            record = replace(frame, start_timestamp_us=timestamp, end_timestamp_us=timestamp)
            engine.consume(parse_capture(record))
            peak = max(peak, engine.cached_bytes)
        snapshots = engine.expire(timestamp + 100)
        if len(snapshots) != len(records) or any(not item.missing_chunks for item in snapshots):
            raise AssertionError("Incomplete captures were not released correctly")
        expired += len(snapshots)
    stats = _stats(expired, perf_counter() - start, peak=peak, engine=engine)
    return {**stats, "expired": expired}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=3, help="M6-equivalent timing repetitions")
    parser.add_argument("--output", type=Path, help="Write JSON to this file as well as stdout")
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("repeat must be positive")

    variants = make_chunk_vectors()
    equivalent = [replay_chunks(variants, M6_TRANSFERS) for _ in range(args.repeat)]
    med = median(item["seconds"] for item in equivalent)
    memory = []
    for transfers in (400, M6_TRANSFERS):
        tracemalloc.start()
        try:
            measured = replay_chunks(variants, transfers)
            current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        memory.append({**measured, "traced_current_bytes": current, "traced_peak_bytes": peak})

    ordinary = (synthetic_message(0x83), synthetic_message(0x1181, (0x0001912C,)),
                synthetic_message(0x1082, (0x10019064,)))
    vdm = tuple(synthetic_vdm_fixture(name) for name in ("discover_identity_drd_ack", "discover_svids_ack",
                                                         "discover_modes_ack", "unstructured"))
    single = tuple(synthetic_extended(2, bytes((n,)) * 7, chunk=0, message_id=n) for n in range(4))
    addresses = ("18181811", "18180606", "18061806")
    concurrent = make_chunk_vectors(addresses)
    incomplete = tuple(synthetic_extended(9, bytes(26), total=260, chunk=0, sop=sop) for sop in addresses)
    report = {
        "environment": {"platform": platform.platform(), "python": platform.python_version(),
                        "pyside6_loaded": "PySide6" in sys.modules},
        "m6_equivalent": equivalent,
        "m6_equivalent_median": _stats(M6_TRANSFERS * 19, med, complete=M6_TRANSFERS,
                                       payload=M6_TRANSFERS * MAX_EXTENDED_DATA_SIZE,
                                       peak=max(item["peak_cached_bytes"] for item in equivalent)),
        "memory": memory,
        "supplemental": {
            "ordinary_pd": replay_single(ordinary, 30000),
            "vdm_vdo": replay_single(vdm, 30000),
            "single_extended": replay_single(single, 15000, extended=True),
            "multi_chunk_sop": replay_chunks(make_chunk_vectors((addresses[0],) * 4), 1000),
            "concurrent_sops": replay_concurrent_chunks(concurrent, 500),
            "incomplete_and_expiry": replay_incomplete(incomplete, 3000),
        },
    }
    output = json.dumps(report, indent=2) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
