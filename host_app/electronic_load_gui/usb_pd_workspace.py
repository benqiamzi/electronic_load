from pathlib import Path

from PySide6.QtCore import QModelIndex, QRegularExpression, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMenu, QMessageBox, QProgressBar, QPushButton, QSplitter, QStackedWidget,
    QTableView, QToolButton, QVBoxLayout, QWidget,
)

from .pd_views import CaptureFilter, CaptureTableModel, CRC_TEXT, PacketDetails, STATUS_TEXT
from .services.capture_service import DeviceState
from .services.device_service import DeviceService
from .services.export_service import ExportJob
from .services.replay_service import ReplayService, ReplayState
from .theme import PLACEHOLDER, set_tone


_NAV = ("设备连接", "实时捕获", "协议分析", "PDO/RDO", "VDM/VDO", "Extended/EPR", "诊断", "离线回放")
_DETAIL_TABS = {2: 0, 3: 2, 4: 3, 5: 4, 6: 5}
_REPLAY_TEXT = {"idle": "尚未打开文件", "ready": "就绪", "playing": "回放中", "paused": "已暂停",
                "ended": "回放完成", "error": "文件错误"}
_CONNECTION_TEXT = {"disconnected": "未连接", "connecting": "正在连接", "connected": "已连接",
                    "disconnecting": "正在断开", "error": "连接异常"}
_CAPTURE_TEXT = {"idle": "未采集", "starting": "正在启动", "running": "采集中", "stopping": "正在停止",
                 "draining": "正在读完设备队列"}


def _label(text="", role="caption") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setProperty("role", role)
    return label


def _button(text, callback, *, primary=False) -> QPushButton:
    button = QPushButton(text)
    if primary:
        button.setProperty("variant", "primary")
    button.clicked.connect(callback)
    return button


def _combo(items, name) -> QComboBox:
    combo = QComboBox()
    combo.setAccessibleName(name)
    for title, key in items:
        combo.addItem(title, key)
    return combo


