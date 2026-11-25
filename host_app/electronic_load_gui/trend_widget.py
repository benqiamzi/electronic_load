from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget

from .domain import MeasurementSnapshot
from .theme import (
    CURRENT,
    LEFT_TEMPERATURE,
    PLOT_AXIS,
    PLOT_BACKGROUND,
    PLOT_TEXT,
    POWER,
    RIGHT_TEMPERATURE,
    VOLTAGE,
)


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
        tabs.setAccessibleName("实时趋势")
        window_label = QLabel(f"最近 {self.WINDOW_SECONDS:g} 秒")
        window_label.setProperty("role", "caption")
        window_label.setContentsMargins(0, 0, 8, 0)
        tabs.setCornerWidget(window_label, Qt.Corner.TopRightCorner)
        tabs.addTab(self._create_electrical_tab(), "电气参数")
        tabs.addTab(self._create_temperature_tab(), "温度")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(tabs)
        self._set_time_range(0.0)

    def _configure_plot(
        self, plot: pg.PlotItem, unit: str, color: str, *, show_time: bool
    ) -> None:
        tick_font = QApplication.font()
        tick_font.setPixelSize(11)
        left = plot.getAxis("left")
        left.setPen(PLOT_AXIS)
        left.setTextPen(color)
        left.setWidth(58)
        left.setStyle(tickFont=tick_font)
        plot.setLabel("left", unit, color=color, **{"font-size": "11px"})
        bottom = plot.getAxis("bottom")
        bottom.setPen(PLOT_AXIS)
        bottom.setTextPen(PLOT_TEXT)
        bottom.setStyle(showValues=show_time, tickFont=tick_font)
        if show_time:
            plot.setLabel("bottom", "时间 (s)", color=PLOT_TEXT, **{"font-size": "11px"})
        plot.showGrid(x=True, y=True, alpha=0.23)

    @staticmethod
    def _plot_surface() -> pg.GraphicsLayoutWidget:
        widget = pg.GraphicsLayoutWidget()
        widget.setBackground(PLOT_BACKGROUND)
        widget.ci.layout.setContentsMargins(4, 6, 10, 0)
        widget.ci.layout.setVerticalSpacing(2)
        return widget

    def _create_electrical_tab(self) -> QWidget:
        widget = self._plot_surface()
        voltage_plot = widget.addPlot(row=0, col=0)
        current_plot = widget.addPlot(row=1, col=0)
        power_plot = widget.addPlot(row=2, col=0)
        self._configure_plot(voltage_plot, "V", VOLTAGE, show_time=False)
        self._configure_plot(current_plot, "A", CURRENT, show_time=False)
        self._configure_plot(power_plot, "W", POWER, show_time=True)
        current_plot.setXLink(voltage_plot)
        power_plot.setXLink(voltage_plot)
        self._electrical_plots = (voltage_plot, current_plot, power_plot)
        self._voltage_curve = voltage_plot.plot(pen=pg.mkPen(VOLTAGE, width=2))
        self._current_curve = current_plot.plot(pen=pg.mkPen(CURRENT, width=2))
        self._power_curve = power_plot.plot(pen=pg.mkPen(POWER, width=2))
        return widget

    def _create_temperature_tab(self) -> QWidget:
        widget = self._plot_surface()
        plot = widget.addPlot(row=0, col=0)
        self._configure_plot(plot, "°C", PLOT_TEXT, show_time=True)
        plot.addLegend(labelTextColor=PLOT_TEXT, brush="#ffffff", pen="#d4deea")
        self._temperature_plot = plot
        self._left_curve = plot.plot(
            pen=pg.mkPen(LEFT_TEMPERATURE, width=2), name="左侧温度"
        )
        self._right_curve = plot.plot(
            pen=pg.mkPen(RIGHT_TEMPERATURE, width=2), name="右侧温度"
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
        self._set_time_range(elapsed)

    def _set_time_range(self, elapsed: float) -> None:
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
        self._set_time_range(0.0)
