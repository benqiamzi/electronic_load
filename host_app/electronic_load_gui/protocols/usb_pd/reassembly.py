from dataclasses import dataclass, field

from .diagnostics import ParseDiagnostic
from .extended import chunk_count
from .models import ExtendedDirection, PDMessageResult, ReassembledExtendedMessage, ReassemblyStatus
from .sop import SopKind


@dataclass(frozen=True, slots=True)
class TransferKey:
    sop: SopKind
    message_type: int
    direction: ExtendedDirection


def capture_cost(frame: PDMessageResult) -> int:
    """Account for retained capture bytes and sampled 16-bit pulse entries."""
    record = frame.record
    return len(record.raw_payload) + len(record.decoded_data) + len(record.sop_bytes) + 2 * record.pulse_count


@dataclass(slots=True)
class ChunkTransfer:
    key: TransferKey
    data_size: int
    updated_us: int
    frames: dict[int, PDMessageResult] = field(default_factory=dict)
    requests: dict[int, PDMessageResult] = field(default_factory=dict)
    diagnostics: list[ParseDiagnostic] = field(default_factory=list)
    retained_bytes: int = 0

    @property
    def count(self) -> int:
        return chunk_count(self.data_size)

    def snapshot(self, status: ReassemblyStatus, *diagnostics: ParseDiagnostic) -> ReassembledExtendedMessage:
        received = tuple(sorted(self.frames))
        missing = tuple(number for number in range(self.count) if number not in self.frames)
        # The contiguous prefix is safe for partial semantic decoding. Other bytes remain in frames.
        prefix_end = missing[0] if missing else self.count
        data = b"".join(self.frames[number].extended_message.chunk_payload for number in range(prefix_end))
        return ReassembledExtendedMessage(
            self.key.sop, self.key.message_type, self.key.direction, self.data_size, data, received, missing, status,
            tuple(self.frames[number] for number in received), tuple(self.requests.values()),
            tuple(self.diagnostics) + diagnostics,
        )
