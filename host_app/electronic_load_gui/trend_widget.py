from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from .domain import MeasurementSnapshot


class TrendWidget(QWidget):
    MAX_POINTS = 1800
    WINDOW_SECONDS = 60.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._origin: float | None = None
        self._time: deque[float] = deque(maxlen=self.MAX_POINTS)
        self._voltage: deque[float] = deque(maxlen=self.MAX_POINTS)
        self._current: deque[float] = deque(maxlen=self.MAX_POINTS)
        self._power: deque[float] = deque(maxlen=self.MAX_POINTS)
        self._left_temp: deque[float] = deque(maxlen=self.MAX_POINTS)
        self._right_temp: deque[float] = deque(maxlen=self.MAX_POINTS)

        tabs = QTabWidget(self)
        tabs.addTab(self._create_electrical_tab(), "电气参数")
        tabs.addTab(self._create_temperature_tab(), "温度")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)

    def _configure_plot(self, plot: pg.PlotItem, title: str, unit: str) -> None:
        plot.setTitle(title)
        plot.setLabel("left", unit)
        plot.setLabel("bottom", "时间", units="s")
        plot.showGrid(x=True, y=True, alpha=0.25)

    def _create_electrical_tab(self) -> QWidget:
        widget = pg.GraphicsLayoutWidget()
        voltage_plot = widget.addPlot(row=0, col=0)
        current_plot = widget.addPlot(row=1, col=0)
        power_plot = widget.addPlot(row=2, col=0)
        self._configure_plot(voltage_plot, "电压", "V")
        self._configure_plot(current_plot, "电流", "A")
        self._configure_plot(power_plot, "功率", "W")
        current_plot.setXLink(voltage_plot)
        power_plot.setXLink(voltage_plot)
        self._electrical_plots = (voltage_plot, current_plot, power_plot)
        self._voltage_curve = voltage_plot.plot(pen=pg.mkPen("#3daee9", width=2))
        self._current_curve = current_plot.plot(pen=pg.mkPen("#5cc96b", width=2))
        self._power_curve = power_plot.plot(pen=pg.mkPen("#f2a93b", width=2))
        return widget

    def _create_temperature_tab(self) -> QWidget:
        widget = pg.GraphicsLayoutWidget()
        plot = widget.addPlot(row=0, col=0)
        self._configure_plot(plot, "散热器温度", "°C")
        plot.addLegend()
        self._temperature_plot = plot
        self._left_curve = plot.plot(
            pen=pg.mkPen("#ff6b6b", width=2), name="左侧温度"
        )
        self._right_curve = plot.plot(
            pen=pg.mkPen("#b06cff", width=2), name="右侧温度"
        )
        return widget

    def add_sample(self, snapshot: MeasurementSnapshot) -> None:
        if self._origin is None:
            self._origin = snapshot.received_monotonic_s
        elapsed = snapshot.received_monotonic_s - self._origin
        self._time.append(elapsed)
        self._voltage.append(snapshot.voltage_v)
        self._current.append(snapshot.current_a)
        self._power.append(snapshot.power_w)
        self._left_temp.append(snapshot.left_temperature_c)
        self._right_temp.append(snapshot.right_temperature_c)
        x = list(self._time)
        self._voltage_curve.setData(x, list(self._voltage))
        self._current_curve.setData(x, list(self._current))
        self._power_curve.setData(x, list(self._power))
        self._left_curve.setData(x, list(self._left_temp))
        self._right_curve.setData(x, list(self._right_temp))
        lower = max(0.0, elapsed - self.WINDOW_SECONDS)
        upper = max(self.WINDOW_SECONDS, elapsed)
        for plot in (*self._electrical_plots, self._temperature_plot):
            plot.setXRange(lower, upper, padding=0)

    def clear(self) -> None:
        self._origin = None
        for values in (
            self._time,
            self._voltage,
            self._current,
            self._power,
            self._left_temp,
            self._right_temp,
        ):
            values.clear()
        for curve in (
            self._voltage_curve,
            self._current_curve,
            self._power_curve,
            self._left_curve,
            self._right_curve,
        ):
            curve.setData([], [])
