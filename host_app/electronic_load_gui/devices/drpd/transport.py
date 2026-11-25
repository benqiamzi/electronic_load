from __future__ import annotations

import logging

from PySide6.QtCore import QIODeviceBase, QObject, Signal, Slot
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo


_LOG = logging.getLogger(__name__)
_PREVIEW_BYTES = 32


class DrpdTransport(QObject):
    """Own one USB CDC port and deliver received bytes exactly as read."""

    opened = Signal(str)
    closed = Signal()
    bytes_received = Signal(bytes)
    bytes_written = Signal(bytes)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serial = QSerialPort(self)
        self._serial.readyRead.connect(self._read_available)
        self._serial.errorOccurred.connect(self._on_serial_error)
        self._connected = False

    @staticmethod
    def available_ports() -> list[QSerialPortInfo]:
        return sorted(QSerialPortInfo.availablePorts(), key=lambda port: port.portName())

    @property
    def is_open(self) -> bool:
        return self._connected

    def open(self, port_name: str, baud_rate: int = 115200) -> bool:
        self.close()
        serial = self._serial
        serial.setPortName(port_name)
        if not (
            serial.setBaudRate(baud_rate)
            and serial.setDataBits(QSerialPort.DataBits.Data8)
            and serial.setParity(QSerialPort.Parity.NoParity)
            and serial.setStopBits(QSerialPort.StopBits.OneStop)
            and serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
            and serial.open(QIODeviceBase.OpenModeFlag.ReadWrite)
            and serial.clear()
            and serial.setDataTerminalReady(True)
        ):
            error = serial.errorString()
            self.close()
            self.error_occurred.emit(f"无法打开 DRPD 串口 {port_name}: {error}")
            return False
        self._connected = True
        self.opened.emit(port_name)
        return True

    def close(self) -> None:
        was_connected = self._connected
        self._connected = False
        if self._serial.isOpen():
            self._serial.clear()
            self._serial.setDataTerminalReady(False)
            self._serial.close()
        if was_connected:
            self.closed.emit()

    def write_bytes(self, data: bytes) -> bool:
        if not self.is_open:
            self.error_occurred.emit("DRPD 串口尚未连接")
            return False
        if self._serial.write(data) != len(data):
            message = self._serial.errorString()
            self.close()
            self.error_occurred.emit(f"DRPD 串口写入不完整: {message}")
            return False
        _LOG.debug("DRPD TX %d bytes [%s]", len(data), data[:_PREVIEW_BYTES].hex(" "))
        self.bytes_written.emit(data)
        return True

    @Slot()
    def _read_available(self) -> None:
        data = bytes(self._serial.readAll())
        if self.is_open and data:
            _LOG.debug("DRPD RX %d bytes [%s]", len(data), data[:_PREVIEW_BYTES].hex(" "))
            self.bytes_received.emit(data)

    @Slot(QSerialPort.SerialPortError)
    def _on_serial_error(self, error: QSerialPort.SerialPortError) -> None:
        if not self.is_open or error == QSerialPort.SerialPortError.NoError:
            return
        message = self._serial.errorString()
        if error in (
            QSerialPort.SerialPortError.DeviceNotFoundError,
            QSerialPort.SerialPortError.PermissionError,
            QSerialPort.SerialPortError.ResourceError,
            QSerialPort.SerialPortError.ReadError,
            QSerialPort.SerialPortError.WriteError,
            QSerialPort.SerialPortError.NotOpenError,
        ):
            self.close()
        self.error_occurred.emit(f"DRPD 串口错误: {message}")
