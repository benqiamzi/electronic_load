from __future__ import annotations

from datetime import datetime
from math import ceil
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QSizeF, Qt, QTimer, Slot
from PySide6.QtGui import QAction, QActionEvent, QCloseEvent, QFontDatabase, QKeySequence, QTextCursor, QTextOption
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from .data_logger import CsvDataLogger
from .device import ElectronicLoadDevice
from .dialogs import DacControlDialog, ProtectionDialog
from .domain import DacVoltages, DeviceStatus, MeasurementSnapshot
from .services.workspace_manager import WorkspaceManager
from .theme import PLACEHOLDER, STYLESHEET, set_tone
from .trend_widget import TrendWidget
from .usb_pd_workspace import UsbPdWorkspace
from .workspace_selector import WorkspaceSelector


class DeviceMenu(QMenu):
    def __init__(self, content: QWidget, parent: QWidget) -> None:
        super().__init__(parent)
        self._content_action = QWidgetAction(self)
        self._content_action.setDefaultWidget(content)
        self.addAction(self._content_action)
        content.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.LayoutRequest
            and watched is self._content_action.defaultWidget()
        ):
            # QMenu caches QWidgetAction geometry separately from the widget's layout.
            QCoreApplication.sendEvent(
                self, QActionEvent(QEvent.Type.ActionChanged, self._content_action)
            )
            if self.isVisible():
                self.adjustSize()
        return super().eventFilter(watched, event)


