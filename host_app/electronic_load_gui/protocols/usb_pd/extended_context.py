from collections import OrderedDict
from dataclasses import replace
from hashlib import sha256

from .diagnostics import ParseDiagnostic, ParseStatus
from .epr import decode_epr_source_capabilities
from .extended import chunk_count
from .models import (
    CaptureResult, ExtendedAnalysis, ExtendedDirection, ExtendedKind, PDMessageResult,
    ReassembledExtendedMessage, ReassemblyStatus, ResetResult,
)
from .reassembly import ChunkTransfer, TransferKey, capture_cost
from .sop import SopKind


_CABLE_ADDRESSES = frozenset((SopKind.SOP_PRIME, SopKind.SOP_DOUBLE_PRIME))
_REVERSE = {
    ExtendedDirection.SOURCE: ExtendedDirection.SINK, ExtendedDirection.SINK: ExtendedDirection.SOURCE,
    ExtendedDirection.CABLE: ExtendedDirection.PORT, ExtendedDirection.PORT: ExtendedDirection.CABLE,
}


def _direction(result: PDMessageResult) -> ExtendedDirection:
    if result.sop.kind == SopKind.SOP:
        return ExtendedDirection.SOURCE if result.header.power_role else ExtendedDirection.SINK
    return ExtendedDirection.CABLE if result.header.cable_plug else ExtendedDirection.PORT


def _diagnostic(code: str, message: str) -> ParseDiagnostic:
    return ParseDiagnostic("reassembly", code, message)


def _chunk_signature(result: PDMessageResult) -> tuple[int, int, bytes]:
    info = result.extended_message
    return result.header.message_id, info.header.data_size, sha256(info.chunk_payload).digest()


