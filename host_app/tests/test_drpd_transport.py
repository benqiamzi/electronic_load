import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtSerialPort import QSerialPort
from PySide6.QtWidgets import QApplication

from electronic_load_gui.devices.drpd.transport import DrpdTransport


class StubSerialPort(QObject):
    readyRead = Signal()
    errorOccurred = Signal(QSerialPort.SerialPortError)
    DataBits = QSerialPort.DataBits
    Parity = QSerialPort.Parity
    StopBits = QSerialPort.StopBits
    FlowControl = QSerialPort.FlowControl
    SerialPortError = QSerialPort.SerialPortError

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.setPortName = Mock()
        self.setBaudRate = Mock(return_value=True)
        self.setDataBits = Mock(return_value=True)
        self.setParity = Mock(return_value=True)
        self.setStopBits = Mock(return_value=True)
        self.setFlowControl = Mock(return_value=True)
        self.setDataTerminalReady = Mock(return_value=True)
        self.errorString = Mock(return_value="device unavailable")
        self.readAll = Mock(return_value=b"")
        self.write = Mock(side_effect=len)
        self.clear = Mock(return_value=True)
        self._open = False
        self.allow_open = True

    def open(self, mode) -> bool:
        self._open = self.allow_open
        return self._open

    def close(self) -> None:
        self._open = False

    def isOpen(self) -> bool:
        return self._open


class DrpdTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        with patch("electronic_load_gui.devices.drpd.transport.QSerialPort", StubSerialPort):
            self.transport = DrpdTransport()
        self.addCleanup(self.transport.close)
        self.serial = self.transport._serial
        self.errors = []
        self.transport.error_occurred.connect(self.errors.append)

    def test_open_write_and_receive_fragments_without_byte_changes(self) -> None:
        opened = []
        received = []
        self.transport.opened.connect(opened.append)
        self.transport.bytes_received.connect(received.append)
        self.assertTrue(self.transport.open("COM15", 57600))
        self.assertTrue(self.transport.is_open)
        self.assertEqual(opened, ["COM15"])
        self.serial.setBaudRate.assert_called_once_with(57600)
        self.serial.setDataTerminalReady.assert_called_once_with(True)
        command = b"BUS:CC:CAP:COUNT?\n"
        self.assertTrue(self.transport.write_bytes(command))
        self.serial.write.assert_called_once_with(command)
        fragments = [b"#13", b"\r\n", b"\x00\n"]
        for fragment in fragments:
            self.serial.readAll.return_value = fragment
            self.serial.readyRead.emit()
        self.assertEqual(received, fragments)

    def test_invalid_port_disconnect_and_reopen(self) -> None:
        disconnected = Mock()
        self.transport.closed.connect(disconnected)
        self.serial.allow_open = False
        self.assertFalse(self.transport.open("COM250"))
        self.assertIn("COM250", self.errors[-1])
        disconnected.assert_not_called()
        self.serial.allow_open = True
        self.assertTrue(self.transport.open("COM15"))
        self.serial.errorOccurred.emit(QSerialPort.SerialPortError.ResourceError)
        self.assertFalse(self.transport.is_open)
        disconnected.assert_called_once()
        self.serial.setDataTerminalReady.assert_called_with(False)
        self.assertTrue(self.transport.open("COM15"))
        self.assertTrue(self.transport.write_bytes(b"*IDN?\n"))

    def test_short_write_closes_the_port(self) -> None:
        self.assertTrue(self.transport.open("COM15"))
        self.serial.write.side_effect = None
        self.serial.write.return_value = 1
        self.assertFalse(self.transport.write_bytes(b"*IDN?\n"))
        self.assertFalse(self.transport.is_open)
        self.assertTrue(self.errors)
