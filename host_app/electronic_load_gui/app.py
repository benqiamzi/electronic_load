from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("STM32F411 电子负载上位机")
    app.setOrganizationName("ElectronicLoad")
    pg.setConfigOptions(antialias=True, background="#17191c", foreground="#d6d6d6")
    window = MainWindow()
    window.show()
    return app.exec()
