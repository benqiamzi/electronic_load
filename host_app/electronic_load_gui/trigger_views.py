from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtCore import QRegularExpression, Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from .services.trigger_service import EVENTS, SENDERS, SYNC_MODES, TriggerConfig, TriggerState


class TriggerPage(QWidget):
    def __init__(self, device, parent=None):
        super().__init__(parent)
        self._device = device
        self._state = TriggerState()
        self._editing = False
        layout = QVBoxLayout(self)
        panel = QGroupBox("DRPD Trigger")
        layout.addWidget(panel)
        form = QFormLayout(panel)
        self.status = QLabel("等待设备读回")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        form.addRow("设备状态", self.status)
        self.event = self._choices(form, "事件类型", EVENTS)
        self.threshold = self._number(form, "事件阈值")
        self.sender = self._choices(form, "发送端过滤", SENDERS)
        self.filters = QLineEdit(placeholderText="CONTROL:3 DATA:1")
        self.filters.textEdited.connect(self._edited)
        form.addRow("消息类型过滤", self.filters)
        self.repeat = QCheckBox("自动重复")
        self.repeat.toggled.connect(self._edited)
        form.addRow(self.repeat)
        self.sync = self._choices(form, "Sync 模式", SYNC_MODES)
        self.width = self._number(form, "Sync 脉宽 µs")
        self.inputs = (self.event, self.threshold, self.sender, self.filters, self.repeat, self.sync, self.width)
        buttons = QHBoxLayout()
        self.refresh = QPushButton("读回")
        self.refresh.clicked.connect(self._refresh)
        self.apply = QPushButton("应用")
        self.apply.clicked.connect(self._apply)
        self.reset = QPushButton("复位")
        self.reset.clicked.connect(self._reset)
        for button in (self.refresh, self.apply, self.reset):
            buttons.addWidget(button)
        form.addRow(buttons)
        layout.addStretch()
        device.trigger_changed.connect(self.set_state)
        device.changed.connect(lambda _: self._update_controls())
        self._update_controls()

    def _choices(self, form, label, items):
        control = QComboBox()
        control.addItems(items)
        control.currentIndexChanged.connect(self._edited)
        form.addRow(label, control)
        return control

    def _number(self, form, label):
        control = QLineEdit()
        control.setValidator(QRegularExpressionValidator(QRegularExpression(r"\d{0,10}"), control))
        control.textEdited.connect(self._edited)
        form.addRow(label, control)
        return control

    def _edited(self):
        self._editing = True

    def _refresh(self):
        self._editing = False
        self._device.refresh_trigger.emit()

    def _reset(self):
        self._editing = False
        self._device.reset_trigger.emit()

    def _apply(self):
        try:
            config = TriggerConfig(self.event.currentText(), int(self.threshold.text()), self.sender.currentText(),
                                   tuple(self.filters.text().upper().split()), "ON" if self.repeat.isChecked() else "OFF",
                                   self.sync.currentText(), int(self.width.text()))
            config.validate()
        except ValueError as exc:
            self.status.setText(f"触发配置无效 · {exc}")
            return
        self._editing = False
        self._device.apply_trigger.emit(config)

    def set_state(self, state):
        self._state = state
        config = state.config
        if config is not None and not self._editing:
            for item in self.inputs:
                item.blockSignals(True)
            self.event.setCurrentText(config.event)
            self.threshold.setText(str(config.threshold))
            self.sender.setCurrentText(config.sender)
            self.filters.setText(" ".join(config.filters))
            self.repeat.setChecked(config.repeat == "ON")
            self.sync.setCurrentText(config.sync)
            self.width.setText(str(config.width_us))
            for item in self.inputs:
                item.blockSignals(False)
        elif not state.available:
            self._editing = False
        self._update_controls()

    def _update_controls(self):
        state = self._state
        active = self._device.state.capture != "idle"
        connected = self._device.state.connection == "connected"
        editable = connected and state.available and state.config is not None and not state.busy and not active
        for item in self.inputs:
            item.setEnabled(editable)
        self.refresh.setEnabled(connected and state.available and not state.busy)
        self.apply.setEnabled(editable)
        self.reset.setEnabled(editable)
        message = "设备未连接" if not connected else "触发接口不可用"
        if state.busy:
            message = "等待触发设备读回"
        elif state.status and connected:
            message = f"{state.status} · {state.count} 次事件"
        self.status.setText(" · ".join(value for value in (message, state.message) if value))
