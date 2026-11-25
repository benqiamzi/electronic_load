from __future__ import annotations

from PySide6.QtCore import QObject

from .binary_block import DEFAULT_MAX_PAYLOAD_BYTES
from .capture_client import CaptureClient
from .protocol_client import DrpdProtocolClient
from .transport import DrpdTransport


class DrpdDevice(QObject):
    """Own the independent CDC, SCPI and capture clients for one DRPD board."""

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        timeout_ms: int = 1000,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
        poll_interval_ms: int = 100,
        max_records_per_drain: int = 32,
    ) -> None:
        super().__init__(parent)
        self.transport = DrpdTransport(self)
        self.protocol = DrpdProtocolClient(
            self.transport, self, timeout_ms=timeout_ms, max_payload_bytes=max_payload_bytes,
        )
        self.capture = CaptureClient(
            self.protocol, self, poll_interval_ms=poll_interval_ms,
            max_records_per_drain=max_records_per_drain,
        )
