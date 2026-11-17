from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .serial_transport import SerialTransport


ResponseCallback = Callable[[str], None]
ErrorCallback = Callable[[str], None]


@dataclass(slots=True)
class _Request:
    command: str
    expects_response: bool
    callback: ResponseCallback | None = None
    errback: ErrorCallback | None = None
    timeout_ms: int = 700
    key: str | None = None


class ProtocolClient(QObject):
    error_occurred = Signal(str)
    unsolicited_line = Signal(str)

    def __init__(self, transport: SerialTransport, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._transport = transport
        self._queue: deque[_Request] = deque()
        self._pending: _Request | None = None
        self._keys: set[str] = set()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._on_timeout)
        self._transport.line_received.connect(self._on_line)
        self._transport.closed.connect(self.clear)

    @property
    def is_idle(self) -> bool:
        return self._pending is None and not self._queue

    def command(self, command: str, *, key: str | None = None) -> bool:
        return self._enqueue(_Request(command=command, expects_response=False, key=key))

    def query(
        self,
        command: str,
        callback: ResponseCallback,
        *,
        errback: ErrorCallback | None = None,
        timeout_ms: int = 700,
        key: str | None = None,
    ) -> bool:
        return self._enqueue(
            _Request(
                command=command,
                expects_response=True,
                callback=callback,
                errback=errback,
                timeout_ms=timeout_ms,
                key=key,
            )
        )

    def _enqueue(self, request: _Request) -> bool:
        if request.key is not None and request.key in self._keys:
            return False
        if request.key is not None:
            self._keys.add(request.key)
        self._queue.append(request)
        self._pump()
        return True

    def clear(self) -> None:
        self._timer.stop()
        self._queue.clear()
        self._pending = None
        self._keys.clear()

    def _pump(self) -> None:
        if self._pending is not None or not self._queue:
            return
        request = self._queue.popleft()
        if not self._transport.write_line(request.command):
            self._finish_with_error(request, f"发送命令失败: {request.command}")
            QTimer.singleShot(0, self._pump)
            return
        if not request.expects_response:
            self._remove_key(request)
            QTimer.singleShot(0, self._pump)
            return
        self._pending = request
        self._timer.start(request.timeout_ms)

    @Slot(str)
    def _on_line(self, line: str) -> None:
        request = self._pending
        if request is None:
            self.unsolicited_line.emit(line)
            return
        self._timer.stop()
        self._pending = None
        self._remove_key(request)
        if request.callback is not None:
            try:
                request.callback(line)
            except Exception as exc:  # callbacks are the protocol boundary
                self.error_occurred.emit(f"处理 {request.command} 响应失败: {exc}")
        self._pump()

    @Slot()
    def _on_timeout(self) -> None:
        request = self._pending
        if request is None:
            return
        self._pending = None
        message = f"命令响应超时: {request.command}"
        self._remove_key(request)
        self._finish_with_error(request, message)
        self._pump()

    def _finish_with_error(self, request: _Request, message: str) -> None:
        self._remove_key(request)
        if request.errback is not None:
            request.errback(message)
        else:
            self.error_occurred.emit(message)

    def _remove_key(self, request: _Request) -> None:
        if request.key is not None:
            self._keys.discard(request.key)
