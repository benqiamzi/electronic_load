from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .data_logger import CsvDataLogger
from .device import ElectronicLoadDevice
from .domain import DeviceStatus, MeasurementSnapshot
from .trend_widget import TrendWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("STM32F411 电子负载上位机")
        self.resize(1180, 800)
        self.device = ElectronicLoadDevice(self)
        self.logger = CsvDataLogger()
        self._input_enabled = False
        self._build_ui()
        self._connect_signals()
        self.refresh_ports()
        self._set_controls_enabled(False)

    def _build_ui(self) -> None:
        root = QWidget(self)
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)
        main_layout.addWidget(self._build_connection_bar())

        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        top = QWidget()
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._build_measurement_panel(), 2)
        top_layout.addWidget(self._build_control_panel(), 1)
        self.main_splitter.addWidget(top)

        lower = QSplitter(Qt.Orientation.Horizontal)
        self.trends = TrendWidget()
        lower.addWidget(self.trends)
        lower.addWidget(self._build_log_panel())
        lower.setStretchFactor(0, 4)
        lower.setStretchFactor(1, 1)
        self.main_splitter.addWidget(lower)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 4)
        main_layout.addWidget(self.main_splitter, 1)

    def _build_connection_bar(self) -> QWidget:
        box = QGroupBox("设备连接")
        layout = QHBoxLayout(box)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(260)
        self.refresh_button = QPushButton("刷新")
        self.connect_button = QPushButton("连接")
        self.connection_label = QLabel("未连接")
        self.connection_label.setStyleSheet("color: #888;")
        self.identity_label = QLabel("")
        layout.addWidget(QLabel("串口："))
        layout.addWidget(self.port_combo)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.connect_button)
        layout.addSpacing(12)
        layout.addWidget(self.connection_label)
        layout.addStretch(1)
        layout.addWidget(self.identity_label)
        return box

    def _measurement_card(self, title: str, unit: str) -> tuple[QFrame, QLabel]:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background: #24272b; border-radius: 6px; }"
            "QFrame QLabel { color: #d6d6d6; }"
        )
        layout = QVBoxLayout(frame)
        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value = QLabel("--")
        value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value.setStyleSheet("font-size: 28px; font-weight: 600; color: #e8e8e8;")
        unit_label = QLabel(unit)
        unit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        layout.addWidget(value, 1)
        layout.addWidget(unit_label)
        return frame, value

    def _build_measurement_panel(self) -> QWidget:
        box = QGroupBox("实时测量")
        layout = QGridLayout(box)
        voltage_card, self.voltage_value = self._measurement_card("电压", "V")
        current_card, self.current_value = self._measurement_card("电流", "A")
        power_card, self.power_value = self._measurement_card("功率", "W")
        left_card, self.left_temp_value = self._measurement_card("左侧温度", "°C")
        right_card, self.right_temp_value = self._measurement_card("右侧温度", "°C")
        layout.addWidget(voltage_card, 0, 0)
        layout.addWidget(current_card, 0, 1)
        layout.addWidget(power_card, 0, 2)
        layout.addWidget(left_card, 1, 0)
        layout.addWidget(right_card, 1, 1)
        self.record_button = QPushButton("开始记录 CSV")
        self.record_button.setCheckable(True)
        self.clear_plot_button = QPushButton("清空曲线")
        actions = QVBoxLayout()
        actions.addWidget(self.record_button)
        actions.addWidget(self.clear_plot_button)
        actions.addStretch(1)
        layout.addLayout(actions, 1, 2)
        return box

    def _build_control_panel(self) -> QWidget:
        box = QGroupBox("负载控制")
        layout = QGridLayout(box)
        self.current_setpoint = QDoubleSpinBox()
        self.current_setpoint.setRange(0.0, 5.0)
        self.current_setpoint.setDecimals(4)
        self.current_setpoint.setSingleStep(0.01)
        self.current_setpoint.setSuffix(" A")
        self.apply_current_button = QPushButton("应用电流")
        self.input_button = QPushButton("负载 OFF")
        self.input_button.setCheckable(True)
        self.input_button.setMinimumHeight(42)
        self.emergency_button = QPushButton("紧急关闭")
        self.emergency_button.setMinimumHeight(42)
        self.emergency_button.setStyleSheet(
            "QPushButton { background: #a32626; color: white; font-weight: bold; }"
        )
        self.clear_fault_button = QPushButton("清除故障")
        self.reset_button = QPushButton("设备复位")
        self.state_value = QLabel("--")
        self.fault_value = QLabel("--")
        self.requested_value = QLabel("--")
        layout.addWidget(QLabel("恒流设定："), 0, 0)
        layout.addWidget(self.current_setpoint, 0, 1)
        layout.addWidget(self.apply_current_button, 1, 0, 1, 2)
        layout.addWidget(self.input_button, 2, 0, 1, 2)
        layout.addWidget(self.emergency_button, 3, 0, 1, 2)
        layout.addWidget(QLabel("运行状态："), 4, 0)
        layout.addWidget(self.state_value, 4, 1)
        layout.addWidget(QLabel("锁存故障："), 5, 0)
        layout.addWidget(self.fault_value, 5, 1)
        layout.addWidget(QLabel("设备设定："), 6, 0)
        layout.addWidget(self.requested_value, 6, 1)
        layout.addWidget(self.clear_fault_button, 7, 0)
        layout.addWidget(self.reset_button, 7, 1)
        layout.setRowStretch(8, 1)
        self._control_widgets = [
            self.current_setpoint,
            self.apply_current_button,
            self.input_button,
            self.emergency_button,
            self.clear_fault_button,
            self.reset_button,
            self.record_button,
        ]
        return box

    def _build_log_panel(self) -> QWidget:
        box = QGroupBox("通信日志")
        layout = QVBoxLayout(box)
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.document().setMaximumBlockCount(1000)
        clear_button = QPushButton("清空日志")
        clear_button.clicked.connect(self.log_view.clear)
        layout.addWidget(self.log_view)
        layout.addWidget(clear_button)
        return box

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self._toggle_connection)
        self.apply_current_button.clicked.connect(
            lambda: self.device.set_current(self.current_setpoint.value())
        )
        self.input_button.clicked.connect(
            lambda checked: self.device.set_input(bool(checked))
        )
        self.emergency_button.clicked.connect(lambda: self.device.set_input(False))
        self.clear_fault_button.clicked.connect(self.device.clear_fault)
        self.reset_button.clicked.connect(self.device.reset_device)
        self.clear_plot_button.clicked.connect(self.trends.clear)
        self.record_button.clicked.connect(self._toggle_recording)
        self.device.connection_changed.connect(self._on_connection_changed)
        self.device.identity_changed.connect(self.identity_label.setText)
        self.device.measurements_updated.connect(self._on_measurements)
        self.device.status_updated.connect(self._on_status)
        self.device.input_state_updated.connect(self._on_input_state)
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
        port_name = self.port_combo.currentData()
        if port_name:
            self.device.connect_to(str(port_name))
        else:
            self._show_error("没有可连接的串口")

    @Slot(bool, str)
    def _on_connection_changed(self, connected: bool, message: str) -> None:
        self.connection_label.setText(message)
        self.connection_label.setStyleSheet("color: #57c75b;" if connected else "color: #888;")
        self.connect_button.setText("断开" if self.device.transport.is_open else "连接")
        self.port_combo.setEnabled(not self.device.transport.is_open)
        self.refresh_button.setEnabled(not self.device.transport.is_open)
        self._set_controls_enabled(connected)
        if not connected:
            self._stop_recording()
            self._on_input_state(False)

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in self._control_widgets:
            widget.setEnabled(enabled)

    @Slot(object)
    def _on_measurements(self, snapshot: MeasurementSnapshot) -> None:
        self.voltage_value.setText(f"{snapshot.voltage_v:.4f}")
        self.current_value.setText(f"{snapshot.current_a:.4f}")
        self.power_value.setText(f"{snapshot.power_w:.4f}")
        self.left_temp_value.setText(f"{snapshot.left_temperature_c:.2f}")
        self.right_temp_value.setText(f"{snapshot.right_temperature_c:.2f}")
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
        has_fault = status.fault.upper() != "NONE"
        self.fault_value.setStyleSheet("color: #ff5b5b; font-weight: bold;" if has_fault else "")

    @Slot(bool)
    def _on_input_state(self, enabled: bool) -> None:
        self._input_enabled = enabled
        self.input_button.setChecked(enabled)
        self.input_button.setText("负载 ON" if enabled else "负载 OFF")
        self.input_button.setStyleSheet(
            "QPushButton { background: #2c8b47; color: white; font-weight: bold; }"
            if enabled
            else ""
        )

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
            self.record_button.setChecked(False)
            return
        try:
            self.logger.start(path)
        except OSError as exc:
            self._show_error(f"无法创建数据文件: {exc}")
            self.record_button.setChecked(False)
            return
        self.record_button.setText("停止记录 CSV")
        self._append_log(f"开始记录: {path}")

    def _stop_recording(self) -> None:
        if self.logger.is_active:
            path = self.logger.path
            self.logger.stop()
            self._append_log(f"数据已保存: {path}")
        self.record_button.setChecked(False)
        self.record_button.setText("开始记录 CSV")

    @Slot(str)
    def _show_error(self, message: str) -> None:
        self.connection_label.setText(message)
        self.connection_label.setStyleSheet("color: #ff5b5b;")
        self._append_log(f"错误: {message}")

    @Slot(str, str)
    def _append_traffic(self, direction: str, text: str) -> None:
        self._append_log(f"{direction}  {text}")

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_view.appendPlainText(f"[{timestamp}] {text}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self._stop_recording()
        self.device.disconnect_device()
        event.accept()
