"""Measure a real DRPD capture through the USB PD workspace."""

import argparse
from dataclasses import asdict
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
from time import monotonic
import tracemalloc

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication

from electronic_load_gui.devices.drpd.__main__ import _delay
from electronic_load_gui.services.capture_file import CaptureReader
from electronic_load_gui.usb_pd_workspace import UsbPdWorkspace


def wait_until(condition, description):
    deadline = monotonic() + 10
    while not condition():
        if monotonic() >= deadline:
            raise RuntimeError(description)
        _delay(20)


def add_record(digest, record):
    payload = record.raw_payload
    digest.update(len(payload).to_bytes(8, "little"))
    digest.update(payload)


def verify(workspace, port, output, seconds, inquiry_interval):
    device = workspace.device
    errors = []
    received = sha256()
    notices = []
    last_tick = monotonic()
    peak_tick_gap = 0.0

    def heartbeat():
        nonlocal last_tick, peak_tick_gap
        now = monotonic()
        peak_tick_gap = max(peak_tick_gap, now - last_tick)
        last_tick = now

    def record_batch(batch, _token):
        for event in batch:
            add_record(received, event.record)

    device.error.connect(errors.append)
    device.batch_ready.connect(record_batch)
    workspace.notice.connect(notices.append)
    device.connect_port(port)
    wait_until(lambda: device.state.connection in ("connected", "error"), "等待连接超时")
    if errors or device.state.connection != "connected":
        raise RuntimeError(errors[0] if errors else "DRPD 连接失败")
    if device.state.device_capture is not False:
        raise RuntimeError("设备已有捕获会话")

    timer = QTimer(interval=20)
    timer.timeout.connect(heartbeat)
    tracemalloc.start()
    device.start_capture.emit()
    try:
        wait_until(lambda: device.state.capture == "running" or errors, "等待捕获启动超时")
        started = monotonic()
        last_tick = next_inquiry = started
        timer.start()
        while monotonic() - started < seconds and not errors:
            if inquiry_interval and monotonic() >= next_inquiry and device.state.sink_state == "PE_SNK_READY":
                device.query_source.emit()
                next_inquiry = monotonic() + inquiry_interval
            _delay(50)
        elapsed = monotonic() - started
    finally:
        try:
            device.stop_capture.emit()
            wait_until(
                lambda: device.state.capture == "idle" and device.state.metrics.pending == 0,
                "等待停止及排空超时",
            )
        finally:
            timer.stop()
            _, peak_memory = tracemalloc.get_traced_memory()
            tracemalloc.stop()

    state = device.state
    export_times = {}
    archive = output / "capture.drpd"
    if state.metrics.archived:
        for kind, suffix in (("raw", "drpd"), ("csv", "csv")):
            path = output / f"capture.{suffix}"
            export_started = monotonic()
            workspace.export_capture("live", kind, path)
            wait_until(lambda: not workspace._exporting, f"{kind} 导出超时")
            if not path.is_file():
                raise RuntimeError(notices[-1] if notices else f"{kind} 导出失败")
            export_times[kind] = monotonic() - export_started

    archived = sha256()
    read_back = 0
    if archive.is_file():
        with CaptureReader(archive) as reader:
            for entry in reader:
                if entry.record is not None:
                    add_record(archived, entry.record)
                    read_back += 1
    metrics = state.metrics
    archive_integrity = (
        metrics.received == metrics.archived == read_back > 0
        and received.digest() == archived.digest()
    )
    results = {
        "port": port,
        "firmware": state.firmware,
        "capture_seconds": elapsed,
        "source_inquiry_interval_seconds": inquiry_interval,
        "device_capture_after_stop": state.device_capture,
        "device_queue_after_stop": state.queue,
        "device_queue_peak": state.peak_queue,
        "device_loss_count": None,
        "host": asdict(metrics),
        "analyzed": metrics.analyzed,
        "crc_invalid": state.crc_errors,
        "diagnostics": state.diagnostic_count,
        "displayed": workspace.live_model.rowCount(),
        "scrolled_out": workspace.live_model.hidden,
        "read_back": read_back,
        "archive_integrity": archive_integrity,
        "python_traced_peak_bytes": peak_memory,
        "ui_20ms_timer_max_gap_seconds": peak_tick_gap,
        "export_seconds": export_times,
        "errors": errors,
    }
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=float, default=1800)
    parser.add_argument("--inquiry-interval", type=float, default=0,
                        help="Seconds between Get_Source_Cap requests while the existing sink is ready")
    args = parser.parse_args()
    if not isfinite(args.seconds) or args.seconds <= 0:
        parser.error("--seconds must be a finite positive value")
    if not isfinite(args.inquiry_interval) or args.inquiry_interval < 0:
        parser.error("--inquiry-interval must be finite and nonnegative")
    args.output.mkdir(parents=True)
    app = QApplication([])
    settings = QSettings(str(args.output / "ui.ini"), QSettings.Format.IniFormat)
    workspace = UsbPdWorkspace(settings, lambda _port: False)
    try:
        result = verify(workspace, args.port, args.output, args.seconds, args.inquiry_interval)
        report = json.dumps(result, ensure_ascii=True, indent=2)
        (args.output / "metrics.json").write_text(report + "\n", encoding="utf-8")
        print(report)
        return int(not (
            result["archive_integrity"] and not result["errors"]
            and result["device_capture_after_stop"] is False and result["device_queue_after_stop"] == 0
            and result["analyzed"] == result["read_back"]
        ))
    finally:
        workspace.shutdown()
        wait_until(lambda: not workspace.running, "等待工作线程退出超时")
        app.processEvents()


if __name__ == "__main__":
    raise SystemExit(main())
