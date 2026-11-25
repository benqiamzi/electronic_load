from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
import re

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot

from .binary_block import BinaryBlockError, BinaryBlockParser, DEFAULT_MAX_PAYLOAD_BYTES
from .transport import DrpdTransport


class DrpdProtocolError(RuntimeError):
    """A DRPD request could not complete."""


class ScpiDeviceError(DrpdProtocolError):
    def __init__(self, code: int, response: str) -> None:
        super().__init__(response)
        self.code = code


ErrorCallback = Callable[[DrpdProtocolError], None]
_MAX_TEXT_BYTES = 4096
_MAX_COMMAND_BYTES = 512
_DEVICE_ERROR = re.compile(r"(-[0-9]{1,9})(?:,.*)?")


class _Response(Enum):
    NONE = auto()
    TEXT = auto()
    BINARY = auto()


@dataclass(slots=True)
class _Request:
    command: str
    wire_bytes: bytes
    response: _Response
    callback: Callable[..., None] | None
    errback: ErrorCallback | None
    timeout_ms: int
    key: str | None


class DrpdProtocolClient(QObject):
    """Serialize SCPI requests on one untagged stream.

    A timeout or framing error invalidates the session. Reopen the port to send
    more requests. This lets DTR reset the device stream before another query.
    """

    error_occurred = Signal(str)
    disconnected = Signal()

    def __init__(
        self,
        transport: DrpdTransport,
        parent: QObject | None = None,
        *,
        timeout_ms: int = 1000,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> None:
        super().__init__(parent)
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._transport = transport
        self._timeout_ms = timeout_ms
        self._queue: deque[_Request] = deque()
        self._keys: set[str] = set()
        self._pending: _Request | None = None
        self._block_parser = BinaryBlockParser(max_payload_bytes)
        self._text_buffer = bytearray()

        self._timeout = QTimer(self, singleShot=True)
        self._timeout.setTimerType(Qt.TimerType.PreciseTimer)
        self._timeout.timeout.connect(self._on_timeout)
        self._send_next = QTimer(self, singleShot=True, interval=0)
        self._send_next.timeout.connect(self._pump)
        transport.bytes_received.connect(self._on_bytes)
        transport.closed.connect(self._on_closed)

    @property
    def is_idle(self) -> bool:
        return self._pending is None and not self._queue

    def command(
        self, command: str, *, callback: Callable[[], None] | None = None,
        errback: ErrorCallback | None = None, key: str | None = None,
    ) -> bool:
        return self._enqueue(command, _Response.NONE, callback, errback, None, key)

    def query_text(
        self, command: str, callback: Callable[[str], None], *,
        errback: ErrorCallback | None = None, timeout_ms: int | None = None,
        key: str | None = None,
    ) -> bool:
        return self._enqueue(command, _Response.TEXT, callback, errback, timeout_ms, key)

    def query_binary(
        self, command: str, callback: Callable[[bytes], None], *,
        errback: ErrorCallback | None = None, timeout_ms: int | None = None,
        key: str | None = None,
    ) -> bool:
        return self._enqueue(command, _Response.BINARY, callback, errback, timeout_ms, key)

    def _enqueue(
        self, command: str, response: _Response, callback: Callable[..., None] | None,
        errback: ErrorCallback | None, timeout_ms: int | None, key: str | None,
    ) -> bool:
        try:
            wire_bytes = command.strip(" \t").encode("ascii")
        except UnicodeEncodeError:
            wire_bytes = b""
        if not 0 < len(wire_bytes) <= _MAX_COMMAND_BYTES or any(
            byte != 9 and not 32 <= byte <= 126 for byte in wire_bytes
        ):
            self._report_error(errback, DrpdProtocolError("DRPD 命令必须是单行 ASCII"))
            return False
        if not self._transport.is_open:
            self._report_error(errback, DrpdProtocolError("DRPD 串口尚未连接"))
            return False
        if timeout_ms is not None and timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        if key is not None:
            if key in self._keys:
                return False
            self._keys.add(key)
        request = _Request(command, wire_bytes + b"\n", response, callback, errback,
                           timeout_ms or self._timeout_ms, key)
        self._queue.append(request)
        self._schedule_next()
        return True

    def clear(self) -> None:
        """Cancel queued work and close the session if a response was in flight."""
        error = DrpdProtocolError("DRPD 请求已取消")
        if self._pending is not None:
            self._fail_session(error)
        else:
            for request in self._take_requests():
                self._report_error(request.errback, error)

    def _schedule_next(self) -> None:
        if self._pending is None and self._queue:
            self._send_next.start()

    @Slot()
    def _pump(self) -> None:
        if self._pending is not None or not self._queue:
            return
        request = self._queue.popleft()
        self._pending = request
        if not self._transport.write_bytes(request.wire_bytes):
            if self._pending is request:
                self._fail_session(DrpdProtocolError(f"DRPD 命令发送失败: {request.command}"))
            return
        if self._pending is not request:  # A synchronous transport failure already ended it.
            return
        if request.response is _Response.NONE:
            self._finish_request()
        else:
            self._timeout.start(request.timeout_ms)

    @Slot(bytes)
    def _on_bytes(self, data: bytes) -> None:
        if not data or not self._transport.is_open:
            return
        request = self._pending
        if request is None or request.response is _Response.NONE:
            self._fail_session(DrpdProtocolError("DRPD 收到无对应请求的响应"))
            return
        try:
            if request.response is _Response.TEXT or self._text_buffer or (
                not self._block_parser.has_pending_data and data.startswith(b"-")
            ):
                line = self._read_text(data)
                if line is None:
                    return
                if request.response is _Response.BINARY:
                    match = _DEVICE_ERROR.fullmatch(line)
                    if match is None:
                        raise DrpdProtocolError("DRPD 在二进制查询中返回了意外文本")
                    error = ScpiDeviceError(int(match[1]), line)
                    self._finish_request(error=error)
                else:
                    self._finish_request(line)
                return

            blocks = self._block_parser.feed(data)
            if not blocks:
                return
            if len(blocks) != 1 or self._block_parser.has_pending_data:
                raise DrpdProtocolError("DRPD 在一项查询中返回了额外的数据")
            self._finish_request(blocks[0])
        except (BinaryBlockError, UnicodeDecodeError, DrpdProtocolError) as exc:
            self._fail_session(DrpdProtocolError(f"{request.command}: {exc}"))

    def _read_text(self, data: bytes) -> str | None:
        self._text_buffer.extend(data)
        terminator = self._text_buffer.find(b"\n")
        if len(self._text_buffer) > _MAX_TEXT_BYTES:
            raise DrpdProtocolError("DRPD 文本响应过长")
        if self._text_buffer.startswith(b"#"):
            raise DrpdProtocolError("DRPD 在文本查询中返回了二进制块")
        if terminator < 0:
            return None
        if terminator != len(self._text_buffer) - 1:
            raise DrpdProtocolError("DRPD 在一项查询中返回了额外的数据")
        line = bytes(self._text_buffer[:terminator]).removesuffix(b"\r")
        if any(byte != 9 and not 32 <= byte <= 126 for byte in line):
            raise DrpdProtocolError("DRPD 文本响应含有非 ASCII 文本字节")
        return line.decode("ascii")

    def _finish_request(
        self, value: str | bytes | None = None, *, error: DrpdProtocolError | None = None,
    ) -> None:
        request = self._pending
        assert request is not None
        self._reset_response()
        if request.key is not None:
            self._keys.discard(request.key)
        if error is not None:
            self._report_error(request.errback, error)
        elif request.callback is not None:
            try:
                if request.response is _Response.NONE:
                    request.callback()
                else:
                    request.callback(value)
            except Exception as exc:
                self._report_error(request.errback, DrpdProtocolError(f"{request.command}: {exc}"))
        self._schedule_next()

    @Slot()
    def _on_timeout(self) -> None:
        if self._pending is not None:
            self._fail_session(DrpdProtocolError(f"DRPD 响应超时: {self._pending.command}"))

    @Slot()
    def _on_closed(self) -> None:
        requests = self._take_requests()
        self.disconnected.emit()
        for request in requests:
            self._report_error(request.errback, DrpdProtocolError(f"DRPD 已断开: {request.command}"))

    def _fail_session(self, error: DrpdProtocolError) -> None:
        requests = self._take_requests()
        self._transport.close()
        if not requests:
            self.error_occurred.emit(str(error))
        for request in requests:
            self._report_error(request.errback, error)

    def _take_requests(self) -> list[_Request]:
        requests = list(self._queue)
        if self._pending is not None:
            requests.insert(0, self._pending)
        self._reset_response()
        self._send_next.stop()
        self._queue.clear()
        self._keys.clear()
        return requests

    def _reset_response(self) -> None:
        self._timeout.stop()
        self._pending = None
        self._block_parser.reset()
        self._text_buffer.clear()

    def _report_error(self, errback: ErrorCallback | None, error: DrpdProtocolError) -> None:
        if errback is None:
            self.error_occurred.emit(str(error))
            return
        try:
            errback(error)
        except Exception as exc:
            self.error_occurred.emit(f"{error}: {exc}")
