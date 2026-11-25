"""Command-line probe for phase-one CDC and capture verification."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
import sys
from time import monotonic
from typing import TypeVar

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from .capture_record import CaptureRecord, FirmwareEvent
from .device import DrpdDevice
from .protocol_client import DrpdProtocolError, ErrorCallback
from .transport import DrpdTransport


_Result = TypeVar("_Result")


def _wait_for(submit: Callable[[Callable[[_Result], None], ErrorCallback], bool]) -> _Result:
    loop = QEventLoop()
    results: list[_Result] = []
    errors: list[DrpdProtocolError] = []

    def done(value: _Result) -> None:
        results.append(value)
        loop.quit()

    def failed(error: DrpdProtocolError) -> None:
        errors.append(error)
        loop.quit()

    if submit(done, failed) and not results and not errors:
        loop.exec()
    if errors:
        raise errors[0]
    if not results:
        raise DrpdProtocolError("DRPD 请求未提交")
    return results[0]


def _delay(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _port_details(port) -> dict:
    return {
        "port": port.portName(), "description": port.description(),
        "manufacturer": port.manufacturer(), "serial_number": port.serialNumber(),
        "vid": f"{port.vendorIdentifier():04x}" if port.hasVendorIdentifier() else None,
        "pid": f"{port.productIdentifier():04x}" if port.hasProductIdentifier() else None,
    }


def _emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=True), flush=True)


def _show_record(record: CaptureRecord | FirmwareEvent) -> None:
    if isinstance(record, FirmwareEvent):
        _emit("firmware_event", timestamp_us=record.timestamp_us, event_type=record.event_type,
              text=record.event_text, utf8_valid=record.text_encoding_valid,
              event_text_hex=record.event_text_bytes.hex(), payload_bytes=len(record.raw_payload))
        return
    _emit("capture", start_us=record.start_timestamp_us, end_us=record.end_timestamp_us,
          result=record.decode_result, sop_hex=record.sop_bytes.hex(), pulses=record.pulse_count,
          data_hex=record.decoded_data.hex(), hard_reset=record.is_hard_reset,
          payload_bytes=len(record.raw_payload))


def _probe(device: DrpdDevice, seconds: float, verify_empty: bool) -> None:
    protocol, capture = device.protocol, device.capture

    def text(command: str) -> str:
        return _wait_for(lambda done, fail: protocol.query_text(command, done, errback=fail))

    def count() -> int:
        return _wait_for(lambda done, fail: capture.get_capture_count(done, errback=fail))

    identity = text("*IDN?")
    if ",dr.pd," not in identity.lower():
        raise DrpdProtocolError(f"串口上的设备不是 Dr. PD: {identity!r}")
    cycle_time = _wait_for(lambda done, fail: capture.get_cycle_time(done, errback=fail))
    _emit("device", identity=identity, cycle_time_ns=cycle_time, queued=count())

    if seconds:
        state = text("BUS:CC:CAP:EN?")
        if state not in ("ON", "OFF"):
            raise DrpdProtocolError(f"DRPD 捕获状态无效: {state!r}")
        errors: list[str] = []
        capture.error_occurred.connect(errors.append)
        capture.capture_received.connect(_show_record)
        if state == "OFF":
            capture.start_capture()
        try:
            if text("BUS:CC:CAP:EN?") != "ON":
                raise DrpdProtocolError("DRPD 未进入捕获状态")
            capture.start_polling()
            deadline = monotonic() + seconds
            while not errors and device.transport.is_open and monotonic() < deadline:
                _delay(max(1, min(100, int((deadline - monotonic()) * 1000))))
        finally:
            capture.stop_polling()
            if state == "OFF" and device.transport.is_open:
                capture.stop_capture()
                if text("BUS:CC:CAP:EN?") != "OFF":
                    raise DrpdProtocolError("DRPD 未退出捕获状态")
        if errors or not device.transport.is_open:
            raise DrpdProtocolError(errors[0] if errors else "DRPD 在捕获过程中断开")
        _emit("capture_window_complete", queued=count(), capture_restored=state)

    if verify_empty:
        if count() != 0:
            raise DrpdProtocolError("DRPD 队列仍有记录，无法验证空队列响应")
        record = _wait_for(lambda done, fail: capture.fetch_next_capture(done, errback=fail))
        if record is not None:
            raise DrpdProtocolError("验证期间设备产生了新的捕获记录")
        _emit("empty_queue", scpi_error=-200)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", nargs="?", help="DRPD CDC port (e.g. COM15)")
    parser.add_argument("--list", action="store_true", help="list serial ports and USB IDs")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--timeout-ms", type=int, default=1000)
    parser.add_argument("--capture-seconds", type=float, default=0,
                        help="temporarily enable capture and read its queue for this duration")
    parser.add_argument("--verify-empty", action="store_true", help="verify empty-queue response")
    parser.add_argument("--wire-log", type=Path, help="write exact TX/RX chunks to a new JSONL file")
    args = parser.parse_args()
    if not isfinite(args.capture_seconds) or args.capture_seconds < 0:
        parser.error("--capture-seconds must be finite and non-negative")
    if args.baud <= 0 or args.timeout_ms <= 0:
        parser.error("--baud and --timeout-ms must be positive")
    if not args.list and not args.port:
        parser.error("specify a DRPD CDC port or use --list")
    app = QCoreApplication(sys.argv[:1])
    ports = [_port_details(port) for port in DrpdTransport.available_ports()]
    if args.list:
        for port in ports:
            _emit("port", **port)
        return 0

    device = DrpdDevice(app, timeout_ms=args.timeout_ms)
    device.transport.error_occurred.connect(lambda message: _emit("transport_error", message=message))
    port = next((item for item in ports if item["port"] == args.port), {"port": args.port})
    _emit("port", **port)
    try:
        wire_log = args.wire_log.open("x", encoding="utf-8") if args.wire_log else None
    except OSError as exc:
        _emit("error", message=str(exc))
        return 1

    def trace(direction: str, **fields) -> None:
        if wire_log is not None:
            line = {"utc": datetime.now(timezone.utc).isoformat(), "event": direction, **fields}
            wire_log.write(json.dumps(line) + "\n")
            wire_log.flush()

    if wire_log is not None:
        trace("port", **port, baud=args.baud)
        device.transport.bytes_written.connect(lambda data: trace("TX", bytes_hex=data.hex()))
        device.transport.bytes_received.connect(lambda data: trace("RX", bytes_hex=data.hex()))
    try:
        if not device.transport.open(args.port, args.baud):
            trace("error", message="port open failed")
            return 1
        _probe(device, args.capture_seconds, args.verify_empty)
        trace("passed")
        return 0
    except DrpdProtocolError as exc:
        trace("error", message=str(exc))
        _emit("error", message=str(exc))
        return 1
    finally:
        device.transport.close()
        if wire_log is not None:
            wire_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
