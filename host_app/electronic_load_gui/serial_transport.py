from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QIODeviceBase, QObject, Signal, Slot
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo


@dataclass(frozen=True, slots=True)
class PortDescriptor:
    name: str
    description: str
    manufacturer: str
    serial_number: str
    vendor_id: int | None
    product_id: int | None

    @property
    def display_name(self) -> str:
        detail = self.description or self.manufacturer or "串口设备"
        return f"{self.name} — {detail}"

    @property
    def is_electronic_load_candidate(self) -> bool:
        text = f"{self.description} {self.manufacturer}".lower()
        return (
            "electronic load" in text
            or (self.vendor_id == 0x0483 and self.product_id == 0x5740)
        )


class SerialTransport(QObject):
    opened = Signal(str)
    closed = Signal()
    line_received = Signal(str)
    error_occurred = Signal(str)
    traffic = Signal(str, str)

    MAX_LINE_BYTES = 4096

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._serial = QSerialPort(self)
        self._rx_buffer = bytearray()
        self._serial.readyRead.connect(self._read_available)
        self._serial.errorOccurred.connect(self._on_serial_error)

    @staticmethod
    def available_ports() -> list[PortDescriptor]:
        ports: list[PortDescriptor] = []
        for info in QSerialPortInfo.availablePorts():
            ports.append(
                PortDescriptor(
                    name=info.portName(),
                    description=info.description(),
                    manufacturer=info.manufacturer(),
                    serial_number=info.serialNumber(),
                    vendor_id=info.vendorIdentifier() if info.hasVendorIdentifier() else None,
                    product_id=info.productIdentifier() if info.hasProductIdentifier() else None,
                )
            )
        return sorted(ports, key=lambda port: (not port.is_electronic_load_candidate, port.name))

    @property
    def is_open(self) -> bool:
        return self._serial.isOpen()

    @property
    def port_name(self) -> str:
        return self._serial.portName()

    def open(self, port_name: str, baud_rate: int = 115200) -> bool:
        if self.is_open:
            self.close()
        self._rx_buffer.clear()
        self._serial.setPortName(port_name)
        self._serial.setBaudRate(baud_rate)
        self._serial.setDataBits(QSerialPort.DataBits.Data8)
        self._serial.setParity(QSerialPort.Parity.NoParity)
        self._serial.setStopBits(QSerialPort.StopBits.OneStop)
        self._serial.setFlowControl(QSerialPort.FlowControl.NoFlowControl)
        if not self._serial.open(QIODeviceBase.OpenModeFlag.ReadWrite):
            self.error_occurred.emit(f"无法打开 {port_name}: {self._serial.errorString()}")
            return False
        self.opened.emit(port_name)
        return True

    def close(self) -> None:
        was_open = self.is_open
        if was_open:
            self._serial.close()
        self._rx_buffer.clear()
        if was_open:
            self.closed.emit()

    def write_line(self, command: str) -> bool:
        if not self.is_open:
            self.error_occurred.emit("串口尚未连接")
            return False
        normalized = command.strip()
        try:
            payload = (normalized + "\n").encode("ascii")
        except UnicodeEncodeError:
            self.error_occurred.emit("设备命令只能包含 ASCII 字符")
            return False
        written = self._serial.write(payload)
        if written < 0:
            self.error_occurred.emit(f"串口写入失败: {self._serial.errorString()}")
            return False
        self.traffic.emit("TX", normalized)
        return True

    @Slot()
    def _read_available(self) -> None:
        self._rx_buffer.extend(bytes(self._serial.readAll()))
        start = 0
        index = 0
        while index < len(self._rx_buffer):
            if self._rx_buffer[index] in (10, 13):
                if index > start:
                    raw = bytes(self._rx_buffer[start:index])
                    line = raw.decode("ascii", errors="replace").strip()
                    if line:
                        self.traffic.emit("RX", line)
                        self.line_received.emit(line)
                index += 1
                while index < len(self._rx_buffer) and self._rx_buffer[index] in (10, 13):
                    index += 1
                start = index
            else:
                index += 1
        if start:
            del self._rx_buffer[:start]
        if len(self._rx_buffer) > self.MAX_LINE_BYTES:
            self._rx_buffer.clear()
            self.error_occurred.emit("收到的串口数据行过长，已丢弃")

    @Slot(QSerialPort.SerialPortError)
    def _on_serial_error(self, error: QSerialPort.SerialPortError) -> None:
        if error == QSerialPort.SerialPortError.NoError:
            return
        message = self._serial.errorString()
        fatal_errors = {
            QSerialPort.SerialPortError.DeviceNotFoundError,
            QSerialPort.SerialPortError.PermissionError,
            QSerialPort.SerialPortError.ResourceError,
        }
        self.error_occurred.emit(f"串口错误: {message}")
        if error in fatal_errors:
            self.close()
