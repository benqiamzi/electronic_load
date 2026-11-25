from struct import pack
import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from electronic_load_gui.devices.drpd.capture_client import CaptureClient
from electronic_load_gui.devices.drpd.protocol_client import DrpdProtocolClient, ScpiDeviceError


class FakeTransport(QObject):
    bytes_received = Signal(bytes)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.is_open = True
        self.writes = []

    def close(self) -> None:
        if self.is_open:
            self.is_open = False
            self.closed.emit()

    def write_bytes(self, data: bytes) -> bool:
        self.writes.append(data)
        return self.is_open


class DrpdProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.protocol = DrpdProtocolClient(self.transport)
        self.addCleanup(self.transport.close)
        self.responses = []
        self.errors = []
        self.protocol.error_occurred.connect(self.errors.append)

    def test_serializes_writes_text_and_binary_queries(self) -> None:
        self.protocol.command("BUS:CC:CAP:EN ON", callback=lambda: self.responses.append("written"))
        self.protocol.query_text("BUS:CC:CAP:COUNT?", self.responses.append, key="count")
        self.assertFalse(self.protocol.query_text("BUS:CC:CAP:COUNT?", self.responses.append, key="count"))
        self.protocol.query_binary("BUS:CC:CAP:DATA?", self.responses.append)
        self.app.processEvents()
        self.app.processEvents()
        self.assertEqual(self.transport.writes, [b"BUS:CC:CAP:EN ON\n", b"BUS:CC:CAP:COUNT?\n"])
        self.transport.bytes_received.emit(b"2\r")
        self.assertEqual(self.responses, ["written"])
        self.transport.bytes_received.emit(b"\n")
        self.app.processEvents()
        self.assertEqual(self.transport.writes[-1], b"BUS:CC:CAP:DATA?\n")
        for byte in b"#13\x0a\x0d\x00\n":
            self.transport.bytes_received.emit(bytes([byte]))
        self.assertEqual(self.responses, ["written", "2", b"\x0a\x0d\x00"])
        self.assertTrue(self.protocol.is_idle)
        self.assertEqual(self.errors, [])

    def test_recognizes_device_error_and_continues(self) -> None:
        self.protocol.query_binary("DATA?", self.responses.append, errback=self.errors.append)
        self.protocol.query_text("COUNT?", self.responses.append)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"-")
        self.transport.bytes_received.emit(b"200\n")
        self.assertIsInstance(self.errors[0], ScpiDeviceError)
        self.assertEqual(self.errors[0].code, -200)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"0\n")
        self.assertEqual(self.responses, ["0"])

    def test_timeout_cancels_queue_and_ignores_late_data(self) -> None:
        self.protocol.query_binary("FIRST?", self.responses.append, errback=self.errors.append, timeout_ms=10)
        self.protocol.query_text("SECOND?", self.responses.append, errback=self.errors.append)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"#13x")
        QTest.qWait(50)
        self.assertFalse(self.transport.is_open)
        self.transport.bytes_received.emit(b"yz\n")
        self.assertEqual(len(self.errors), 2)
        self.assertEqual(self.transport.writes, [b"FIRST?\n"])
        self.assertEqual(self.responses, [])
        self.transport.is_open = True
        self.protocol.query_text("NEW?", self.responses.append)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"new\n")
        self.assertEqual(self.responses, ["new"])

    def test_disconnect_and_clear_notify_pending_and_queued_requests(self) -> None:
        for end_session in (self.transport.close, self.protocol.clear):
            with self.subTest(end_session=end_session):
                self.transport.is_open = True
                self.protocol.query_text("FIRST?", self.responses.append, errback=self.errors.append)
                self.protocol.query_binary("SECOND?", self.responses.append, errback=self.errors.append)
                self.app.processEvents()
                self.transport.bytes_received.emit(b"half")
                end_session()
                self.assertTrue(self.protocol.is_idle)
                self.assertFalse(self.transport.is_open)
        self.assertEqual(len(self.errors), 4)
        self.assertEqual(self.responses, [])

    def test_extra_bytes_in_same_read_never_become_next_response(self) -> None:
        self.protocol.query_text("FIRST?", self.responses.append, errback=self.errors.append)
        self.protocol.query_text("SECOND?", self.responses.append, errback=self.errors.append)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"one\nunexpected\n")
        self.app.processEvents()
        self.assertEqual(self.transport.writes, [b"FIRST?\n"])
        self.assertEqual(self.responses, [])
        self.assertEqual(len(self.errors), 2)

    def test_binary_framing_error_closes_session(self) -> None:
        self.protocol.query_binary("DATA?", self.responses.append)
        self.app.processEvents()
        self.transport.bytes_received.emit(b"#11x\r")
        self.assertFalse(self.transport.is_open)
        self.assertIn("LF", self.errors[0])

    def test_rejects_non_ascii_and_multiline_commands_without_writing(self) -> None:
        self.assertFalse(self.protocol.command("COUNT?\nDATA?"))
        self.assertFalse(self.protocol.command("你好"))
        self.app.processEvents()
        self.assertEqual(self.transport.writes, [])
        self.assertEqual(len(self.errors), 2)


class CaptureClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.protocol = DrpdProtocolClient(self.transport)
        self.capture = CaptureClient(self.protocol, max_records_per_drain=2)
        self.addCleanup(self.transport.close)
        self.records = []
        self.errors = []
        self.rounds = []
        self.counts = []
        self.capture.capture_received.connect(self.records.append)
        self.capture.error_occurred.connect(self.errors.append)
        self.capture.drain_finished.connect(self.rounds.append)
        self.capture.capture_count_changed.connect(self.counts.append)

    def respond(self, command: bytes, response: bytes) -> None:
        self.app.processEvents()
        self.assertEqual(self.transport.writes[-1], command + b"\n")
        self.transport.bytes_received.emit(response)

    def test_drain_is_bounded_and_cycle_time_is_queried(self) -> None:
        self.assertTrue(self.capture.drain_capture_queue())
        self.assertFalse(self.capture.drain_capture_queue())
        self.respond(b"BUS:CC:CAP:COUNT?", b"6\n")
        self.respond(b"BUS:CC:CAP:CYCLETIME?", b"7.25\n")
        record = pack("<QQI4sIHI3s", 1, 2, 2, b"abcd", 1, 101, 3, b"\x00\x0a\x0d")
        wire = b"#237" + record + b"\n"
        self.respond(b"BUS:CC:CAP:DATA?", wire)
        self.respond(b"BUS:CC:CAP:DATA?", wire)
        self.assertEqual(self.rounds, [2])
        self.assertEqual(len(self.records), 2)
        self.assertEqual(self.records[0].pulse_widths_ns, (732.25,))
        self.assertEqual(self.records[1].decoded_data, b"\x00\x0a\x0d")
        self.assertEqual(len(self.transport.writes), 4)
        self.assertEqual(self.errors, [])

    def test_empty_after_count_ends_round_and_reconnect_refreshes_cycle(self) -> None:
        self.capture.drain_capture_queue()
        self.respond(b"BUS:CC:CAP:COUNT?", b"2\n")
        self.respond(b"BUS:CC:CAP:CYCLETIME?", b"9\n")
        self.respond(b"BUS:CC:CAP:DATA?", b'-200,"Execution error"\n')
        self.assertEqual(self.rounds, [0])
        self.assertEqual(self.counts, [2, 0])
        self.transport.close()
        self.transport.is_open = True
        result = []
        self.capture.fetch_next_capture(result.append)
        self.respond(b"BUS:CC:CAP:CYCLETIME?", b"10\n")
        self.respond(b"BUS:CC:CAP:DATA?", b"-200\n")
        self.assertEqual(result, [None])
        self.assertEqual(self.capture.cycle_time_ns, 10)

    def test_capture_commands_and_invalid_text(self) -> None:
        states = []
        self.capture.capture_state_changed.connect(states.append)
        self.capture.start_capture()
        self.capture.stop_capture()
        self.capture.get_cycle_time()
        self.app.processEvents()
        self.app.processEvents()
        self.respond(b"BUS:CC:CAP:CYCLETIME?", b"nan\n")
        self.capture.get_capture_count()
        self.respond(b"BUS:CC:CAP:COUNT?", b"-1\n")
        self.assertEqual(self.transport.writes[:2], [b"BUS:CC:CAP:EN ON\n", b"BUS:CC:CAP:EN OFF\n"])
        self.assertEqual(states, [True, False])
        self.assertEqual(len(self.errors), 2)
