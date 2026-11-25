import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from electronic_load_gui.main_window import MainWindow
from electronic_load_gui.serial_transport import PortDescriptor
from electronic_load_gui.theme import PLACEHOLDER


class FakeSerialTransport(QObject):
    opened = Signal(str)
    closed = Signal()
    line_received = Signal(str)
    error_occurred = Signal(str)
    traffic = Signal(str, str)

    def __init__(self, parent: QObject) -> None:
        super().__init__(parent)
        self.is_open = False
        self.port_name = ""
        self.writes: list[str] = []

    @staticmethod
    def available_ports() -> list[PortDescriptor]:
        return [PortDescriptor("COM7", "Electronic Load CDC", "", "", 0x0483, 0x5740)]

    def open(self, name: str) -> None:
        self.is_open = True
        self.port_name = name
        self.opened.emit(name)

    def close(self) -> None:
        if self.is_open:
            self.is_open = False
            self.closed.emit()

    def write_line(self, command: str) -> bool:
        self.writes.append(command)
        self.traffic.emit("TX", command)
        return True


class MainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.enterContext(
            patch("electronic_load_gui.device.SerialTransport", FakeSerialTransport)
        )
        self.window = MainWindow()
        self.addCleanup(self.window.close)

    def test_channel_poll_does_not_override_pending_selection(self) -> None:
        window = self.window
        window._on_channel_mode("A")
        window.channel_mode_combo.setCurrentIndex(
            window.channel_mode_combo.findData("B")
        )

        window._on_channel_mode("A")

        self.assertEqual(window.channel_mode_combo.currentData(), "B")
        self.assertIn("当前 A", window.apply_channel_mode_button.text())

    def test_input_on_waits_for_selected_channel_to_be_applied(self) -> None:
        window = self.window
        window._advanced_supported = True
        window.input_button.setEnabled(True)
        window._on_channel_mode("A")
        window.channel_mode_combo.setCurrentIndex(window.channel_mode_combo.findData("B"))

        with patch.object(window.device, "set_input") as set_input, patch(
            "electronic_load_gui.main_window.QMessageBox.warning"
        ) as warning:
            window.input_button.click()
            set_input.assert_not_called()
            self.assertFalse(window.input_button.isChecked())
            warning.assert_called_once()

            window._on_channel_mode("B")
            window.input_button.click()
            set_input.assert_called_once_with(True)

    def test_live_dac_controls_require_new_firmware_capability(self) -> None:
        window = self.window
        window.device.transport.is_open = True
        window.device._ready = True
        window._on_dac_capability_changed(True)
        window._on_input_state(True)
        self.assertFalse(window.set_dac_2_action.isEnabled())

        window._on_live_dac_capability_changed(True)
        self.assertTrue(window.set_dac_2_action.isEnabled())
        self.assertTrue(window.dac_dialog.apply_button.isEnabled())
        self.assertEqual(window.dac_dialog.voltage_spin.maximum(), 0.5)

        window.dac_dialog.set_mode("MANUAL")
        self.assertIn("MANUAL", window.dac_dialog.context_label.text())

    def test_device_menu_keeps_identification_error_after_serial_closes(self) -> None:
        window = self.window
        transport = window.device.transport
        menu = window.device_menu_button.menu()
        self.assertTrue(menu.isAncestorOf(window.connection_label))
        self.assertEqual(window.connection_label.text(), "未连接")

        window.connect_button.click()
        self.assertEqual(window.connection_label.text(), "正在识别 COM7…")
        transport.line_received.emit("OTHER,MODEL,SERIAL,0.3.5")

        self.assertFalse(transport.is_open)
        self.assertEqual(window.connection_label.text(), "连接失败")
        self.assertIn("OTHER,MODEL,SERIAL,0.3.5", window.connection_error_text.toPlainText())
        self.assertIn("设备识别失败", window.log_view.toPlainText())

        window.connect_button.click()
        self.assertEqual(window.connection_label.text(), "正在识别 COM7…")
        self.assertTrue(window.connection_error_text.isHidden())
        self.assertEqual(transport.writes, ["*IDN?", "*IDN?"])

    def test_protection_menu_reads_applies_and_restores_device_thresholds(self) -> None:
        window = self.window
        transport = window.device.transport
        window.connect_button.click()
        for line in (
            "ElectronicLoad,EL-F411,SERIAL,0.3.7",
            "12.0000,0.0000,0.0000,36.00,37.00",
            "DISABLED,NONE,0.0000",
            "0.00000,0.00000",
            "AUTO",
            "A",
            "30.0",
            "0",
        ):
            transport.line_received.emit(line)

        window.protection_action.trigger()
        dialog = window.protection_dialog
        self.addCleanup(dialog.close)
        self.assertEqual(transport.writes[-1], "SYST:PROT?")
        self.assertFalse(dialog.apply_button.isEnabled())
        defaults = "30.0000,2.7500,50.0000,80.0000,0"
        transport.line_received.emit(defaults)
        self.assertTrue(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.spins[-1].isEnabled())

        window.device.input_state_updated.emit(True)
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertFalse(dialog.restore_button.isEnabled())
        window.device.input_state_updated.emit(False)

        dialog.spins[0].setValue(24.0)
        dialog.apply_button.click()
        self.assertEqual(transport.writes[-1], "SYST:PROT 24.0000,2.7500,50.0000,80.0000")
        transport.line_received.emit("24.0000,2.7500,50.0000,80.0000,0")
        self.assertEqual(dialog.spins[0].value(), 24.0)
        self.assertTrue(dialog.restore_button.isEnabled())

        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
            dialog.restore_button.click()
        self.assertEqual(transport.writes[-1], "SYST:PROT:DEF")
        transport.line_received.emit(defaults)
        self.assertEqual(dialog.spins[0].value(), 30.0)

        dialog.spins[1].setValue(2.0)
        dialog.apply_button.click()
        transport.line_received.emit("ERROR,Disable load before changing protection thresholds")
        self.assertIn("Disable load", dialog.status_label.text())
        self.assertFalse(dialog.apply_button.isEnabled())
        self.assertTrue(dialog.read_button.isEnabled())

    def test_protection_menu_does_not_send_commands_to_older_firmware(self) -> None:
        window = self.window
        transport = window.device.transport
        window.connect_button.click()
        transport.line_received.emit("ElectronicLoad,EL-F411,SERIAL,0.3.6")
        window.protection_action.trigger()
        self.addCleanup(window.protection_dialog.close)
        self.assertFalse(window.protection_dialog.read_button.isEnabled())
        self.assertIn("0.3.7", window.protection_dialog.status_label.text())
        self.assertNotIn("SYST:PROT?", transport.writes)

    def test_disconnect_clears_live_readings_without_discarding_history(self) -> None:
        window = self.window
        transport = window.device.transport
        identity = "ElectronicLoad,EL-F411,SERIAL,0.3.5"
        window.connect_button.click()
        transport.line_received.emit(identity)
        transport.line_received.emit("12.3456,1.2345,15.2406,36.02,37.14")
        transport.line_received.emit("FAULT,OVER_TEMPERATURE,1.2500")
        transport.line_received.emit("0.00000,0.00000")
        transport.line_received.emit("BOTH")
        transport.line_received.emit("30.0")
        transport.line_received.emit("1")

        self.assertEqual(window.connection_label.text(), "已连接 COM7")
        self.assertEqual(window.identity_text.toPlainText(), identity)
        self.assertEqual(window.voltage_value.text(), "12.3456")
        self.assertEqual(window.left_temp_value.text(), "36.02 °C")
        self.assertEqual(window.requested_value.text(), "1.2500 A")
        self.assertEqual(window.fault_value.property("tone"), "error")
        self.assertTrue(window.input_button.isChecked())
        self.assertFalse(window.set_dac_1_action.isEnabled())
        self.assertTrue(window.record_action.isEnabled())
        self.assertFalse(any(command.startswith("INP ") for command in transport.writes))

        window.emergency_button.click()
        self.assertIn("INP OFF", transport.writes)
        window.close()

        self.assertFalse(transport.is_open)
        self.assertEqual(window.identity_text.toPlainText(), PLACEHOLDER)
        self.assertEqual(window.voltage_value.text(), PLACEHOLDER)
        self.assertEqual(window.fault_value.text(), PLACEHOLDER)
        self.assertFalse(window.input_button.isEnabled())
        self.assertFalse(window.record_action.isEnabled())
        self.assertEqual(list(window.trends._voltage_curve.getData()[1]), [12.3456])
        self.assertIn("INP OFF", window.log_view.toPlainText())
        self.assertEqual(
            [command for command in transport.writes if command.startswith("INP ")],
            ["INP OFF"],
        )


if __name__ == "__main__":
    unittest.main()