class UsbPdWorkspace(QWidget):
    status_changed = Signal(str)
    notice = Signal(str)
    closed = Signal()
    _load_file = Signal(object)
    _replay_control = Signal(str, float)
    _file_ack = Signal(int)
    _export_file = Signal(object)
    _close_file = Signal()

    def __init__(self, settings, port_reserved, parent=None, *, device_factory=None) -> None:
        super().__init__(parent)
        self.setObjectName("pdWorkspace")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.settings = settings
        self._port_reserved = port_reserved
        factory = {"device_factory": device_factory} if device_factory else {}
        self.device = DeviceService(self, **factory)
        self.live_model = CaptureTableModel(self)
        self.replay_model = CaptureTableModel(self)
        self._dataset = "live"
        self._selected = {"live": None, "replay": None}
        self._file_thread = None
        self._file_worker = None
        self._replay = ReplayState()
        self._exporting = False
        self._waiting_export = None
        self._archive_pending = False
        self._saved_live_count = 0
        self._closing = False
        self._closed = False
        self._follow = self.settings.value("pd/auto_follow", True, type=bool)
        self._filter_timer = QTimer(self, singleShot=True, interval=100)
        self._filter_timer.timeout.connect(self._apply_filter)
        self._build()
        self.device.changed.connect(self._device_changed)
        self.device.batch_ready.connect(self._live_batch)
        self.device.error.connect(self._notice)
        self.device.snapshot_ready.connect(self._snapshot_ready)
        self.device.capture_cleared.connect(self._live_cleared)
        self.device.finished.connect(self._maybe_closed)
        self.refresh_ports()
        self._device_changed(self.device.state)
        self._replay_changed(self._replay)
        try:
            page = int(self.settings.value("pd/page", 0))
        except (TypeError, ValueError):
            page = 0
        self.navigation.setCurrentRow(page if 0 <= page < len(_NAV) else 0)

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)
        self.navigation = QListWidget()
        self.navigation.setObjectName("workspaceNavigation")
        self.navigation.setAccessibleName("USB PD 页面")
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.addItems(_NAV)
        self.navigation.setFixedWidth(146)
        outer.addWidget(self.navigation)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_device_page())
        self.pages.addWidget(self._build_analyzer())
        outer.addWidget(self.pages, 1)
        self.navigation.currentRowChanged.connect(self._navigate)

    def _build_device_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setProperty("role", "panel")
        body = QVBoxLayout(panel)
        body.setContentsMargins(16, 14, 16, 16)
        body.addWidget(_label("DRPD 设备连接", "heading"))
        row = QHBoxLayout()
        serial = _label("串口")
        self.port_combo = _combo((), "DRPD 串口")
        self.port_combo.setMinimumWidth(220)
        serial.setBuddy(self.port_combo)
        self.refresh = _button("刷新串口", self.refresh_ports)
        self.connect_button = _button("连接", self._toggle_connection, primary=True)
        self.status_button = _button("读取设备状态", self.device.refresh_status.emit)
        for widget in (serial, self.port_combo, self.refresh, self.connect_button, self.status_button):
            row.addWidget(widget)
        row.addStretch()
        body.addLayout(row)
        form = QFormLayout()
        form.setHorizontalSpacing(20)
        self.device_labels = {}
        for key, title in (("connection", "连接状态"), ("identity", "设备标识"), ("firmware", "固件版本"),
                           ("sink_state", "DUT 协商状态"), ("device_capture", "设备捕获开关"), ("cycle", "捕获周期"),
                           ("epr_config", "固件 EPR 配置"), ("firmware_epr_count", "固件 EPR PDO 数"),
                           ("last", "最近通信"), ("error", "最近错误")):
            label = _label(PLACEHOLDER, "summary")
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            label.setWordWrap(True)
            self.device_labels[key] = label
            form.addRow(_label(title), label)
        body.addLayout(form)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def _build_analyzer(self) -> QWidget:
        panel = QFrame()
        panel.setProperty("role", "panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(7)
        self.live_controls = QWidget()
        row = QHBoxLayout(self.live_controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.go = _button("开始捕获", self.device.start_capture.emit, primary=True)
        self.halt = _button("停止捕获", self.device.stop_capture.emit)
        self.query = _button("读取源能力", self.device.query_source.emit)
        self.clear_display = _button("清空显示", self._hide_rows)
        self.clear_raw = _button("清空本次捕获", self._clear_capture)
        for button in (self.go, self.halt, self.query, self.clear_display, self.clear_raw):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self._export_menu("live"))
        layout.addWidget(self.live_controls)

        self.replay_controls = QWidget()
        row = QHBoxLayout(self.replay_controls)
        row.setContentsMargins(0, 0, 0, 0)
        self.open_button = _button("打开捕获…", self._choose_file, primary=True)
        self.play = _button("继续", lambda: self._replay_control.emit("play", 0.0))
        self.pause = _button("暂停", lambda: self._replay_control.emit("pause", 0.0))
        self.stop_replay = _button("停止", lambda: self._replay_control.emit("stop", 0.0))
        self.step = _button("单帧", lambda: self._replay_control.emit("step", 0.0))
        self.speed = _combo([(f"{speed:g}×", speed) for speed in (0.25, 0.5, 1.0, 2.0, 5.0, 20.0, 100.0)], "回放速度")
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda: self._replay_control.emit("speed", self.speed.currentData()))
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setFormat("%p%")
        self.progress.setAccessibleName("回放进度")
        for button in (self.open_button, self.play, self.pause, self.stop_replay, self.step, self.speed, self.progress):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self._export_menu("replay"))
        layout.addWidget(self.replay_controls)

        self.capture_summary = _label()
        self.capture_summary.setWordWrap(True)
        layout.addWidget(self.capture_summary)
        layout.addLayout(self._build_filters())
        self.filter = CaptureFilter(self)
        self.filter.setSourceModel(self.live_model)
        self.table = QTableView()
        self.table.setObjectName("pdCaptureTable")
        self.table.setAccessibleName("PD 报文列表")
        self.table.setModel(self.filter)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((55, 126, 73, 69, 52, 168, 36, 64, 92, 62)):
            self.table.setColumnWidth(column, width)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.selectionModel().currentChanged.connect(self._current_changed)
        self.details = PacketDetails()
        split = QSplitter(Qt.Orientation.Vertical)
        split.setChildrenCollapsible(False)
        split.addWidget(self.table)
        split.addWidget(self.details)
        split.setSizes([340, 260])
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        layout.addWidget(split, 1)
        self.replay_controls.hide()
        return panel

    def _build_filters(self) -> QVBoxLayout:
        first, second = QHBoxLayout(), QHBoxLayout()
        self.sop_filter = _combo([("全部 SOP", ""), *( (name, name) for name in ("SOP", "SOP'", "SOP''", "Hard Reset", "Cable Reset") )], "SOP 过滤")
        self.type_filter = QLineEdit(placeholderText="消息类型")
        self.type_filter.setAccessibleName("消息类型过滤")
        self.crc_filter = _combo([("全部 CRC", ""), *((v, k) for k, v in CRC_TEXT.items())], "CRC 过滤")
        self.state_filter = _combo([("全部状态", ""), *((v, k) for k, v in STATUS_TEXT.items())], "解析状态过滤")
        self.scope_filter = _combo([("全部协议", ""), ("PDO/RDO", "power"), ("VDM/VDO", "vdm"), ("Extended", "extended")], "协议分类过滤")
        self.level_filter = _combo([("全部诊断级别", ""), ("错误", "error"), ("提示", "warning")], "诊断级别过滤")
        self.keyword = QLineEdit(placeholderText="搜索消息、SVID、原始字或诊断代码")
        self.keyword.setAccessibleName("搜索 PD 报文")
        self.keyword.returnPressed.connect(self._find_first)
        self.time_from = QLineEdit(placeholderText="起始 µs")
        self.time_to = QLineEdit(placeholderText="结束 µs")
        for field, name in ((self.time_from, "起始时间"), (self.time_to, "结束时间")):
            field.setAccessibleName(name)
            field.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,20}"), field))
            field.setMaximumWidth(134)
        self._filter_widgets = (self.sop_filter, self.type_filter, self.crc_filter, self.state_filter,
                                self.scope_filter, self.level_filter, self.keyword, self.time_from, self.time_to)
        for widget in self._filter_widgets[:6]:
            first.addWidget(widget, 1 if widget is self.type_filter else 0)
        for widget in self._filter_widgets[6:]:
            second.addWidget(widget, 1 if widget is self.keyword else 0)
        for widget in self._filter_widgets:
            signal = widget.textChanged if isinstance(widget, QLineEdit) else widget.currentIndexChanged
            signal.connect(lambda *_: self._filter_timer.start())
        second.addWidget(_button("定位", self._find_first))
        second.addWidget(_button("清除过滤", self._clear_filters))
        filters = QVBoxLayout()
        filters.setSpacing(5)
        filters.addLayout(first)
        filters.addLayout(second)
        return filters

    def _export_menu(self, dataset: str) -> QToolButton:
        button = QToolButton()
        button.setText("保存 / 导出")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        for label, kind in (("原始捕获…", "raw"), ("CSV 摘要…", "csv"), ("JSON 详情…", "json"), ("诊断报告…", "diagnostics")):
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, value=kind: self._choose_export(dataset, value))
        button.setMenu(menu)
        if dataset == "live":
            self.live_export = button
        else:
            self.replay_export = button
        return button

    @Slot(int)
    def _navigate(self, row: int) -> None:
        if row < 0:
            return
        self.settings.setValue("pd/page", row)
        self.pages.setCurrentIndex(int(row != 0))
        if row == 0:
            return
        if row == 1:
            self._show_dataset("live")
        elif row == 7:
            self._show_dataset("replay")
        if row in _DETAIL_TABS:
            self.details.setCurrentIndex(_DETAIL_TABS[row])
        self._apply_filter()

    def _show_dataset(self, dataset: str) -> None:
        if self._dataset != dataset:
            self._dataset = dataset
            self.filter.setSourceModel(self.live_model if dataset == "live" else self.replay_model)
            self._restore_selection(self._selected[dataset])
        self.live_controls.setVisible(dataset == "live")
        self.replay_controls.setVisible(dataset == "replay")
        self._update_summary()

    def _restore_selection(self, frame_index) -> None:
        if frame_index is not None:
            model = self.filter.sourceModel()
            for row, event in enumerate(model.rows):
                if event.index == frame_index:
                    proxy = self.filter.mapFromSource(model.index(row, 0))
                    if proxy.isValid():
                        self.table.setCurrentIndex(proxy)
                        return
                    break
        self.details.set_event(None)

    @Slot(QModelIndex, QModelIndex)
    def _current_changed(self, current, previous) -> None:
        event = current.data(CaptureTableModel.EventRole)
        if event is not None:
            self._selected[self._dataset] = event.index
        self.details.set_event(event)

    def _apply_filter(self) -> None:
        page = self.navigation.currentRow()
        self.filter.configure(sop=self.sop_filter.currentData(), message=self.type_filter.text().strip().casefold(),
                              crc=self.crc_filter.currentData(), state=self.state_filter.currentData(),
                              scope=self.scope_filter.currentData(), level=self.level_filter.currentData(),
                              start=int(self.time_from.text()) if self.time_from.text() else None,
                              end=int(self.time_to.text()) if self.time_to.text() else None,
                              keyword=self.keyword.text().strip().casefold(), diagnostics_only=page == 6)
        self._update_summary()

    def _find_first(self) -> None:
        self._apply_filter()
        if self.filter.rowCount():
            index = self.filter.index(0, 0)
            self.table.setCurrentIndex(index)
            self.table.scrollTo(index)

    def _clear_filters(self) -> None:
        for widget in self._filter_widgets:
            if isinstance(widget, QLineEdit):
                widget.clear()
            else:
                widget.setCurrentIndex(0)
        self._apply_filter()

    def focus_search(self) -> None:
        if self.navigation.currentRow() == 0:
            self.navigation.setCurrentRow(2)
        self.keyword.setFocus()
        self.keyword.selectAll()

    def set_auto_follow(self, enabled: bool) -> None:
        self._follow = enabled
        self.settings.setValue("pd/auto_follow", enabled)

    @Slot()
    def refresh_ports(self) -> None:
        previous = self.port_combo.currentData() or self.settings.value("pd/port")
        self.port_combo.clear()
        for name, display in self.device.available_ports():
            self.port_combo.addItem(display, name)
        index = self.port_combo.findData(previous)
        if index >= 0:
            self.port_combo.setCurrentIndex(index)
        if not self.port_combo.count():
            self.port_combo.addItem("未发现串口", None)

    def _toggle_connection(self) -> None:
        if self.device.state.connection == "connected":
            self.device.disconnect_port.emit()
            return
        port = self.port_combo.currentData()
        if not port:
            self._notice("没有可连接的 DRPD 串口")
        elif self._port_reserved(port):
            self._notice(f"{port} 正由电子负载工作区使用")
        else:
            self.settings.setValue("pd/port", port)
            self.device.connect_port(port)

    @Slot(object)
    def _device_changed(self, state: DeviceState) -> None:
        connected = state.connection == "connected"
        busy = state.connection in ("connecting", "disconnecting")
        active = state.capture != "idle"
        self.connect_button.setText("断开" if connected else "连接")
        self.connect_button.setEnabled(not busy and not self._closing)
        self.refresh.setEnabled(not connected and not busy)
        self.port_combo.setEnabled(not connected and not busy)
        self.status_button.setEnabled(connected)
        self.go.setEnabled(connected and not active)
        self.halt.setEnabled(state.capture in ("running", "starting"))
        self.query.setEnabled(state.capture == "running")
        self.clear_raw.setEnabled(not active and not self._exporting and state.count > 0)
        self.live_export.setEnabled(not self._exporting and state.count > 0)
        self.clear_display.setEnabled(self.live_model.rowCount() > 0)
        values = {"connection": f"{_CONNECTION_TEXT[state.connection]} {state.port}".strip(),
                  "identity": state.identity, "firmware": state.firmware, "sink_state": state.sink_state,
                  "device_capture": ("ON" if state.device_capture else "OFF") if state.device_capture is not None else "",
                  "cycle": f"{state.cycle_ns:g} ns" if state.cycle_ns is not None else "", "epr_config": state.epr_config,
                  "firmware_epr_count": state.firmware_epr_count, "last": state.last_communication, "error": state.error}
        for key, value in values.items():
            label = self.device_labels[key]
            label.setText(str(value) if value is not None and value != "" else PLACEHOLDER)
            if key == "error":
                set_tone(label, "error" if value else "muted")
        self._update_summary()
        status = f"USB PD  {_CONNECTION_TEXT[state.connection]}{' ' + state.port if state.port else ''}"
        if active:
            status += f" · {_CAPTURE_TEXT[state.capture]} {state.count} 帧"
        if state.waiting_for_ui:
            status += " · 背压"
        if state.error:
            status += " · 有告警"
        if self._replay.state == "playing":
            status += " · 回放中"
        self.status_changed.emit(status)

    def _update_summary(self) -> None:
        showing = self.filter.rowCount()
        if self._dataset == "live":
            state = self.device.state
            metrics = state.metrics
            self.capture_summary.setToolTip(
                f"主机读取 {metrics.received} · 分析 {metrics.analyzed} · 原始归档 {metrics.archived}\n"
                f"待交付 {metrics.pending}（峰值 {metrics.peak_pending}）· 背压 {metrics.backpressure_count} 次\n"
                f"CRC 不可用 {metrics.crc_unavailable} · 读取失败 {metrics.capture_read_errors} · "
                f"写入失败 {metrics.journal_errors}\n"
                "固件未提供物理漏捕计数"
            )
            queue = str(state.queue) if state.queue is not None else PLACEHOLDER
            epr = f"EPR {'已观察到通告' if state.epr_observed else '未观察到通告'} · 有效 PDO {state.epr_pdo_count}"
            hidden = f" · 显示窗口外 {self.live_model.hidden} 帧" if self.live_model.hidden else ""
            wait = " · 背压，设备仍在排队，丢失计数不可用" if state.waiting_for_ui else ""
            self.capture_summary.setText(f"{_CAPTURE_TEXT[state.capture]} · {state.count} 帧 · 显示 {showing} · 主机 CRC 错误 {state.crc_errors}"
                                         f" · 诊断 {state.diagnostic_count} · 设备队列 {queue}（峰值 {state.peak_queue}） · {epr}{hidden}{wait}")
        else:
            state = self._replay
            name = state.path.name if state.path else PLACEHOLDER
            metadata = state.metadata or {}
            peer = metadata.get("peer", "")
            hidden = f" · 显示窗口外 {self.replay_model.hidden} 帧" if self.replay_model.hidden else ""
            self.capture_summary.setText(f"{_REPLAY_TEXT[state.state]} · {name} · 已读 {state.count} 帧 · 显示 {showing}{hidden}"
                                         + (f" · {peer}" if peer else ""))
            self.capture_summary.setToolTip("\n".join(f"{k}: {v}" for k, v in metadata.items()))

    @Slot(object, int)
    def _live_batch(self, batch, token: int) -> None:
        try:
            if not self._closing:
                self._append(self.live_model, batch, "live")
                self.clear_display.setEnabled(self.live_model.rowCount() > 0)
        finally:
            self.device.acknowledge.emit(token)

    @Slot(object, int)
    def _replay_batch(self, batch, token: int) -> None:
        try:
            if not self._closing:
                self._append(self.replay_model, batch, "replay")
        finally:
            self._file_ack.emit(token)

    def _append(self, model, batch, dataset: str) -> None:
        model.append(batch)
        if self._dataset == dataset:
            if self._follow and not self.table.currentIndex().isValid():
                self.table.scrollToBottom()
            self._update_summary()

    def _hide_rows(self) -> None:
        self.live_model.clear(display_only=True)
        self._selected["live"] = None
        self.clear_display.setEnabled(False)
        if self._dataset == "live":
            self.details.set_event(None)
        self._update_summary()

    def _clear_capture(self) -> None:
        if QMessageBox.question(self, "清空本次捕获", "清空本次捕获的临时原始数据？已导出的文件仍可打开。",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.device.clear_capture.emit()

    @Slot()
    def _live_cleared(self) -> None:
        self.live_model.clear()
        self._saved_live_count = 0
        self._selected["live"] = None
        self.clear_display.setEnabled(False)
        if self._dataset == "live":
            self.details.set_event(None)
        self._update_summary()

    def _ensure_file_worker(self) -> None:
        if self._file_thread is not None:
            return
        worker = ReplayService()
        thread = QThread(self)
        worker.moveToThread(thread)
        self._load_file.connect(worker.load)
        self._replay_control.connect(worker.control)
        self._file_ack.connect(worker.acknowledge)
        self._export_file.connect(worker.export)
        self._close_file.connect(worker.shutdown)
        worker.opened.connect(self._file_opened)
        worker.changed.connect(self._replay_changed)
        worker.batch_ready.connect(self._replay_batch)
        worker.error.connect(self._notice)
        worker.exported.connect(self._exported)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._maybe_closed)
        self._file_thread, self._file_worker = thread, worker
        thread.start()

    def _choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "打开 PD 捕获", str(self.settings.value("pd/open_dir", "")),
                                              "捕获文件 (*.drpd *.json *.hex *.txt);;所有文件 (*)")
        if path:
            self.open_capture(Path(path))

    def open_capture(self, path: Path) -> None:
        if self._closing:
            return
        self._ensure_file_worker()
        self.settings.setValue("pd/open_dir", str(path.parent))
        self.navigation.setCurrentRow(7)
        self._load_file.emit(path)

    @Slot(object)
    def _file_opened(self, path: Path) -> None:
        self.replay_model.clear()
        self._selected["replay"] = None
        if self._dataset == "replay":
            self.details.set_event(None)

    @Slot(object)
    def _replay_changed(self, state: ReplayState) -> None:
        self._replay = state
        ready = state.state in ("ready", "playing", "paused")
        self.play.setEnabled(ready and state.state != "playing")
        self.pause.setEnabled(state.state == "playing")
        self.step.setEnabled(ready and state.state != "playing")
        self.stop_replay.setEnabled(state.path is not None and state.state != "error")
        self.replay_export.setEnabled(state.path is not None and state.state != "error" and not self._exporting)
        self.progress.setValue(round(state.progress * 1000))
        self._device_changed(self.device.state)

    def _choose_export(self, dataset: str, kind: str) -> None:
        ext = {"raw": "drpd", "csv": "csv", "json": "json", "diagnostics": "md"}[kind]
        directory = Path(str(self.settings.value("pd/export_dir", str(Path.home()))))
        path, _ = QFileDialog.getSaveFileName(self, "保存捕获或导出", str(directory / f"capture.{ext}"),
                                              f"{ext.upper()} 文件 (*.{ext})")
        if path:
            target = Path(path)
            self.settings.setValue("pd/export_dir", str(target.parent))
            self.export_capture(dataset, kind, target)

    def export_capture(self, dataset: str, kind: str, target: Path) -> None:
        if self._exporting or self._closing:
            return
        if dataset == "replay" and self._replay.path is None:
            return
        if dataset == "live" and not self.device.state.count:
            return
        self._ensure_file_worker()
        self._exporting = True
        self._archive_pending = dataset == "live" and kind == "raw"
        self._replay_changed(self._replay)
        if dataset == "live":
            self._waiting_export = (kind, target)
            self.device.snapshot.emit()
        else:
            self._export_file.emit(ExportJob(self._replay.path, target, kind))

    @Slot(object)
    def _snapshot_ready(self, snapshot) -> None:
        pending, self._waiting_export = self._waiting_export, None
        if pending is None or self._closing:
            return
        kind, target = pending
        if snapshot is None or not snapshot.count:
            self._exported(target, 0, "没有可保存的已落盘捕获")
        else:
            self._export_file.emit(ExportJob(snapshot.path, target, kind, snapshot))

    @Slot(object, int, str)
    def _exported(self, target, count, error) -> None:
        if self._archive_pending and not error:
            self._saved_live_count = max(self._saved_live_count, count)
        self._archive_pending = False
        self._exporting = False
        self._notice(f"导出失败：{error}" if error else f"已保存 {count} 帧到 {target.name}")
        self._replay_changed(self._replay)

    def _notice(self, message: str) -> None:
        self.notice.emit(message)

    @property
    def busy(self) -> bool:
        return (self.device.state.capture != "idle" or self.device.state.count > self._saved_live_count
                or self._replay.state == "playing" or self._exporting)

    @property
    def running(self) -> bool:
        return self.device.running or (self._file_thread is not None and self._file_thread.isRunning())

    def shutdown(self) -> None:
        self._closing = True
        self.device.shutdown()
        if self._file_thread is not None and self._file_thread.isRunning():
            self._file_thread.requestInterruption()
            self._close_file.emit()
        self._maybe_closed()

    @Slot()
    def _maybe_closed(self) -> None:
        if self._closing and not self._closed and not self.running:
            self._closed = True
            self.device.cleanup()
            self.closed.emit()