class DeviceMenuText(QTextEdit):
    def __init__(self, text: str, name: str) -> None:
        super().__init__()
        self.setProperty("role", "menuText")
        self.setAccessibleName(name)
        self.setReadOnly(True)
        self.setTabChangesFocus(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self.document().documentLayout().documentSizeChanged.connect(self._fit_text)
        self.setPlainText(text)

    def _fit_text(self, size: QSizeF) -> None:
        self.setFixedHeight(min(144, ceil(size.height())))


class MainWindow(QMainWindow):
    def __init__(self, *, settings=None, drpd_device_factory=None) -> None:
        super().__init__()
        self.setWindowTitle("STM32F411 电子负载上位机")
        self.setMinimumSize(1024, 680)
        self.resize(1280, 800)
        self.device = ElectronicLoadDevice(self)
        self.logger = CsvDataLogger()
        self.dac_dialog = DacControlDialog(self)
        self.protection_dialog = ProtectionDialog(self)
        self._input_enabled = False
        self._dac_supported = False
        self._dac_live_supported = False
        self._advanced_supported = False
        self._channel_mode_initialized = False
        self._actual_channel_mode: str | None = None
        self._connection_failed = False
        self._closing = False
        self._close_deferred = False
        self.workspace_manager = WorkspaceManager(self, settings)
        self._drpd_device_factory = drpd_device_factory
        self._build_ui()
        self.setStyleSheet(STYLESHEET)
        self._connect_signals()
        self.refresh_ports()
        self._set_controls_enabled(False)
        self._update_dac_controls()

    def _build_ui(self) -> None:
        self.workspace_selector = WorkspaceSelector(self)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._build_toolbar())
        root = QWidget(self)
        root.setObjectName("dashboard")
        self.workspace_stack = QStackedWidget(self)
        self.setCentralWidget(self.workspace_stack)
        self.workspace_stack.addWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.setContentsMargins(16, 12, 16, 16)
        main_layout.setSpacing(10)
        main_layout.addWidget(self._build_measurement_panel())

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.main_splitter.setHandleWidth(10)
        self.main_splitter.setChildrenCollapsible(False)
        self.trends = TrendWidget()
        self.trends.setMinimumHeight(250)
        self.main_splitter.addWidget(self.trends)

        lower = QWidget()
        lower_layout = QHBoxLayout(lower)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        lower_layout.setSpacing(12)
        lower_layout.addWidget(self._build_control_panel())
        lower_layout.addWidget(self._build_log_panel(), 1)
        self.main_splitter.addWidget(lower)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.main_splitter.setSizes([410, 214])
        main_layout.addWidget(self.main_splitter, 1)

        self.load_status = self._label("电子负载  未连接", "caption")
        self.pd_status = self._label("USB PD  未连接", "caption")
        self.statusBar().setSizeGripEnabled(False)
        self.statusBar().addPermanentWidget(self.load_status)
        self.statusBar().addPermanentWidget(self.pd_status)
        self.pd_workspace = UsbPdWorkspace(self.workspace_manager.settings, self._load_owns_port, self,
                                           device_factory=self._drpd_device_factory)
        self.workspace_stack.addWidget(self.pd_workspace)
        self.pd_workspace.status_changed.connect(self.pd_status.setText)
        self.pd_workspace.notice.connect(self._announce)
        self.pd_workspace.closed.connect(self._pd_closed)
        self.workspace_selector.selected.connect(self.workspace_manager.select)
        self.workspace_manager.changed.connect(self._show_workspace)
        self._show_workspace(self.workspace_manager.index)

    def _build_toolbar(self) -> QToolBar:
        toolbar = QToolBar("设备与采集工具", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.addWidget(self.workspace_selector)
        toolbar.addSeparator()
        always_visible = tuple(toolbar.actions())
        toolbar.addWidget(self._build_device_menu_button())

        protection_menu = QMenu(self)
        self.protection_action = protection_menu.addAction("设置保护阈值…")
        toolbar.addWidget(self._menu_button("保护", protection_menu))

        self.record_action = QAction("开始记录曲线 CSV…", self)
        self.record_action.setCheckable(True)
        self.record_action.setToolTip("将后续 INA226 测量值和温度数据保存为 CSV")
        self.clear_plot_action = QAction("清空曲线", self)
        curve_menu = QMenu(self)
        curve_menu.addAction(self.record_action)
        curve_menu.addAction(self.clear_plot_action)
        self.curve_menu_button = self._menu_button("曲线工具", curve_menu)
        toolbar.addWidget(self.curve_menu_button)

        dac_menu = QMenu(self)
        self.view_dac_action = dac_menu.addAction("查看两路 DAC 设定输出…")
        self.dac_set_menu = dac_menu.addMenu("设置单路电压")
        self.set_dac_1_action = self.dac_set_menu.addAction("DAC 1（通道 A）…")
        self.set_dac_2_action = self.dac_set_menu.addAction("DAC 2（通道 B）…")
        dac_menu.addSeparator()
        self.zero_dac_action = dac_menu.addAction("双路 DAC 归零…")
        self.dac_menu_button = self._menu_button("DAC 工具", dac_menu)
        toolbar.addWidget(self.dac_menu_button)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        shared_spacer = toolbar.addWidget(spacer)
        self.port_combo = QComboBox()
        self.port_combo.setFixedWidth(242)
        self.port_combo.setToolTip("选择电子负载的 USB CDC 串口")
        self.refresh_button = QPushButton("刷新")
        self.connect_button = QPushButton("连接")
        self.connect_button.setProperty("variant", "primary")
        self.connect_button.setFixedWidth(76)
        port_label = self._label("串口", "caption")
        port_label.setBuddy(self.port_combo)
        toolbar.addWidget(port_label)
        toolbar.addWidget(self.port_combo)
        toolbar.addWidget(self.refresh_button)
        toolbar.addWidget(self.connect_button)
        self._load_toolbar_actions = tuple(action for action in toolbar.actions()
                                           if action not in always_visible and action is not shared_spacer)
        toolbar.addSeparator()
        self.notice_menu = QMenu(self)
        self.notice_menu.addAction("暂无通知").setEnabled(False)
        toolbar.addWidget(self._menu_button("通知", self.notice_menu))
        search = QAction("搜索", self)
        search.setShortcut(QKeySequence.StandardKey.Find)
        search.triggered.connect(self._search_workspace)
        toolbar.addAction(search)
        settings_menu = QMenu(self)
        follow = settings_menu.addAction("自动跟随新捕获")
        follow.setCheckable(True)
        follow.setChecked(self.workspace_manager.settings.value("pd/auto_follow", True, type=bool))
        follow.toggled.connect(lambda enabled: self.pd_workspace.set_auto_follow(enabled))
        toolbar.addWidget(self._menu_button("设置", settings_menu))
        return toolbar

    @Slot(int)
    def _show_workspace(self, index: int) -> None:
        self.workspace_selector.set_current(index)
        self.workspace_stack.setCurrentIndex(index)
        self.setWindowTitle("STM32F411 电子负载上位机" if index == 0 else "STM32F411 电子负载上位机 · USB PD 测试")
        for action in self._load_toolbar_actions:
            action.setVisible(index == 0)

    def _load_owns_port(self, port: str) -> bool:
        transport = self.device.transport
        return transport.is_open and transport.port_name.casefold() == port.casefold()

    def _refresh_load_status(self) -> None:
        label = f"电子负载  {self.connection_label.text()}"
        if self._input_enabled:
            label += " · 负载 ON"
        if self.logger.is_active:
            label += " · CSV 记录中"
        self.load_status.setText(label)

    @Slot(str)
    def _announce(self, message: str) -> None:
        first = self.notice_menu.actions()[0]
        if first.text() == "暂无通知":
            self.notice_menu.removeAction(first)
            first.deleteLater()
        contents = self.notice_menu.actions()
        action = QAction(message, self.notice_menu)
        action.triggered.connect(lambda: self.statusBar().showMessage(message, 9000))
        self.notice_menu.insertAction(contents[0] if contents else None, action)
        if len(contents) >= 8:
            self.notice_menu.removeAction(contents[-1])
            contents[-1].deleteLater()
        self.statusBar().showMessage(message, 9000)

    def _search_workspace(self) -> None:
        if self.workspace_manager.index == 1:
            self.pd_workspace.focus_search()
            return
        keyword, accepted = QInputDialog.getText(self, "搜索通信日志", "关键字")
        if accepted and keyword and not self.log_view.find(keyword):
            self.log_view.moveCursor(QTextCursor.MoveOperation.Start)
            if not self.log_view.find(keyword):
                self.statusBar().showMessage("通信日志中没有匹配项", 4000)

    @staticmethod
    def _menu_button(title: str, menu: QMenu) -> QToolButton:
        button = QToolButton()
        button.setText(title)
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return button

    def _build_device_menu_button(self) -> QToolButton:
        information = QWidget()
        information.setFixedWidth(360)
        layout = QVBoxLayout(information)
        layout.setContentsMargins(12, 8, 12, 10)
        layout.setSpacing(5)
        self.connection_label = self._label("未连接", "summary")
        self.connection_label.setProperty("tone", "muted")
        self.identity_text = DeviceMenuText(PLACEHOLDER, "设备标识")
        self.connection_error_text = DeviceMenuText("", "错误详情")
        self.connection_error_text.setProperty("tone", "error")
        layout.addWidget(self._label("连接状态", "caption"))
        layout.addWidget(self.connection_label)
        layout.addWidget(self.connection_error_text)
        self.connection_error_text.hide()
        layout.addSpacing(5)
        layout.addWidget(self._label("设备标识", "caption"))
        layout.addWidget(self.identity_text)
        menu = DeviceMenu(information, self)
        self.device_menu_button = self._menu_button("设备", menu)
        return self.device_menu_button

    @staticmethod
    def _label(text: str, role: str) -> QLabel:
        label = QLabel(text)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setProperty("role", role)
        return label

    def _measurement_card(self, title: str, unit: str, metric: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setProperty("role", "metric")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 7, 12, 7)
        layout.setSpacing(1)
        layout.addWidget(self._label(title, "caption"))
        reading = QHBoxLayout()
        reading.setSpacing(5)
        value = self._label(PLACEHOLDER, "readout")
        value.setAccessibleName(f"{title}（{unit}）")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setFamilies(["Consolas", font.family()])
        value.setFont(font)
        unit_label = self._label(unit, "unit")
        for label in (value, unit_label):
            label.setProperty("metric", metric)
            reading.addWidget(label, alignment=Qt.AlignmentFlag.AlignBaseline)
        reading.addStretch(1)
        layout.addLayout(reading)
        return frame, value

    def _build_measurement_panel(self) -> QWidget:
        box = QFrame()
        box.setProperty("role", "panel")
        box.setAccessibleName("实时测量和设备状态")
        layout = QHBoxLayout(box)
        layout.setContentsMargins(9, 9, 12, 9)
        layout.setSpacing(8)
        voltage_card, self.voltage_value = self._measurement_card("电压", "V", "voltage")
        current_card, self.current_value = self._measurement_card("电流", "A", "current")
        power_card, self.power_value = self._measurement_card("功率", "W", "power")
        voltage_card.setToolTip("电压数据由 INA226 总线电压寄存器采集")
        current_card.setToolTip("电流数据由 INA226 电流寄存器采集")
        for card in (voltage_card, current_card, power_card):
            card.setMinimumWidth(174)
            layout.addWidget(card, 1)

        details = QGridLayout()
        details.setContentsMargins(10, 0, 0, 0)
        details.setHorizontalSpacing(12)
        details.setVerticalSpacing(3)
        self.left_temp_value = self._label(PLACEHOLDER, "summary")
        self.left_temp_value.setProperty("metric", "leftTemperature")
        self.right_temp_value = self._label(PLACEHOLDER, "summary")
        self.right_temp_value.setProperty("metric", "rightTemperature")
        self.state_value = self._label(PLACEHOLDER, "summary")
        self.fault_value = self._label(PLACEHOLDER, "summary")
        self.requested_value = self._label(PLACEHOLDER, "summary")
        entries = (
            ("左侧温度", self.left_temp_value, 0, 0),
            ("右侧温度", self.right_temp_value, 1, 0),
            ("运行状态", self.state_value, 0, 1),
            ("故障", self.fault_value, 1, 1),
            ("总设定电流", self.requested_value, 0, 2),
        )
        for title, value, row, column in entries:
            reading = QVBoxLayout()
            reading.setSpacing(1)
            reading.addWidget(self._label(title, "caption"))
            value.setAccessibleName(title)
            reading.addWidget(value)
            details.addLayout(reading, row, column)
        details.setColumnMinimumWidth(0, 76)
        details.setColumnMinimumWidth(1, 150)
        details.setColumnMinimumWidth(2, 80)
        layout.addLayout(details)
        return box

    def _build_control_panel(self) -> QWidget:
        box = QFrame()
        box.setProperty("role", "panel")
        box.setMinimumWidth(424)
        layout = QGridLayout(box)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(5)
        layout.addWidget(self._label("负载控制", "heading"), 0, 0, 1, 2)
        self.channel_mode_combo = QComboBox()
        self.channel_mode_combo.addItem("A 路单独输出", "A")
        self.channel_mode_combo.addItem("B 路单独输出", "B")
        self.channel_mode_combo.addItem("A+B 双路（总电流均分）", "BOTH")
        self.apply_channel_mode_button = QPushButton("安全切换")
        self.apply_channel_mode_button.setToolTip(
            "先关闭负载并将 DAC 归零，再切换到下拉框选择的环路"
        )
        self.current_setpoint = QDoubleSpinBox()
        self.current_setpoint.setRange(0.0, 2.5)
        self.current_setpoint.setDecimals(4)
        self.current_setpoint.setSingleStep(0.01)
        self.current_setpoint.setSuffix(" A")
        self.current_setpoint.setToolTip("总负载电流；双路模式下 A、B 各承担一半")
        self.apply_current_button = QPushButton("应用电流")
        self.fan_duty_spin = QDoubleSpinBox()
        self.fan_duty_spin.setRange(0.0, 100.0)
        self.fan_duty_spin.setDecimals(1)
        self.fan_duty_spin.setSingleStep(5.0)
        self.fan_duty_spin.setSuffix(" %")
        self.fan_duty_spin.setValue(100.0)
        self.apply_fan_button = QPushButton("应用风扇")
        self.fan_duty_value = self._label(PLACEHOLDER, "muted")
        self.input_button = QPushButton("负载 OFF")
        self.input_button.setCheckable(True)
        self.input_button.setMinimumHeight(32)
        self.input_button.setProperty("variant", "load")
        self.emergency_button = QPushButton("紧急关闭")
        self.emergency_button.setMinimumHeight(32)
        self.emergency_button.setProperty("variant", "danger")
        self.clear_fault_button = QPushButton("清除故障")
        self.reset_button = QPushButton("设备复位")
        layout.addWidget(self.clear_fault_button, 0, 2)
        layout.addWidget(self.reset_button, 0, 3)
        layout.addWidget(self.input_button, 1, 0, 1, 2)
        layout.addWidget(self.emergency_button, 1, 2, 1, 2)
        layout.addWidget(self._label("输出环路", "caption"), 2, 0)
        layout.addWidget(self.channel_mode_combo, 2, 1, 1, 2)
        layout.addWidget(self.apply_channel_mode_button, 2, 3)
        layout.addWidget(self._label("总恒流", "caption"), 3, 0)
        layout.addWidget(self.current_setpoint, 3, 1, 1, 2)
        layout.addWidget(self.apply_current_button, 3, 3)
        layout.addWidget(self._label("风扇", "caption"), 4, 0)
        layout.addWidget(self.fan_duty_spin, 4, 1)
        layout.addWidget(self.fan_duty_value, 4, 2)
        layout.addWidget(self.apply_fan_button, 4, 3)
        layout.setColumnStretch(1, 1)
        layout.setColumnMinimumWidth(3, 126)
        layout.setRowStretch(5, 1)
        self._control_widgets = [
            self.channel_mode_combo,
            self.apply_channel_mode_button,
            self.current_setpoint,
            self.apply_current_button,
            self.fan_duty_spin,
            self.apply_fan_button,
            self.input_button,
            self.emergency_button,
            self.clear_fault_button,
            self.reset_button,
            self.record_action,
        ]
        return box

    def _build_log_panel(self) -> QWidget:
        box = QFrame()
        box.setProperty("role", "panel")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 9, 12, 10)
        layout.setSpacing(5)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("communicationLog")
        self.log_view.setAccessibleName("通信日志")
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log_view.document().setMaximumBlockCount(1000)
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_view.clear)
        header = QHBoxLayout()
        header.addWidget(self._label("通信日志", "heading"))
        header.addStretch(1)
        header.addWidget(clear_button)
        layout.addLayout(header)
        layout.addWidget(self.log_view, 1)
        return box

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.apply_current_button.clicked.connect(
            lambda: self.device.set_current(self.current_setpoint.value())
        )
        self.apply_channel_mode_button.clicked.connect(self._request_channel_mode_change)
        self.apply_fan_button.clicked.connect(
            lambda: self.device.set_fan_duty(self.fan_duty_spin.value())
        )
        self.input_button.clicked.connect(self._request_input_change)
        self.emergency_button.clicked.connect(lambda: self.device.set_input(False))
        self.clear_fault_button.clicked.connect(self.device.clear_fault)
        self.reset_button.clicked.connect(self.device.reset_device)
        self.clear_plot_action.triggered.connect(self.trends.clear)
        self.record_action.triggered.connect(self._toggle_recording)
        self.view_dac_action.triggered.connect(lambda: self._show_dac_dialog())
        self.set_dac_1_action.triggered.connect(lambda: self._show_dac_dialog(1))
        self.set_dac_2_action.triggered.connect(lambda: self._show_dac_dialog(2))
        self.zero_dac_action.triggered.connect(self._confirm_zero_dac)
        self.protection_action.triggered.connect(self._show_protection_dialog)
        self.protection_dialog.read_requested.connect(self.device.read_protection_thresholds)
        self.protection_dialog.apply_requested.connect(self.device.set_protection_thresholds)
        self.protection_dialog.restore_requested.connect(self.device.restore_protection_thresholds)
        self.device.protection_thresholds_updated.connect(self.protection_dialog.set_thresholds)
        self.device.protection_error.connect(self.protection_dialog.show_error)
        self.device.protection_error.connect(lambda message: self._append_log(f"保护操作失败：{message}"))
        self.device.input_state_updated.connect(self.protection_dialog.set_input_state)
        self.dac_dialog.apply_requested.connect(self._apply_dac_voltage)
        self.dac_dialog.zero_requested.connect(self._confirm_zero_dac)
        self.device.connection_changed.connect(self._on_connection_changed)
        self.device.identity_changed.connect(self.identity_text.setPlainText)
        self.device.measurements_updated.connect(self._on_measurements)
        self.device.status_updated.connect(self._on_status)
        self.device.input_state_updated.connect(self._on_input_state)
        self.device.dac_voltages_updated.connect(self._on_dac_voltages)
        self.device.dac_capability_changed.connect(self._on_dac_capability_changed)
        self.device.live_dac_capability_changed.connect(self._on_live_dac_capability_changed)
        self.device.dac_mode_updated.connect(self.dac_dialog.set_mode)
        self.device.channel_mode_updated.connect(self._on_channel_mode)
        self.device.fan_duty_updated.connect(self._on_fan_duty)
        self.device.advanced_control_capability_changed.connect(
            self._on_advanced_control_capability_changed
        )
        self.device.error_occurred.connect(self._show_error)
        self.device.traffic.connect(self._append_traffic)

    @Slot()
    def refresh_ports(self) -> None:
        previous = self.port_combo.currentData()
        self.port_combo.clear()
        for port in self.device.available_ports():
            self.port_combo.addItem(port.display_name, port.name)
            if port.name == previous:
                self.port_combo.setCurrentIndex(self.port_combo.count() - 1)
        if not self.port_combo.count():
            self.port_combo.addItem("未发现串口", None)

    @Slot()
    def _toggle_connection(self) -> None:
        if self.device.transport.is_open:
            self.device.disconnect_device()
            return
        self._connection_failed = False
        self._clear_connection_error()
        port_name = self.port_combo.currentData()
        if port_name:
            pd = self.pd_workspace.device.state
            if pd.port and pd.port.casefold() == str(port_name).casefold():
                self._show_error(f"{port_name} 正由 USB PD 测试工作区使用")
                return
            self.device.connect_to(str(port_name))
        else:
            self._show_error("没有可连接的串口")

    @Slot(bool, str)
    def _on_connection_changed(self, connected: bool, message: str) -> None:
        self.protection_dialog.set_context(
            connected=connected, supported=self.device.protection_supported
        )
        if connected and self.protection_dialog.isVisible():
            self.protection_dialog.read()
        port_open = self.device.transport.is_open
        if connected:
            self._connection_failed = False
            self._clear_connection_error()
        self.connection_label.setText("连接失败" if self._connection_failed else message)
        set_tone(
            self.connection_label,
            "error" if self._connection_failed else "success" if connected else "muted",
        )
        self.connect_button.setText("断开" if port_open else "连接")
        self.port_combo.setEnabled(not port_open)
        self.refresh_button.setEnabled(not port_open)
        self._set_controls_enabled(connected)
        self._update_dac_controls()
        self._update_advanced_controls()
        if not connected:
            self._channel_mode_initialized = False
            self._actual_channel_mode = None
            self._dac_live_supported = False
            self.apply_channel_mode_button.setText("安全切换")
            self.identity_text.setPlainText(PLACEHOLDER)
            for label in (
                self.voltage_value,
                self.current_value,
                self.power_value,
                self.left_temp_value,
                self.right_temp_value,
                self.state_value,
                self.fault_value,
                self.requested_value,
                self.fan_duty_value,
            ):
                label.setText(PLACEHOLDER)
            set_tone(self.fault_value, "muted")
            self._stop_recording()
            self._on_input_state(False)
        self._refresh_load_status()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self._control_widgets:
            widget.setEnabled(enabled)

    @Slot()
    def _show_protection_dialog(self) -> None:
        if not self.protection_dialog.isVisible():
            self.protection_dialog.read()
        self.protection_dialog.show()
        self.protection_dialog.raise_()
        self.protection_dialog.activateWindow()

    @Slot(bool)
    def _on_dac_capability_changed(self, supported: bool) -> None:
        self._dac_supported = supported
        if not supported:
            self.dac_dialog.set_voltages(None)
        self._update_dac_controls()

    @Slot(bool)
    def _on_live_dac_capability_changed(self, supported: bool) -> None:
        self._dac_live_supported = supported
        self._update_dac_controls()

    def _update_dac_controls(self) -> None:
        connected = self.device.is_connected
        configurable = connected and self._dac_supported and (
            not self._input_enabled or self._dac_live_supported
        )
        self.dac_menu_button.setEnabled(connected)
        self.view_dac_action.setEnabled(connected)
        self.dac_set_menu.setEnabled(configurable)
        self.set_dac_1_action.setEnabled(configurable)
        self.set_dac_2_action.setEnabled(configurable)
        self.zero_dac_action.setEnabled(configurable)
        self.dac_dialog.set_context(
            connected=connected,
            supported=self._dac_supported,
            input_enabled=self._input_enabled,
            live_supported=self._dac_live_supported,
        )

    @Slot(bool)
    def _on_advanced_control_capability_changed(self, supported: bool) -> None:
        self._advanced_supported = supported
        self._update_advanced_controls()

    def _update_advanced_controls(self) -> None:
        enabled = self.device.is_connected and self._advanced_supported
        for widget in (
            self.channel_mode_combo,
            self.apply_channel_mode_button,
            self.fan_duty_spin,
            self.apply_fan_button,
        ):
            widget.setEnabled(enabled)

    @Slot()
    def _request_channel_mode_change(self) -> None:
        mode = str(self.channel_mode_combo.currentData())
        if self._input_enabled:
            answer = QMessageBox.warning(
                self,
                "安全切换输出环路",
                "切换输出环路会先关闭负载并将两路 DAC 归零。切换完成后负载保持 OFF，"
                "需要重新手动开启。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.device.set_channel_mode(mode)

    @Slot(bool)
    def _request_input_change(self, checked: bool) -> None:
        if checked and self._advanced_supported:
            selected = str(self.channel_mode_combo.currentData())
            if self._actual_channel_mode != selected:
                self.input_button.setChecked(False)
                QMessageBox.warning(
                    self,
                    "输出环路尚未切换",
                    f"设备当前环路为 {self._actual_channel_mode or '未知'}，"
                    f"界面选择为 {selected}。请先点击“安全切换”，确认切换完成后再开启负载。",
                )
                return
        self.device.set_input(checked)

    @Slot(str)
    def _on_channel_mode(self, mode: str) -> None:
        self._actual_channel_mode = mode
        # Only initialize the requested selection once. Periodic device polling
        # must not overwrite an operator's pending A/B/BOTH choice before they
        # press the explicit safe-switch button.
        if not self._channel_mode_initialized:
            index = self.channel_mode_combo.findData(mode)
            if index >= 0:
                self.channel_mode_combo.setCurrentIndex(index)
            self._channel_mode_initialized = True
        self.apply_channel_mode_button.setText(f"安全切换（当前 {mode}）")

    @Slot(float)
    def _on_fan_duty(self, duty_percent: float) -> None:
        self.fan_duty_value.setText(f"实际 {duty_percent:.1f}%")
        if not self.fan_duty_spin.hasFocus():
            self.fan_duty_spin.setValue(duty_percent)

    @Slot(int, float)
    def _apply_dac_voltage(self, channel: int, volts: float) -> None:
        self.device.set_dac_voltage(channel, volts)

    def _show_dac_dialog(self, channel: int | None = None) -> None:
        if channel is not None:
            self.dac_dialog.select_channel(channel)
        self.dac_dialog.show()
        self.dac_dialog.raise_()
        self.dac_dialog.activateWindow()

    @Slot()
    def _confirm_zero_dac(self) -> None:
        answer = QMessageBox.question(
            self,
            "双路 DAC 归零",
            "确认将 DAC 1 和 DAC 2 的设定电压同时归零吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.device.zero_dac()

    @Slot(object)
    def _on_dac_voltages(self, voltages: DacVoltages) -> None:
        self.dac_dialog.set_voltages(voltages)

    @Slot(object)
    def _on_measurements(self, snapshot: MeasurementSnapshot) -> None:
        self.voltage_value.setText(f"{snapshot.voltage_v:.4f}")
        self.current_value.setText(f"{snapshot.current_a:.4f}")
        self.power_value.setText(f"{snapshot.power_w:.4f}")
        self.left_temp_value.setText(f"{snapshot.left_temperature_c:.2f} °C")
        self.right_temp_value.setText(f"{snapshot.right_temperature_c:.2f} °C")
        self.trends.add_sample(snapshot)
        try:
            self.logger.append(snapshot)
        except OSError as exc:
            self._show_error(f"写入数据文件失败: {exc}")
            self._stop_recording()

    @Slot(object)
    def _on_status(self, status: DeviceStatus) -> None:
        self.state_value.setText(status.state)
        self.fault_value.setText(status.fault)
        self.requested_value.setText(f"{status.requested_current_a:.4f} A")
        if not self.current_setpoint.hasFocus():
            self.current_setpoint.setValue(status.requested_current_a)
        set_tone(self.fault_value, "error" if status.fault.upper() != "NONE" else "muted")

    @Slot(bool)
    def _on_input_state(self, enabled: bool) -> None:
        self._input_enabled = enabled
        self.input_button.setChecked(enabled)
        self.input_button.setText("负载 ON" if enabled else "负载 OFF")
        set_tone(self.input_button, "success" if enabled else "muted")
        self._update_dac_controls()
        self._refresh_load_status()

    @Slot(bool)
    def _toggle_recording(self, checked: bool) -> None:
        if not checked:
            self._stop_recording()
            return
        default_name = f"electronic_load_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存采集数据", str(Path.home() / default_name), "CSV 文件 (*.csv)"
        )
        if not path:
            self.record_action.setChecked(False)
            return
        try:
            self.logger.start(path)
        except OSError as exc:
            self._show_error(f"无法创建数据文件: {exc}")
            self.record_action.setChecked(False)
            return
        self.record_action.setText("停止记录曲线 CSV")
        self._append_log(f"开始记录: {path}")
        self._refresh_load_status()

    def _stop_recording(self) -> None:
        if self.logger.is_active:
            path = self.logger.path
            self.logger.stop()
            self._append_log(f"数据已保存: {path}")
        self.record_action.setChecked(False)
        self.record_action.setText("开始记录曲线 CSV…")
        self._refresh_load_status()

    @Slot(str)
    def _show_error(self, message: str) -> None:
        if not self.device.is_connected:
            self._connection_failed = True
            self.connection_label.setText("连接失败")
            set_tone(self.connection_label, "error")
        self.connection_error_text.setPlainText(message)
        self.connection_error_text.show()
        set_tone(self.device_menu_button, "error")
        self._append_log(f"错误: {message}")
        self._refresh_load_status()
        self._announce(message)

    def _clear_connection_error(self) -> None:
        self.connection_error_text.clear()
        self.connection_error_text.hide()
        set_tone(self.device_menu_button, "muted")

    @Slot(str, str)
    def _append_traffic(self, direction: str, text: str) -> None:
        self._append_log(f"{direction}  {text}")

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_view.appendPlainText(f"[{timestamp}] {text}")

    def _pd_closed(self) -> None:
        if self._close_deferred:
            self._close_deferred = False
            QTimer.singleShot(0, self.close)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        if not self._closing:
            if self.isVisible() and (self.pd_workspace.busy or self.logger.is_active):
                choice = QMessageBox.question(self, "退出上位机", "有捕获、回放或记录需要处理。可取消并先保存捕获。仍要退出？",
                                              QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                              QMessageBox.StandardButton.Cancel)
                if choice != QMessageBox.StandardButton.Yes:
                    event.ignore()
                    return
            self._closing = True
            running = self.pd_workspace.running
            self._close_deferred = running
            self.pd_workspace.shutdown()
            if running:
                self.setEnabled(False)
                event.ignore()
                return
        elif self.pd_workspace.running:
            event.ignore()
            return
        self._stop_recording()
        self.device.disconnect_device()
        event.accept()
