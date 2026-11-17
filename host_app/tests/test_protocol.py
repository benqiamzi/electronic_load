import unittest

from PySide6.QtCore import QObject, QCoreApplication, Signal

from electronic_load_gui.protocol import ProtocolClient


class FakeTransport(QObject):
    line_received = Signal(str)
    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []
        self.accept_writes = True

    def write_line(self, command: str) -> bool:
        self.writes.append(command)
        return self.accept_writes


class ProtocolClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self) -> None:
        self.transport = FakeTransport()
        self.client = ProtocolClient(self.transport)

    def test_queries_are_strictly_serialized(self) -> None:
        responses: list[tuple[str, str]] = []
        self.client.query("FIRST?", lambda line: responses.append(("first", line)))
        self.client.query("SECOND?", lambda line: responses.append(("second", line)))
        self.assertEqual(self.transport.writes, ["FIRST?"])

        self.transport.line_received.emit("1")
        self.assertEqual(self.transport.writes, ["FIRST?", "SECOND?"])
        self.transport.line_received.emit("2")
        self.assertEqual(responses, [("first", "1"), ("second", "2")])
        self.assertTrue(self.client.is_idle)

    def test_duplicate_poll_key_is_suppressed(self) -> None:
        accepted_first = self.client.query("MEAS:ALL?", lambda line: None, key="measure")
        accepted_second = self.client.query("MEAS:ALL?", lambda line: None, key="measure")
        self.assertTrue(accepted_first)
        self.assertFalse(accepted_second)
        self.assertEqual(self.transport.writes, ["MEAS:ALL?"])

    def test_fire_and_forget_command_precedes_following_query(self) -> None:
        response: list[str] = []
        self.client.command("INP OFF")
        self.client.query("SYST:ERR?", response.append)
        QCoreApplication.processEvents()
        self.assertEqual(self.transport.writes, ["INP OFF", "SYST:ERR?"])
        self.transport.line_received.emit('0,"No error"')
        self.assertEqual(response, ['0,"No error"'])


if __name__ == "__main__":
    unittest.main()