class ExtendedMessageReassembler:
    """Reassemble capture records using device time and bounded per-link state."""

    def __init__(self, *, timeout_us: int = 1_000_000, max_transfers: int = 16,
                 max_cached_bytes: int = 256 * 1024) -> None:
        if min(timeout_us, max_transfers, max_cached_bytes) <= 0:
            raise ValueError("Reassembly limits must be positive.")
        self._timeout_us = timeout_us
        self._max_transfers = max_transfers
        self._max_cached_bytes = max_cached_bytes
        self._active: dict[TransferKey, ChunkTransfer] = {}
        self._recent: OrderedDict[TransferKey, tuple[int, dict[int, tuple[int, int, bytes]]]] = OrderedDict()
        self._cached_bytes = 0
        self._clock_us = 0

    @property
    def active_count(self) -> int:
        return len(self._active)

    @property
    def cached_bytes(self) -> int:
        return self._cached_bytes

    def _drop(self, key: TransferKey) -> ChunkTransfer:
        transfer = self._active.pop(key)
        self._cached_bytes -= transfer.retained_bytes
        return transfer

    def _clear(self, addresses: frozenset[SopKind] | None, issue: ParseDiagnostic) -> tuple[ReassembledExtendedMessage, ...]:
        interrupted = tuple(self._drop(key).snapshot(ReassemblyStatus.PARTIAL, issue)
                            for key in tuple(self._active) if addresses is None or key.sop in addresses)
        for key in tuple(self._recent):
            if addresses is None or key.sop in addresses:
                del self._recent[key]
        return interrupted

    def reset(self, sop: SopKind | None = None) -> tuple[ReassembledExtendedMessage, ...]:
        return self._clear(None if sop is None else frozenset((sop,)),
                           _diagnostic("extended_reset", "Reset ended the incomplete Extended Message."))

    def disconnect(self) -> tuple[ReassembledExtendedMessage, ...]:
        self._clock_us = 0
        return self._clear(None, _diagnostic("extended_disconnect", "Disconnect ended the incomplete Extended Message."))

    def expire(self, timestamp_us: int) -> tuple[ReassembledExtendedMessage, ...]:
        self._clock_us = max(self._clock_us, timestamp_us)
        cutoff = self._clock_us - self._timeout_us
        for key, (finished, _) in tuple(self._recent.items()):
            if finished <= cutoff:
                del self._recent[key]
        issue = _diagnostic("extended_timeout", "The capture window ended with missing Extended Message chunks.")
        expired = []
        for key, transfer in tuple(self._active.items()):
            if transfer.updated_us <= cutoff:
                expired.append(self._drop(key).snapshot(ReassemblyStatus.PARTIAL, issue))
                self._remember(transfer, complete=False)
        return tuple(expired)

    def _analysis(self, result: PDMessageResult, status: ReassemblyStatus, issues=(), *,
                  message: ReassembledExtendedMessage | None = None, requested: int | None = None) -> ExtendedAnalysis:
        epr = decode_epr_source_capabilities(message) if message is not None and requested is None else None
        return ExtendedAnalysis(result, status, message, requested, tuple(issues), epr)

    def _request(self, result: PDMessageResult, key: TransferKey) -> ExtendedAnalysis:
        number = result.extended_message.header.chunk_number
        transfer = self._active.get(replace(key, direction=_REVERSE[key.direction]))
        if transfer is None:
            issue = _diagnostic("extended_request_context", "No Extended Message is active in the reverse direction.")
            return self._analysis(result, ReassemblyStatus.CONTEXT_MISSING, (issue,), requested=number)
        if number >= transfer.count:
            issue = _diagnostic("extended_request_range", "Requested Chunk Number is outside the active transfer.")
            return self._analysis(result, ReassemblyStatus.INVALID, (issue,), requested=number)
        if number not in transfer.requests:
            cost = capture_cost(result)
            if self._cached_bytes + cost > self._max_cached_bytes:
                return self._limit(result, requested=number)
            transfer.requests[number] = result
            transfer.retained_bytes += cost
            transfer.updated_us = self._clock_us
            self._cached_bytes += cost
        issues = ()
        if number - 1 not in transfer.frames:
            issues = (_diagnostic("extended_request_predecessor_missing", "The chunk preceding the requested Chunk Number was not observed."),)
        return self._analysis(result, ReassemblyStatus.PENDING, issues, message=transfer.snapshot(ReassemblyStatus.PENDING),
                              requested=number)

    def _limit(self, result: PDMessageResult, *, requested: int | None = None) -> ExtendedAnalysis:
        issue = _diagnostic("extended_resource_limit", "The capture exceeds the active reassembly cache limits.")
        return self._analysis(result, ReassemblyStatus.INVALID, (issue,), requested=requested)

    def _remember(self, transfer: ChunkTransfer, *, complete: bool) -> None:
        signatures = {n: _chunk_signature(frame) for n, frame in transfer.frames.items()} if complete else {}
        self._recent[transfer.key] = (self._clock_us, signatures)
        self._recent.move_to_end(transfer.key)
        if len(self._recent) > self._max_transfers:
            self._recent.popitem(last=False)

    def _chunk(self, result: PDMessageResult, key: TransferKey) -> ExtendedAnalysis:
        info = result.extended_message
        number, size = info.header.chunk_number, info.header.data_size
        transfer = self._active.get(key)
        interrupted = ()
        if transfer is not None:
            previous = transfer.frames.get(number)
            if number == 0 and previous is not None and previous.header.message_id != result.header.message_id:
                issue = _diagnostic("extended_restarted", "A new Chunk 0 ended the previous incomplete transfer.")
                interrupted = (self._drop(key).snapshot(ReassemblyStatus.PARTIAL, issue),)
                transfer = None
            elif transfer.data_size != size or (previous is not None and previous.extended_message.chunk_payload != info.chunk_payload):
                issue = _diagnostic("extended_chunk_conflict", "Chunk Data Size or content conflicts with the active transfer.")
                message = self._drop(key).snapshot(ReassemblyStatus.INVALID, issue)
                self._remember(transfer, complete=False)
                return self._analysis(result, ReassemblyStatus.INVALID, (issue,), message=message)
            elif previous is not None:
                issue = _diagnostic("extended_duplicate_chunk", "An identical Chunk has already been received.")
                return self._analysis(result, ReassemblyStatus.PENDING, (issue,),
                                      message=transfer.snapshot(ReassemblyStatus.PENDING, issue))

        if transfer is None and key in self._recent:
            _, signatures = self._recent[key]
            if signatures.get(number) == _chunk_signature(result):
                issue = _diagnostic("extended_duplicate_chunk", "This Chunk belongs to an already completed transfer.")
                return self._analysis(result, ReassemblyStatus.COMPLETE, (issue,))
            if number:
                issue = _diagnostic("extended_new_chunk_context", "A subsequent transfer needs a new Chunk 0 after the previous transfer ended.")
                return self._analysis(result, ReassemblyStatus.CONTEXT_MISSING, (issue,))

        if transfer is None and chunk_count(size) == 1:
            finished = ChunkTransfer(key, size, self._clock_us, frames={0: result})
            self._remember(finished, complete=True)
            message = finished.snapshot(ReassemblyStatus.COMPLETE)
            return replace(self._analysis(result, ReassemblyStatus.COMPLETE, message=message), interrupted=interrupted)
        cost = capture_cost(result)
        if self._cached_bytes + cost > self._max_cached_bytes or (transfer is None and self.active_count >= self._max_transfers):
            return replace(self._limit(result), interrupted=interrupted)
        if transfer is None:
            self._recent.pop(key, None)
            transfer = ChunkTransfer(key, size, self._clock_us)
            self._active[key] = transfer
        next_expected = next((n for n in range(transfer.count) if n not in transfer.frames), transfer.count)
        issues = []
        if number != next_expected:
            issues.append(_diagnostic("extended_chunk_order", "Chunk arrived before one or more preceding chunks."))
        if number and number not in transfer.requests:
            issues.append(_diagnostic("extended_request_unobserved", "No matching Chunk Request was observed before this chunk."))
        transfer.diagnostics.extend(issues)
        transfer.frames[number] = result
        transfer.retained_bytes += cost
        transfer.updated_us = self._clock_us
        self._cached_bytes += cost

        if len(transfer.frames) == transfer.count:
            status = ReassemblyStatus.COMPLETE
            self._remember(self._drop(key), complete=True)
        else:
            status = ReassemblyStatus.PENDING if 0 in transfer.frames else ReassemblyStatus.CONTEXT_MISSING
        return replace(self._analysis(result, status, issues, message=transfer.snapshot(status)),
                       interrupted=interrupted)

    def _consume_extended(self, result: PDMessageResult) -> ExtendedAnalysis:
        info = result.extended_message
        if (result.crc_valid is not True or result.header_status != ParseStatus.VALID
                or info.status != ParseStatus.VALID or result.message_type.status == ParseStatus.INVALID):
            status = ReassemblyStatus.PARTIAL if result.parse_status == ParseStatus.PARTIAL else ReassemblyStatus.INVALID
            return self._analysis(result, status, result.diagnostics)
        key = TransferKey(result.sop.kind, info.message_type, _direction(result))
        if info.kind == ExtendedKind.REQUEST_CHUNK:
            return self._request(result, key)
        if info.kind == ExtendedKind.UNCHUNKED:
            message = ReassembledExtendedMessage(key.sop, key.message_type, key.direction, info.header.data_size,
                                                 info.chunk_payload, (), (), ReassemblyStatus.COMPLETE, (result,))
            analysis = self._analysis(result, ReassemblyStatus.COMPLETE, message=message)
            if key in self._active:
                issue = _diagnostic("extended_restarted", "An Unchunked Message ended the previous incomplete transfer.")
                transfer = self._drop(key)
                self._remember(transfer, complete=False)
                return replace(analysis, interrupted=(transfer.snapshot(ReassemblyStatus.PARTIAL, issue),))
            return analysis
        return self._chunk(result, key)

    def consume(self, result: CaptureResult) -> ExtendedAnalysis | None:
        timestamp = getattr(result.record, "start_timestamp_us", getattr(result.record, "timestamp_us", 0))
        interrupted = self.expire(timestamp)
        if isinstance(result, ResetResult):
            if result.sop.kind == SopKind.HARD_RESET:
                interrupted += self.reset()
            elif result.sop.kind == SopKind.CABLE_RESET:
                interrupted += self._clear(_CABLE_ADDRESSES, _diagnostic("extended_cable_reset", "Cable Reset ended the cable transfer."))
        elif isinstance(result, PDMessageResult):
            if result.extended_message is not None:
                analysis = self._consume_extended(result)
                return replace(analysis, interrupted=interrupted + analysis.interrupted)
            if result.parse_status == ParseStatus.VALID and result.crc_valid is True:
                if result.message_type.name in ("Soft_Reset", "PR_Swap", "FR_Swap"):
                    interrupted += self.reset(result.sop.kind)
                elif result.message_type.name == "Data_Reset_Complete":
                    interrupted += self._clear(_CABLE_ADDRESSES, _diagnostic("extended_data_reset", "Data Reset ended the cable transfer."))
        return ExtendedAnalysis(result, ReassemblyStatus.PARTIAL, interrupted=interrupted) if interrupted else None
