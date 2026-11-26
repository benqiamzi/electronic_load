import json
from dataclasses import replace
from struct import pack

from electronic_load_gui.devices.drpd.binary_block import BinaryBlockParser
from electronic_load_gui.devices.drpd.capture_record import CaptureRecordParser
from electronic_load_gui.protocols.usb_pd import ExtendedMessageReassembler, PDSessionContext, VDMContext, parse_capture
from electronic_load_gui.protocols.usb_pd.extended import CHUNK_DATA_SIZE

from test_extended import synthetic_extended
from test_usb_pd import FIXTURES, synthetic_message


def read_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def capture_wire(record):
    """Build a synthetic SCPI block with the same layout as a DRPD capture."""
    widths = record.pulse_widths
    prefix = pack("<QQI4sI", record.start_timestamp_us, record.end_timestamp_us,
                  record.decode_result, record.sop_bytes, len(widths))
    block = prefix + pack(f"<{len(widths)}H", *widths) + pack("<I", len(record.decoded_data)) + record.decoded_data
    size = str(len(block)).encode("ascii")
    return b"#" + str(len(size)).encode("ascii") + size + block + b"\n"


def synthetic_mixed_wire():
    synthetic = read_fixture("usb_pd_m7_synthetic.json")
    assert synthetic["provenance"] == "synthetic"
    epr_index = read_fixture("usb_pd_extended_synthetic.json")
    epr = next(case for case in epr_index["cases"] if case["kind"] == "epr_capabilities")
    cap_data = b"".join(int(word, 16).to_bytes(4, "little") for word in epr["pdo_hex"])
    labels = []
    blocks = []
    for offset, step in enumerate(synthetic["steps"], 1):
        if "header" in step:
            words = tuple(int(word, 16) for word in step.get("words", ()))
            frame = synthetic_message(int(step["header"], 16), words)
        elif "reset" in step:
            frame = replace(synthetic_message(0, sop=step["reset"]), decoded_data=b"")
        else:
            if "epr_chunk" in step:
                number = step["epr_chunk"]
                start = CHUNK_DATA_SIZE * number
                frame = synthetic_extended(step["type"], cap_data[start:start + CHUNK_DATA_SIZE],
                                           chunk=number, total=len(cap_data), message_id=step.get("message_id", 0))
            else:
                data = bytes(step["repeat_data"]) if "repeat_data" in step else bytes.fromhex(step.get("data_hex", ""))
                frame = synthetic_extended(step["type"], data, chunk=step.get("chunk"), total=step.get("total"),
                                           sop=step.get("sop", "18181811"), request=step.get("request", False),
                                           sender=step.get("sender", 1))
        frame = replace(frame, start_timestamp_us=offset * 500,
                        end_timestamp_us=offset * 500 + 250, pulse_widths=(10, 13, 256))
        labels.append(step["id"])
        blocks.append(capture_wire(frame))
    return labels, b"".join(blocks), synthetic["expected"]


def parse_wire(wire, cycle=10.0, *, fragment_size=97):
    parser = BinaryBlockParser()
    for start in range(0, len(wire), fragment_size):
        for block in parser.feed(wire[start:start + fragment_size]):
            yield CaptureRecordParser.parse(block, cycle)


class ProtocolReplay:
    def __init__(self):
        self.power = PDSessionContext()
        self.discovery = VDMContext()
        self.extended = ExtendedMessageReassembler()

    def consume(self, record):
        result = parse_capture(record)
        power = self.power.consume(result)
        discovery = self.discovery.consume(result)
        extended = self.extended.consume(result)
        if extended is not None:
            self.power.consume_extended(extended)
        return result, power, discovery, extended
