from __future__ import annotations

import sys

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = app.font()
    font.setPixelSize(13)
    app.setFont(font)
    app.setApplicationName("STM32F411 电子负载上位机")
    app.setOrganizationName("ElectronicLoad")
    pg.setConfigOptions(antialias=True)
    window = MainWindow()
    window.show()
    return app.exec()
