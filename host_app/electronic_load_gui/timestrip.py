from bisect import bisect_left, bisect_right
from collections import deque
from math import nan

import pyqtgraph as pg
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class Timestrip(QWidget):
    selected = Signal(object)
    range_selected = Signal(object, object)
    samples_requested = Signal(str, object, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events = []
        self._times = []
        self._live = deque(maxlen=10000)
        self._archived = []
        self._session = ""
        self._dataset = "live"
        self._origin = None
        self._focus = None
        self._changing_range = False
        self._last_sample_request = None

        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.label = QLabel("设备时间 · 等待捕获")
        self.follow = QCheckBox("跟随")
        self.follow.setChecked(True)
        self.follow.toggled.connect(lambda _: self._render(force_range=True))
        fit = QPushButton("适应范围")
        fit.clicked.connect(self._fit)
        self.range_tool = QCheckBox("选择范围")
        self.range_tool.toggled.connect(self._show_region)
        controls.addWidget(self.label, 1)
        controls.addWidget(self.follow)
        controls.addWidget(fit)
        controls.addWidget(self.range_tool)
        layout.addLayout(controls)

        self._timeline = pg.GraphicsLayoutWidget()
        layout.addWidget(self._timeline, 1)
        self._timeline.setBackground("#fbfcfe")
        self.messages = self._timeline.addPlot(row=0, col=0, title="报文与固件事件")
        self.volts = self._timeline.addPlot(row=1, col=0)
        self.amps = self._timeline.addPlot(row=2, col=0)
        self.volts.setLabel("left", "VBUS", units="V")
        self.amps.setLabel("left", "IBUS", units="A")
        self.amps.setLabel("bottom", "相对设备时间", units="s")
        self.messages.getAxis("left").setTicks([[(0, "报文"), (1, "事件")]])
        self.messages.setYRange(-0.5, 1.5)
        self.messages.setMouseEnabled(y=False)
        for plot in (self.volts, self.amps):
            plot.setXLink(self.messages)
            plot.showGrid(x=True, y=True, alpha=0.2)
        self.messages.showGrid(x=True, alpha=0.2)

        self._dots = pg.ScatterPlotItem(size=7, pen=None)
        self._dots.sigClicked.connect(lambda _, points: self.selected.emit(points[0].data()) if points else None)
        self.messages.addItem(self._dots)
        self._spans = self.messages.plot(pen="#2563a8")
        self._voltage = self.volts.plot(pen="#2563a8", symbol="o", symbolSize=3)
        self._current = self.amps.plot(pen="#0c7863", symbol="o", symbolSize=3)
        self._marker = pg.InfiniteLine(pen=pg.mkPen("#9c4b16", width=2))
        self.messages.addItem(self._marker, ignoreBounds=True)
        self._marker.hide()
        self._region = pg.LinearRegionItem()
        self.messages.addItem(self._region, ignoreBounds=True)
        self._region.hide()
        self._region.sigRegionChangeFinished.connect(self._selected_range)
        self.messages.getViewBox().sigXRangeChanged.connect(self._range_changed)
        self.messages.enableAutoRange(x=False, y=False)

    def clear_live(self):
        self._live.clear()
        if self._dataset == "live":
            self.update_records((), "live")

    def add_sample(self, session, sample):
        if self._live and self._live[-1][0] != session:
            self._live.clear()
        self._live.append((session, sample.timestamp_us, sample.voltage, sample.current))
        if self.isVisible() and self._dataset == "live":
            if self._focus is None and self._session != session:
                self.update_records((), "live")
            self._render(force_range=self.follow.isChecked())

    def update_records(self, records, dataset, selected=None):
        if selected is not None:
            session = selected.session_id
        elif dataset == "live" and self._live:
            session = self._live[-1][0]
        else:
            session = records[-1].session_id if records else ""
        changed = session != self._session or dataset != self._dataset
        if changed:
            self._archived = []
            self._last_sample_request = None
            self._origin = None
        self._session, self._dataset = session, dataset
        self._events = sorted((event for event in records if event.session_id == session),
                              key=lambda event: (event.timestamp_us, event.index))
        self._times = [event.timestamp_us for event in self._events]
        if self._origin is None and self._times:
            self._origin = self._times[0]
        if self._origin is None and dataset == "live" and self._live and self._live[0][0] == session:
            self._origin = self._live[0][1]
        self._focus = selected
        self._render(force_range=changed or self.follow.isChecked())

    def set_archived_samples(self, session, key, samples):
        if self._dataset == "replay" and session == self._session and key == self._last_sample_request:
            self._archived = samples
            self._render()

    def _coords(self, timestamp):
        return (timestamp - self._origin) / 1e6

    def _fit(self):
        bounds = self._bounds()
        if bounds is not None:
            self._set_range(self._coords(bounds[0]), self._coords(bounds[1]))
            self._render()

    def _bounds(self):
        times = [self._times[i] for i in (0, -1)] if self._times else []
        if self._dataset == "live" and self._live and self._live[0][0] == self._session:
            times.extend((self._live[0][1], self._live[-1][1]))
        return (min(times), max(times)) if times else None

    def _set_range(self, left, right):
        self._changing_range = True
        self.messages.setXRange(left, max(right, left + 0.000001), padding=0.05)
        self._changing_range = False

    def _range_changed(self):
        if not self._changing_range and self.isVisible():
            if self.follow.isChecked():
                self.follow.blockSignals(True)
                self.follow.setChecked(False)
                self.follow.blockSignals(False)
            self._render()

    def _show_region(self, visible):
        if visible:
            left, right = self.messages.viewRange()[0]
            self._region.setRegion((left + (right - left) / 4, right - (right - left) / 4))
        self._region.setVisible(visible)

    def _selected_range(self):
        if self._origin is not None and self._region.isVisible():
            left, right = self._region.getRegion()
            self.range_selected.emit(max(0, round(self._origin + left * 1e6)),
                                     max(0, round(self._origin + right * 1e6)))

    def _render(self, force_range=False):
        bounds = self._bounds()
        if bounds is None or self._origin is None:
            self.label.setText("设备时间 · 当前会话暂无记录")
            self._dots.setData(spots=[])
            for item in (self._spans, self._voltage, self._current):
                item.setData([], [])
            self._marker.hide()
            return
        if force_range:
            right = self._coords(bounds[1])
            self._set_range(max(self._coords(bounds[0]), right - 10), right)
        event = self._focus
        if event is not None:
            left, right = self.messages.viewRange()[0]
            point = self._coords(event.timestamp_us)
            if not left <= point <= right:
                width = max(0.001, right - left)
                self._set_range(point - width / 2, point + width / 2)
            self._marker.setValue(point)
            self._marker.show()
            index = next((i for i, item in enumerate(self._events) if item.index == event.index), 0)
            gap = "—" if index == 0 else f"{event.timestamp_us - self._events[index - 1].end_us} µs"
            self.label.setText(f"设备 {event.timestamp_us}–{event.end_us} µs · 时长 {event.end_us - event.timestamp_us} µs"
                               f" · 与前帧间隔 {gap}")
        else:
            self._marker.hide()
            self.label.setText(f"设备时间 · 原点 {self._origin} µs")

        left, right = self.messages.viewRange()[0]
        start = max(0, round(self._origin + left * 1e6))
        end = max(0, round(self._origin + right * 1e6))
        shown = self._events[max(0, bisect_left(self._times, start) - 1):bisect_right(self._times, end)]
        dots = []
        span_x, span_y = [], []
        for item in shown:
            x = self._coords(item.timestamp_us)
            y = int(bool(item.event_type))
            dots.append({"pos": (x, y), "data": item.index, "brush": "#9c4b16" if y else "#2563a8"})
            if item.end_us > item.timestamp_us:
                span_x.extend((x, self._coords(item.end_us), nan))
                span_y.extend((y, y, nan))
        self._dots.setData(spots=dots)
        self._spans.setData(span_x, span_y, connect="finite")
        if self._dataset == "replay":
            key = (start, end)
            if len(self._session) == 32 and key != self._last_sample_request:
                self._last_sample_request = key
                self.samples_requested.emit(self._session, start, end)
            samples = self._archived
        else:
            samples = [(t, v, a) for session, t, v, a in self._live if session == self._session]
        xs, volts, amps = [], [], []
        previous = None
        for timestamp, voltage, current in samples:
            if start <= timestamp <= end:
                if previous is not None and (timestamp <= previous or timestamp - previous > 1_500_000):
                    xs.append(nan)
                    volts.append(nan)
                    amps.append(nan)
                xs.append(self._coords(timestamp))
                volts.append(voltage)
                amps.append(current)
                previous = timestamp
        self._voltage.setData(xs, volts, connect="finite")
        self._current.setData(xs, amps, connect="finite")
