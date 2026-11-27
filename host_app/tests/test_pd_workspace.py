from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory, mkstemp
from time import monotonic
import unittest
from unittest.mock import patch

from PySide6.QtCore import QEventLoop, QObject, QSettings, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from electronic_load_gui.devices.drpd.capture_client import CaptureClient
from electronic_load_gui.devices.drpd.protocol_client import DrpdProtocolClient
from electronic_load_gui.main_window import MainWindow
from electronic_load_gui.services.capture_file import CaptureJournal, CaptureReader
from electronic_load_gui.pd_views import CaptureTableModel
from protocol_m7_fixtures import parse_wire, synthetic_mixed_wire
from test_usb_pd import FIXTURES


class SimulatedDrpdTransport(QObject):
    bytes_received = Signal(bytes)
    closed = Signal()
    error_occurred = Signal(str)
    opened = Signal(str)
    remove_device = Signal()

    def __init__(self, parent, wires):
        super().__init__(parent)
        self.wires = wires
        self.queue = deque()
        self.is_open = False
        self.enabled = False
        self.opens = 0
        self.remove_device.connect(self.unplug)

    def open(self, port):
        self.opens += 1
        self.is_open = True
        self.opened.emit(port)
        return True

    def close(self):
        if self.is_open:
            self.is_open = False
            self.closed.emit()

    @Slot()
    def unplug(self):
        self.close()
        self.error_occurred.emit("设备已拔出")

    def write_bytes(self, data):
        command = data.decode("ascii").strip()
        responses = {"*IDN?": '"MTA",Dr.PD,test,1.0.0-beta.1', "BUS:CC:CAP:CYCLETIME?": "10",
                     "BUS:CC:CAP:EN?": "ON" if self.enabled else "OFF", "SINK:STATUS?": "PE_SNK_READY",
                     "SINK:EPR:EN?": "ON", "SINK:CAP:EPR:COUNT?": "0", "BUS:CC:CAP:COUNT?": str(len(self.queue))}
        if command in responses:
            response = (responses[command] + "\n").encode("ascii")
        elif command == "BUS:CC:CAP:DATA?":
            response = self.queue.popleft() if self.queue else b"-200\n"
        else:
            if command == "BUS:CC:CAP:EN ON":
                self.enabled = True
            elif command == "BUS:CC:CAP:EN OFF":
                self.enabled = False
            elif command == "SINK:INQ GET_SOURCE_CAP" and self.enabled:
                self.queue.extend(self.wires)
            return self.is_open
        QTimer.singleShot(0, self, lambda: self.bytes_received.emit(response) if self.is_open else None)
        return self.is_open


class PdWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        directory = TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.settings = QSettings(str(self.directory / "ui.ini"), QSettings.Format.IniFormat)
        wires = tuple(bytes.fromhex(line) for line in (FIXTURES / "usb_pd_m7_cuktech10mini_blocks.txt").read_text().splitlines())
        self.transport = None

        def device_factory(parent):
            device = QObject(parent)
            device.transport = SimulatedDrpdTransport(device, wires)
            self.transport = device.transport
            device.protocol = DrpdProtocolClient(device.transport, device, timeout_ms=250)
            device.capture = CaptureClient(device.protocol, device, max_records_per_drain=8)
            return device

        self.enterContext(patch("electronic_load_gui.services.device_service.tempfile.mkstemp",
                                side_effect=lambda **kw: mkstemp(**kw, dir=self.directory)))
        self.enterContext(patch("electronic_load_gui.services.device_service.DeviceService.available_ports",
                                return_value=[("COM99", "COM99 — DRPD 模拟")]))
        self.window = MainWindow(settings=self.settings, drpd_device_factory=device_factory)
        self.ws = self.window.pd_workspace
        self.addCleanup(self._close)

    def _close(self):
        self.ws.shutdown()
        self.wait(lambda: not self.ws.running)
        self.window._closing = True
        self.window.close()

    def wait(self, predicate, *, limit=4.0):
        deadline = monotonic() + limit
        while not predicate() and monotonic() < deadline:
            loop = QEventLoop()
            QTimer.singleShot(10, loop.quit)
            loop.exec()
        self.assertTrue(predicate(), f"Live {self.ws.device.state!r}; replay {self.ws._replay!r}")

    def test_switch_retains_running_capture_and_independent_port_ownership(self):
        self.assertEqual(self.window.workspace_stack.currentIndex(), 0)
        self.window.workspace_manager.select(1)
        self.ws.connect_button.click()
        self.wait(lambda: self.ws.device.state.connection == "connected" and self.ws.device.state.epr_config == "ON")
        self.assertIsNot(self.transport.thread(), QThread.currentThread())
        self.ws.navigation.setCurrentRow(1)
        self.ws.go.click()
        self.wait(lambda: self.ws.device.state.capture == "running")
        self.ws.query.click()
        self.window.workspace_manager.select(0)
        for _ in range(6):
            self.window.workspace_manager.select(1)
            self.window.workspace_manager.select(0)
        self.wait(lambda: self.ws.live_model.rowCount() == 48)
        self.assertIn("采集中", self.window.pd_status.text())
        self.assertEqual(self.transport.opens, 1)
        self.window.port_combo.addItem("COM99", "COM99")
        self.window.port_combo.setCurrentIndex(self.window.port_combo.findData("COM99"))
        self.window.connect_button.click()
        self.assertFalse(self.window.device.transport.is_open)
        self.assertIn("正由 USB PD", self.window.connection_error_text.toPlainText())
        self.window.workspace_manager.select(1)
        self.assertEqual(self.ws.navigation.currentRow(), 1)
        self.ws.halt.click()
        self.wait(lambda: self.ws.device.state.capture == "idle" and self.ws.device.state.device_capture is False)
        self.ws.clear_display.click()
        self.assertEqual(self.ws.live_model.rowCount(), 0)
        destination = self.directory / "live.drpd"
        self.ws.export_capture("live", "raw", destination)
        self.wait(lambda: destination.exists() and not self.ws._exporting)
        with CaptureReader(destination) as reader:
            self.assertEqual(len(tuple(reader)), 48)
        self.transport.remove_device.emit()
        self.wait(lambda: self.ws.device.state.connection == "error" and "拔出" in self.ws.device.state.error)
        self.ws.device.connect_port("COM99")
        self.wait(lambda: self.ws.device.state.connection == "connected")
        self.assertEqual(self.transport.opens, 2)
        self.assertEqual(self.settings.value("workspace/active"), "usb_pd")

    def test_workspace_menu_keyboard_selection_and_startup_restore(self):
        self.assertEqual(self.window.workspace_stack.currentIndex(), 0)
        self.window.show()
        self.addCleanup(self.window.hide)
        selector = self.window.workspace_selector
        menu = selector.menu()
        menu.popup(selector.mapToGlobal(selector.rect().bottomLeft()))
        self.wait(menu.isVisible)
        self.app.processEvents()
        for action in menu.actions():
            button = action.defaultWidget()
            self.assertGreaterEqual(button.height(), button.layout().sizeHint().height())
        menu.setActiveAction(menu.actions()[0])
        QTest.keyClick(menu, Qt.Key.Key_Down)
        QTest.keyClick(menu, Qt.Key.Key_Return)
        self.wait(lambda: self.window.workspace_stack.currentIndex() == 1)
        self.assertFalse(menu.isVisible())
        self.ws.navigation.setCurrentRow(4)
        self.ws.set_auto_follow(False)
        self.settings.sync()
        restored_settings = QSettings(self.settings.fileName(), QSettings.Format.IniFormat)
        restored = MainWindow(settings=restored_settings)
        self.addCleanup(restored.close)
        self.assertEqual(restored.workspace_stack.currentIndex(), 1)
        self.assertEqual(restored.pd_workspace.navigation.currentRow(), 4)
        self.assertFalse(restored.pd_workspace._follow)
        self.assertEqual(restored.pd_workspace.device.state.connection, "disconnected")
        self.assertFalse(restored.pd_workspace.running)

    def test_replay_step_filter_locate_and_restore_selection(self):
        self.window.workspace_manager.select(1)
        self.ws.open_capture(FIXTURES / "usb_pd_m7_cuktech10mini_real.json")
        self.wait(lambda: self.ws._replay.state == "ready")
        self.ws.step.click()
        self.wait(lambda: self.ws.replay_model.rowCount() == 1)
        self.assertEqual(self.ws._replay.state, "paused")
        self.ws.speed.setCurrentIndex(self.ws.speed.count() - 1)
        self.ws.play.click()
        self.wait(lambda: self.ws._replay.state == "ended" and self.ws.replay_model.rowCount() == 48)
        frames = {event.index: event for event in self.ws.replay_model.rows}
        self.assertEqual([pdo.supply_type for pdo in frames[3].message.pdos], ["fixed"] * 5 + ["pps"] * 2)
        self.assertEqual([frames[i].message_name for i in (7, 9, 13, 17, 19, 21)],
                         ["Accept", "PS_RDY", "Source_Capabilities_Extended", "Status",
                          "Get_Manufacturer_Info", "Not_Supported"])
        self.assertEqual(frames[25].message.data_objects, (0x31180000,))
        self.assertEqual(frames[29].message.data_objects, (0x80787878,))
        self.assertEqual(frames[33].message.vdm.vdos[0].decoded_fields["usb_vid"], 0x2B01)
        self.assertEqual(frames[37].message.vdm.discovered_svids, (0x2717,))
        self.assertEqual((frames[41].message.vdm.svid, frames[41].message.vdm.vdos[0].raw), (0xFF01, 0x405))
        self.assertIn("vdm_discovery_response_mismatch", [issue.code for issue in frames[41].diagnostics])
        self.ws.keyword.setText("0x1144B12C")
        self.ws._find_first()
        selected = self.ws.table.currentIndex().data(CaptureTableModel.EventRole)
        self.assertEqual(selected.power.rdo.operating_current_ma, 3000)
        self.window.workspace_manager.select(0)
        self.window.workspace_manager.select(1)
        self.assertEqual(self.ws.table.currentIndex().data(CaptureTableModel.EventRole), selected)
        self.ws.navigation.setCurrentRow(6)
        self.ws.keyword.setText("invalid_unchunked_header")
        self.ws._find_first()
        event = self.ws.table.currentIndex().data(CaptureTableModel.EventRole)
        self.assertEqual(event.message_name, "Security_Request")
        self.assertIsNone(event.extended.message)
        self.assertIn("88 A8 04 00", self.ws.details.raw.toPlainText())
        self.assertEqual(self.ws.replay_model.rowCount(), 48)
        self.ws.stop_replay.click()
        self.wait(lambda: self.ws._replay.state == "ready" and self.ws.replay_model.rowCount() == 0)

    def test_play_large_native_file_with_bounded_view_and_responsive_main_loop(self):
        path = self.directory / "large.drpd"
        _, wire, _ = synthetic_mixed_wire()
        record = next(parse_wire(wire))
        journal = CaptureJournal(path, {"capture_cycle_ns": 10.0})
        for _ in range(12000):
            journal.append(record, "synthetic")
        journal.close()
        self.window.workspace_manager.select(1)
        self.ws.open_capture(path)
        self.wait(lambda: self.ws._replay.state == "ready")
        replies = []
        heartbeat = QTimer(interval=20)
        heartbeat.timeout.connect(lambda: replies.append(monotonic()))
        heartbeat.start()
        self.ws.play.click()
        self.wait(lambda: self.ws._replay.state == "ended", limit=12)
        heartbeat.stop()
        self.assertGreaterEqual(len(replies), 3)
        self.assertEqual(self.ws._replay.count, 12000)
        self.assertLessEqual(self.ws.replay_model.rowCount(), 4000)
        self.assertEqual(self.ws.replay_model.hidden + self.ws.replay_model.rowCount(), 12000)

    def test_replay_pause_invalid_file_and_synthetic_epr_detail(self):
        self.window.workspace_manager.select(1)
        self.ws.open_capture(FIXTURES / "usb_pd_m7_cuktech10mini_real.json")
        self.wait(lambda: self.ws._replay.state == "ready")
        self.ws.play.click()
        self.wait(lambda: self.ws._replay.state == "playing")
        self.ws.pause.click()
        self.wait(lambda: self.ws._replay.state == "paused")
        count = self.ws.replay_model.rowCount()
        self.wait(lambda: self.ws._replay.count == count)
        self.assertLess(count, 48)
        malformed = self.directory / "malformed.drpd"
        malformed.write_text('{"format":"electronic-load-drpd-capture","version":900}\n', encoding="utf-8")
        self.ws.open_capture(malformed)
        self.wait(lambda: self.ws._replay.state == "error")
        self.assertEqual(self.ws.replay_model.rowCount(), 0)

        path = self.directory / "synthetic.drpd"
        _, wire, _ = synthetic_mixed_wire()
        journal = CaptureJournal(path, {"capture_cycle_ns": 10.0})
        for record in parse_wire(wire):
            journal.append(record, "synthetic")
        journal.close()
        self.ws.open_capture(path)
        self.wait(lambda: self.ws._replay.state == "ready")
        self.ws.speed.setCurrentIndex(self.ws.speed.count() - 1)
        self.ws.play.click()
        self.wait(lambda: self.ws._replay.state == "ended" and self.ws.replay_model.rowCount() == 22)
        self.ws.keyword.setText("0x9048c055")
        self.ws._find_first()
        current = self.ws.table.currentIndex().data(CaptureTableModel.EventRole)
        self.assertEqual(current.provenance, "synthetic")
        self.assertTrue(current.epr_observed)
        self.assertEqual((current.epr_pdo_count, current.power.rdo.operating_current_ma), (2, 4250))
        headings = [self.ws.details.extended.topLevelItem(i).text(0)
                    for i in range(self.ws.details.extended.topLevelItemCount())]
        self.assertIn("EPR 请求能力上下文", headings)
