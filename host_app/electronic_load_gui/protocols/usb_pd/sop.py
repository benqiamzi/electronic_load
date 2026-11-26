from dataclasses import dataclass
from enum import StrEnum


class SopKind(StrEnum):
    SOP = "SOP"
    SOP_PRIME = "SOP'"
    SOP_DOUBLE_PRIME = "SOP''"
    SOP_PRIME_DEBUG = "SOP' Debug"
    SOP_DOUBLE_PRIME_DEBUG = "SOP'' Debug"
    HARD_RESET = "Hard Reset"
    CABLE_RESET = "Cable Reset"
    UNKNOWN = "Unknown"


# USB PD R3.2 V1.1 Tables 5.1 and 5.5–5.12. The numbers are the
# 4b5b K-code values stored as bytes by DRPD.
_ORDERED_SETS = {
    bytes.fromhex("18 18 18 11"): SopKind.SOP,
    bytes.fromhex("18 18 06 06"): SopKind.SOP_PRIME,
    bytes.fromhex("18 06 18 06"): SopKind.SOP_DOUBLE_PRIME,
    bytes.fromhex("18 19 19 06"): SopKind.SOP_PRIME_DEBUG,
    bytes.fromhex("18 19 06 11"): SopKind.SOP_DOUBLE_PRIME_DEBUG,
    bytes.fromhex("07 07 07 19"): SopKind.HARD_RESET,
    bytes.fromhex("07 18 07 06"): SopKind.CABLE_RESET,
}

_MESSAGE_SETS = (SopKind.SOP, SopKind.SOP_PRIME, SopKind.SOP_DOUBLE_PRIME)


@dataclass(frozen=True, slots=True)
class SopInfo:
    raw_bytes: bytes
    kind: SopKind
    matched_symbols: int
    candidates: tuple[SopKind, ...] = ()

    @property
    def is_message(self) -> bool:
        return self.kind in _MESSAGE_SETS


def classify_sop(raw: bytes) -> SopInfo:
    """Recognize exact ordered sets and unambiguous three-symbol SOPs."""
    match = _ORDERED_SETS.get(raw)
    if match is not None:
        return SopInfo(raw, match, 4)
    if len(raw) != 4:
        return SopInfo(raw, SopKind.UNKNOWN, 0)

    # The spec permits 3-of-4 matching. Require a unique candidate so
    # ordering in the lookup table cannot decide the packet's address.
    candidates = tuple(
        kind for pattern, kind in _ORDERED_SETS.items()
        if sum(observed == expected for observed, expected in zip(raw, pattern)) == 3
    )
    if len(candidates) == 1 and candidates[0] in _MESSAGE_SETS:
        return SopInfo(raw, candidates[0], 3)
    return SopInfo(raw, SopKind.UNKNOWN, 3 if candidates else 0, candidates)
