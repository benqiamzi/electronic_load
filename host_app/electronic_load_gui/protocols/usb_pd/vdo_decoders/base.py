from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ..models import VDMInfo
from ..sop import SopKind


@dataclass(frozen=True, slots=True)
class VDODecodeContext:
    sop: SopKind
    revision: int
    vdm: VDMInfo
    vdo_index: int
    mode_position: int | None


class VDODecoder(Protocol):
    def decode(self, raw: int, context: VDODecodeContext) -> Mapping[str, object] | None:
        """Return SVID-specific fields or None to keep the object opaque."""
        ...


class VDORegistry:
    def __init__(self) -> None:
        self._decoders: dict[tuple[int, int | None, int | None], VDODecoder] = {}

    def register(
        self, svid: int, decoder: VDODecoder, *, command: int | None = None, position: int | None = None,
    ) -> None:
        if not 1 <= svid <= 0xFFFF:
            raise ValueError("SVID must be a nonzero 16-bit value.")
        if command is not None and not 0 <= command <= 31:
            raise ValueError("VDM command must be a 5-bit value.")
        if position is not None and not 0 <= position <= 7:
            raise ValueError("VDM Object Position must be a 3-bit value.")
        self._decoders[svid, command, position] = decoder

    def get(self, svid: int, *, command: int | None = None, position: int | None = None) -> VDODecoder | None:
        """Prefer command and position, then command alone, position alone, and SVID alone."""
        for key in ((svid, command, position), (svid, command, None), (svid, None, position), (svid, None, None)):
            if key in self._decoders:
                return self._decoders[key]
        return None
