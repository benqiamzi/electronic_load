import csv
from pathlib import Path
import tempfile
import unittest

from electronic_load_gui.data_logger import CsvDataLogger
from electronic_load_gui.domain import MeasurementSnapshot


class CsvDataLoggerTests(unittest.TestCase):
    def test_writes_header_and_measurement(self) -> None:
        # Keep the temporary file inside the repository so this test also works
        # in restricted Windows sandboxes where the process temp path is read-only.
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "capture.csv"
            logger = CsvDataLogger()
            logger.start(path)
            logger.append(MeasurementSnapshot(12.0, 1.0, 12.0, 35.5, 36.5))
            logger.stop()
            with path.open("r", encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0][1:], [
                "voltage_V",
                "current_A",
                "power_W",
                "left_temperature_C",
                "right_temperature_C",
            ])
            self.assertEqual(rows[1][1:], ["12.0000", "1.0000", "12.0000", "35.50", "36.50"])


if __name__ == "__main__":
    unittest.main()
