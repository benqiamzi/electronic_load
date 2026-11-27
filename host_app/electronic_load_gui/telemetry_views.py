from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
    QMenu, QMessageBox, QPushButton, QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from .services.telemetry_service import TelemetryState
from .theme import PLACEHOLDER


class MeasurementPage(QWidget):
    def __init__(self, device, settings, parent=None):
        super().__init__(parent)
        self._state = TelemetryState()
        self._device = device
        self._settings = settings
        self._values = {}
        self._panels = {}
        layout = QVBoxLayout(self)
        self.status = QLabel("设备未连接")
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        header = QHBoxLayout()
        header.addWidget(self.status, 1)
        layout.addLayout(header)
        panels = QSplitter(Qt.Orientation.Horizontal)
        panels.setChildrenCollapsible(False)
        layout.addWidget(panels)
        vbus = self._panel(panels, "VBUS / IBUS", (
            ("voltage", "电压"), ("current", "电流"), ("power", "功率"),
            ("protection", "保护状态"), ("ovp_us", "最近 OVP"), ("ocp_us", "最近 OCP"),
        ))
        cc = self._panel(panels, "CC Lines", (
            ("dut_cc1", "DUT CC1"), ("dut_cc2", "DUT CC2"),
            ("usds_cc1", "USDS CC1"), ("usds_cc2", "USDS CC2"), ("active_cc", "活动通道"),
        ))
        accumulator = self._panel(panels, "Accumulator", (
            ("elapsed_us", "累计时间"), ("charge_mah", "累计电荷"), ("energy_mwh", "累计能量"),
        ))
        self._thresholds = {}
        for key, maximum, unit in (("ovp", 60, "V"), ("ocp", 6, "A")):
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            value = QLabel(PLACEHOLDER)
            self._values[key] = value
            spin = QDoubleSpinBox()
            spin.setRange(0, maximum)
            spin.setDecimals(2)
            spin.setSuffix(" " + unit)
            spin.setAccessibleName(f"{key.upper()} 新阈值")
            button = QPushButton("设置")
            button.clicked.connect(lambda _checked=False, field=key, editor=spin: self._set_threshold(field, editor))
            row.addWidget(value)
            row.addWidget(spin)
            row.addWidget(button)
            self._thresholds[key] = (spin, button)
            vbus.addRow(key.upper(), holder)
        self._reset_protection = QPushButton("复位 VBUS 故障")
        self._reset_protection.clicked.connect(lambda: self._confirm(
            "复位 VBUS 故障", "确认复位当前保护，设备可能恢复供电。", self._device.reset_protection.emit
        ))
        vbus.addRow(self._reset_protection)
        self._reset_accumulator = QPushButton("累计量清零")
        self._reset_accumulator.clicked.connect(lambda: self._confirm(
            "累计量清零", "确认清除设备累计的时间、电荷和能量。", self._device.reset_accumulator.emit
        ))
        accumulator.addRow(self._reset_accumulator)
        for form in (vbus, cc, accumulator):
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self._splitter = panels
        self._setup_layout_menu(header)
        layout.addStretch()
        device.telemetry_changed.connect(self.update_state)
        self._clock = QTimer(self, interval=500)
        self._clock.timeout.connect(self._render)
        self._clock.start()
        self._render()

    def _panel(self, container, title, rows):
        panel = QGroupBox(title)
        form = QFormLayout(panel)
        for key, name in rows:
            value = QLabel(PLACEHOLDER)
            value.setTextFormat(Qt.TextFormat.PlainText)
            value.setWordWrap(True)
            self._values[key] = value
            form.addRow(name, value)
        container.addWidget(panel)
        self._panels[title] = panel
        return form

    def _setup_layout_menu(self, header):
        button = QToolButton()
        button.setText("仪表布局")
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(button)
        self._layout_actions = {}
        hidden = self._settings.value("pd/layout-v1/measurement-hidden", [], type=list)
        for name, panel in self._panels.items():
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name not in hidden)
            panel.setVisible(action.isChecked())
            action.toggled.connect(self._apply_layout)
            self._layout_actions[name] = action
        menu.addSeparator()
        menu.addAction("恢复默认", self._reset_layout)
        button.setMenu(menu)
        header.addWidget(button)
        saved = self._settings.value("pd/layout-v1/measurement-split")
        if saved:
            self._splitter.restoreState(saved)
        self._splitter.splitterMoved.connect(lambda *_: self._settings.setValue(
            "pd/layout-v1/measurement-split", self._splitter.saveState()
        ))

    def _apply_layout(self):
        hidden = []
        for name, action in self._layout_actions.items():
            self._panels[name].setVisible(action.isChecked())
            if not action.isChecked():
                hidden.append(name)
        self._settings.setValue("pd/layout-v1/measurement-hidden", hidden)

    def _reset_layout(self):
        for action in self._layout_actions.values():
            action.setChecked(True)
        self._splitter.setSizes([400, 280, 275])
        self._settings.remove("pd/layout-v1/measurement-split")

    def _confirm(self, title, message, action):
        if QMessageBox.question(
            self, title, message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        ) == QMessageBox.StandardButton.Yes:
            action()

    def _set_threshold(self, field, spin):
        value = spin.value()
        self._confirm(field.upper(), f"确认设置新的保护阈值 {spin.text()}？",
                      lambda: self._device.set_threshold.emit(field, value))

    @Slot(object)
    def update_state(self, state):
        for key, (spin, _) in self._thresholds.items():
            value = getattr(state, key)
            if value is not None and value != getattr(self._state, key):
                spin.setValue(value)
        self._state = state
        self._render()

    def _render(self):
        state = self._state
        now = datetime.now(timezone.utc)
        sample = state.sample
        fresh = sample and (now - sample.received_at).total_seconds() < 3
        values = {}
        if fresh:
            values.update({key: f"{getattr(sample, key):.2f} V" for key in
                           ("voltage", "dut_cc1", "dut_cc2", "usds_cc1", "usds_cc2")})
            values.update(current=f"{sample.current:.2f} A", power=f"{sample.voltage * sample.current:.2f} W",
                          elapsed_us=f"{sample.elapsed_us / 1e6:.3f} s",
                          charge_mah=f"{sample.charge_mah} mAh", energy_mwh=f"{sample.energy_mwh} mWh")
        role = state.role
        if role and role.attach == "ATTACHED":
            values["active_cc"] = f"{role.source_port} {role.source_cc} / {role.sink_port} {role.sink_cc}"
        if state.protection:
            values["protection"] = state.protection.status
            for key in ("ovp_us", "ocp_us"):
                event = getattr(state.protection, key)
                values[key] = "无" if event is None else f"{event} µs"
        for key, unit in (("ovp", "V"), ("ocp", "A")):
            threshold = getattr(state, key)
            if threshold is not None:
                values[key] = f"{threshold:g} {unit}"
            spin, button = self._thresholds[key]
            spin.setEnabled(threshold is not None and not state.busy)
            button.setEnabled(spin.isEnabled())
        for key, label in self._values.items():
            label.setText(values.get(key, PLACEHOLDER))
        self._reset_accumulator.setEnabled(bool(fresh) and not state.busy)
        self._reset_protection.setEnabled(values.get("protection") in ("OVP", "OCP") and not state.busy)
        status = "设备未连接或测量不可用"
        if state.available:
            status = "等待 DRPD 测量数据" if sample is None else "DRPD 测量读数已过期"
        if fresh:
            status = f"DRPD MEAS:ALL? · 设备 {sample.timestamp_us} µs · 接收 {sample.received_at.astimezone():%H:%M:%S}"
        self.status.setText(" · ".join(part for part in (status, state.message) if part))
