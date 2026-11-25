"""Run the phase-one DRPD and electronic-load regression in a single Qt process."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import ExitStack
from math import isfinite
from time import monotonic

from PySide6.QtCore import QCoreApplication

from electronic_load_gui.device import ElectronicLoadDevice
from electronic_load_gui.devices.drpd.__main__ import _delay, _emit, _wait_for
from electronic_load_gui.devices.drpd.capture_record import CaptureRecord, DecodeResult
from electronic_load_gui.devices.drpd.device import DrpdDevice
from electronic_load_gui.domain import MeasurementSnapshot


def _wait_until(condition: Callable[[], bool], message: str, errors: list[str]) -> None:
    deadline = monotonic() + 5
    while not condition():
        if errors:
            raise RuntimeError(errors[0])
        if monotonic() >= deadline:
            raise RuntimeError(message)
        _delay(20)


def verify(
    drpd: DrpdDevice,
    load: ElectronicLoadDevice,
    drpd_port: str,
    load_port: str,
    voltage: float,
    tolerance: float,
) -> None:
    load_errors: list[str] = []
    drpd_errors: list[str] = []
    load_identities: list[str] = []
    measurements: list[MeasurementSnapshot] = []
    packets: list[CaptureRecord] = []

    load.error_occurred.connect(load_errors.append)
    load.identity_changed.connect(load_identities.append)
    load.measurements_updated.connect(measurements.append)
    drpd.transport.error_occurred.connect(drpd_errors.append)
    drpd.capture.error_occurred.connect(drpd_errors.append)

    def record_received(record: object) -> None:
        if isinstance(record, CaptureRecord) and record.decode_result == DecodeResult.SUCCESS:
            packets.append(record)

    drpd.capture.capture_received.connect(record_received)

    def query(command: str) -> str:
        return _wait_for(lambda done, fail: drpd.protocol.query_text(command, done, errback=fail))

    def restore_capture() -> None:
        drpd.capture.stop_capture()
        if query("BUS:CC:CAP:EN?") != "OFF":
            raise RuntimeError("DRPD 捕获开关恢复失败")

    with ExitStack() as cleanup:
        cleanup.callback(drpd.transport.close)
        cleanup.callback(load.disconnect_device)
        if not drpd.transport.open(drpd_port):
            raise RuntimeError(f"无法打开 {drpd_port}")
        identity = query("*IDN?")
        if ",dr.pd," not in identity.lower():
            raise RuntimeError(f"{drpd_port} 返回了非 Dr. PD 设备身份 {identity!r}")

        load.connect_to(load_port)
        _wait_until(
            lambda: bool(load.is_connected and measurements),
            "电子负载身份或电压采样未确认",
            load_errors,
        )
        cycle = _wait_for(lambda done, fail: drpd.capture.get_cycle_time(done, errback=fail))
        initial_count = _wait_for(lambda done, fail: drpd.capture.get_capture_count(done, errback=fail))
        capture_state = query("BUS:CC:CAP:EN?")
        if capture_state not in ("ON", "OFF"):
            raise RuntimeError(f"DRPD 捕获状态无效 {capture_state!r}")
        if capture_state == "OFF":
            cleanup.callback(restore_capture)
            drpd.capture.start_capture()
            if query("BUS:CC:CAP:EN?") != "ON":
                raise RuntimeError("DRPD 未进入捕获状态")

        cleanup.callback(drpd.capture.stop_polling)
        drpd.capture.start_polling()
        if query("SINK:STATUS?") == "PE_SNK_READY":
            drpd.protocol.command("SINK:INQ GET_SOURCE_CAP")

        measurements.clear()
        _wait_until(
            lambda: len(packets) >= 2 and any(packet.decoded_data for packet in packets)
            and len(measurements) >= 3,
            "未同时采到至少两条 PD 捕获记录和三次电子负载电压读数",
            drpd_errors,
        )
        if load_errors or drpd_errors or not (load.is_connected and drpd.transport.is_open):
            raise RuntimeError(next(iter(load_errors + drpd_errors), "回归期间设备断开"))
        measured = [sample.voltage_v for sample in measurements]
        if any(abs(reading - voltage) > tolerance for reading in measured):
            raise RuntimeError(f"参考电压为 {voltage:g} V，实测范围 {min(measured):g}～{max(measured):g} V")

    _emit(
        "dual_voltage_regression_passed",
        drpd_port=drpd_port,
        drpd_identity=identity,
        cycle_time_ns=cycle,
        initial_capture_count=initial_count,
        packet_count=len(packets),
        load_port=load_port,
        load_identity=load_identities[0],
        measurements=len(measured),
        reference_voltage_v=voltage,
        voltage_min_v=min(measured),
        voltage_max_v=max(measured),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("drpd_port")
    parser.add_argument("load_port")
    parser.add_argument("--voltage", type=float, required=True, help="Reference voltage in volts")
    parser.add_argument("--tolerance", type=float, required=True, help="Allowed error in volts")
    args = parser.parse_args()
    if args.drpd_port.casefold() == args.load_port.casefold():
        parser.error("DRPD 和电子负载必须使用不同的串口")
    if not isfinite(args.voltage) or not isfinite(args.tolerance) or args.tolerance <= 0:
        parser.error("参考电压必须为有限值，误差上限必须为有限正数")

    app = QCoreApplication([])
    try:
        verify(
            DrpdDevice(app), ElectronicLoadDevice(app), args.drpd_port, args.load_port,
            args.voltage, args.tolerance,
        )
    except RuntimeError as exc:
        _emit("dual_regression_failed", message=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
