from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .domain import DacVoltages, PROTECTION_RANGES, ProtectionThresholds
from .theme import PLACEHOLDER, set_tone


class ProtectionDialog(QDialog):
    read_requested = Signal()
    apply_requested = Signal(object)
    restore_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("保护阈值")
        self.setMinimumWidth(410)
        self._connected = False
        self._supported = False
        self._input_enabled: bool | None = None
        self._thresholds: ProtectionThresholds | None = None
        self._busy = False
        self._error = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        settings = QGroupBox("设备保护阈值")
        form = QFormLayout(settings)
        self.spins: list[QDoubleSpinBox] = []
        fields = (
            ("过压保护", " V", 0.1),
            ("过流保护", " A", 0.01),
            ("过功率保护", " W", 1.0),
            ("过温保护", " °C", 1.0),
        )
        for (label, unit, step), (low, high) in zip(fields, PROTECTION_RANGES):
            spin = QDoubleSpinBox()
            spin.setDecimals(4)
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setSuffix(unit)
            spin.setAccessibleName(label)
            spin.clear()
            form.addRow(label, spin)
            self.spins.append(spin)
        self.temperature_status = QLabel()
        self.temperature_status.setProperty("role", "muted")
        form.addRow("", self.temperature_status)
        layout.addWidget(settings)

        self.status_label = QLabel()
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)
        self.status_label.setProperty("role", "summary")
        layout.addWidget(self.status_label)
        note = QLabel("阈值在设备断电后恢复默认。过流设置适用于软件保护，快速硬件切断独立生效。")
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)

        self.read_button = QPushButton("重新读取")
        self.restore_button = QPushButton("恢复默认…")
        self.apply_button = QPushButton("应用阈值")
        self.apply_button.setProperty("variant", "primary")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.addButton(self.read_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(self.restore_button, QDialogButtonBox.ButtonRole.ResetRole)
        buttons.addButton(self.apply_button, QDialogButtonBox.ButtonRole.ApplyRole)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.read_button.clicked.connect(self.read)
        self.apply_button.clicked.connect(self._apply)
        self.restore_button.clicked.connect(self._restore)
        self._update_controls()

    def set_context(self, *, connected: bool, supported: bool) -> None:
        self._connected = connected
        self._supported = supported
        self._input_enabled = None
        self._busy = False
        self._error = ""
        self._clear_thresholds()
        self._update_controls()

    @Slot(bool)
    def set_input_state(self, enabled: bool) -> None:
        self._input_enabled = enabled
        self._update_controls()

    @Slot()
    def read(self) -> None:
        if self.read_button.isEnabled():
            self._begin_request()
            self.read_requested.emit()

    @Slot(object)
    def set_thresholds(self, thresholds: ProtectionThresholds) -> None:
        self._thresholds = thresholds
        self._busy = False
        self._error = ""
        for spin, value in zip(self.spins, thresholds.values()):
            spin.setValue(value)
            # A value equal to the current minimum may still have an empty editor.
            spin.lineEdit().setText(spin.textFromValue(value) + spin.suffix())
        self._update_controls()

    @Slot(str)
    def show_error(self, message: str) -> None:
        self._busy = False
        self._error = message
        self._clear_thresholds()
        self._update_controls()

    def _clear_thresholds(self) -> None:
        self._thresholds = None
        for spin in self.spins:
            spin.clear()

    def _begin_request(self) -> None:
        self._busy = True
        self._error = ""
        self._update_controls()

    @Slot()
    def _apply(self) -> None:
        thresholds = ProtectionThresholds(*(spin.value() for spin in self.spins))
        self._begin_request()
        self.apply_requested.emit(thresholds)

    @Slot()
    def _restore(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认保护阈值",
            "确认将设备的保护阈值恢复为固件默认值？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes and self.restore_button.isEnabled():
            self._begin_request()
            self.restore_requested.emit()

    def _update_controls(self) -> None:
        can_read = self._supported and not self._busy
        can_edit = can_read and self._thresholds is not None and self._input_enabled is False
        self.read_button.setEnabled(can_read)
        self.apply_button.setEnabled(can_edit)
        self.restore_button.setEnabled(can_edit)
        for spin in self.spins[:-1]:
            spin.setEnabled(can_edit)
        temperature_enabled = (
            self._thresholds is not None and self._thresholds.temperature_enabled
        )
        self.spins[-1].setEnabled(can_edit and temperature_enabled)
        self.temperature_status.setText(
            "当前板卡未启用温度保护" if self._thresholds and not temperature_enabled else ""
        )
        self.temperature_status.setVisible(bool(self.temperature_status.text()))
        tone = "muted"
        if not self._connected:
            message = "请先连接电子负载。"
        elif not self._supported:
            message = "设置保护阈值需要固件 0.3.7 或更新版本。"
        elif self._busy:
            message = "正在等待设备返回保护阈值…"
        elif self._error:
            message = f"保护操作失败：{self._error}。请重新读取设备。"
            tone = "error"
        elif self._input_enabled is True:
            message = "负载已开启。关闭负载后可修改阈值。"
            tone = "warning"
        elif self._input_enabled is None:
            message = "等待设备确认负载状态…"
        elif self._thresholds is not None:
            message = "设备已确认当前保护阈值。"
            tone = "success"
        else:
            message = "读取设备当前的保护阈值后可进行设置。"
        self.status_label.setText(message)
        set_tone(self.status_label, tone)


class DacControlDialog(QDialog):
    """Modeless DAC status and diagnostic voltage control window."""

    apply_requested = Signal(int, float)
    zero_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("DAC 输出查看与设置")
        self.setModal(False)
        self.setMinimumWidth(430)
        self._mode = "AUTO"
        self._build_ui()
        self.set_context(connected=False, supported=False, input_enabled=False,
                         live_supported=False)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 14)
        layout.setSpacing(9)

        status_group = QGroupBox("DAC 设定输出")
        status_layout = QHBoxLayout(status_group)
        self.channel_1_value = QLabel(f"DAC 1\n{PLACEHOLDER} V")
        self.channel_2_value = QLabel(f"DAC 2\n{PLACEHOLDER} V")
        self.channel_1_value.setProperty("role", "dacReadout")
        self.channel_2_value.setProperty("role", "dacReadout")
        status_layout.addWidget(self.channel_1_value)
        status_layout.addWidget(self.channel_2_value)
        layout.addWidget(status_group)

        settings_group = QGroupBox("单通道设置")
        settings_layout = QFormLayout(settings_group)
        self.channel_combo = QComboBox()
        self.channel_combo.addItem("DAC 1（通道 A）", 1)
        self.channel_combo.addItem("DAC 2（通道 B）", 2)
        self.voltage_spin = QDoubleSpinBox()
        self.voltage_spin.setRange(0.0, 2.5)
        self.voltage_spin.setDecimals(5)
        self.voltage_spin.setSingleStep(0.01)
        self.voltage_spin.setSuffix(" V")
        self.apply_button = QPushButton("应用到所选通道")
        self.apply_button.setProperty("variant", "primary")
        self.zero_button = QPushButton("双路 DAC 归零")
        self.zero_button.setProperty("variant", "warning")
        settings_layout.addRow("通道：", self.channel_combo)
        settings_layout.addRow("设定电压：", self.voltage_spin)
        settings_layout.addRow(self.apply_button)
        settings_layout.addRow(self.zero_button)
        layout.addWidget(settings_group)

        self.context_label = QLabel()
        self.context_label.setProperty("role", "summary")
        self.context_label.setWordWrap(True)
        layout.addWidget(self.context_label)
        note = QLabel(
            "说明：这里显示的是固件记录的最近成功写入值。DAC8552 没有输出回读 ADC，"
            "因此不是物理电压实测值。带载直写仍保留过流和故障保护。"
        )
        note.setWordWrap(True)
        note.setProperty("role", "muted")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.apply_button.clicked.connect(self._emit_apply)
        self.zero_button.clicked.connect(lambda: self.zero_requested.emit())

    @Slot()
    def _emit_apply(self) -> None:
        self.apply_requested.emit(
            int(self.channel_combo.currentData()),
            self.voltage_spin.value(),
        )

    def select_channel(self, channel: int) -> None:
        index = self.channel_combo.findData(channel)
        if index >= 0:
            self.channel_combo.setCurrentIndex(index)

    def set_voltages(self, voltages: DacVoltages | None) -> None:
        if voltages is None:
            self.channel_1_value.setText(f"DAC 1\n{PLACEHOLDER} V")
            self.channel_2_value.setText(f"DAC 2\n{PLACEHOLDER} V")
            return
        self.channel_1_value.setText(f"DAC 1\n{voltages.channel_1_v:.5f} V")
        self.channel_2_value.setText(f"DAC 2\n{voltages.channel_2_v:.5f} V")

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.set_context(**self._context)

    def set_context(self, *, connected: bool, supported: bool, input_enabled: bool,
                    live_supported: bool) -> None:
        self._context = dict(connected=connected, supported=supported,
                             input_enabled=input_enabled, live_supported=live_supported)
        controls_enabled = connected and supported and (not input_enabled or live_supported)
        self.voltage_spin.setMaximum(0.5 if input_enabled and live_supported else 2.5)
        for widget in (
            self.channel_combo,
            self.voltage_spin,
            self.apply_button,
            self.zero_button,
        ):
            widget.setEnabled(controls_enabled)

        if not connected:
            message = "设备未连接。"
            tone = "muted"
        elif not supported:
            message = "当前固件不支持单通道 DAC 电压控制，请升级到 0.2.0 或更高版本。"
            tone = "warning"
        elif input_enabled and not live_supported:
            message = "负载当前已开启。请先关闭负载，再修改 DAC 诊断电压。"
            tone = "warning"
        elif input_enabled:
            message = (
                f"带载 DAC 模式：{self._mode}。A+B 电压合计不超过 0.5 V；"
                "写入后保持手动设定，应用电流可恢复自动控制，关闭负载会归零。"
            )
            tone = "warning"
        else:
            message = "负载已关闭，可设置 0～2.5 V；再次开启负载时 DAC 会先归零。"
            tone = "success"
        self.context_label.setText(message)
        set_tone(self.context_label, tone)
