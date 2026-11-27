from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)


class HistoryPage(QWidget):
    request = Signal(str, object, object)

    def __init__(self, active_capture, replay_path, parent=None):
        super().__init__(parent)
        self._active_capture = active_capture
        self._replay_path = replay_path
        self._serial = 0
        self._current_query = 0
        self._page_cursors = [0]
        self._rows = []
        self._before = ""
        self._session_rows = []
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.sessions_box = QComboBox()
        self.sessions_box.setAccessibleName("历史会话")
        self.sessions_box.currentIndexChanged.connect(self.search)
        bar.addWidget(self.sessions_box, 1)
        self._button(bar, "刷新", self.refresh)
        self.older = self._button(bar, "更早轮次", self._older)
        self._button(bar, "删除会话", self._delete)
        layout.addLayout(bar)
        filters = QHBoxLayout()
        self.keyword = QLineEdit(placeholderText="消息、诊断代码或备注")
        self.keyword.returnPressed.connect(self.search)
        self.start = QLineEdit(placeholderText="起始 µs")
        self.end = QLineEdit(placeholderText="结束 µs")
        self.flagged = QCheckBox("已标记")
        for item in (self.keyword, self.start, self.end, self.flagged):
            filters.addWidget(item)
        self._button(filters, "查询", self.search)
        layout.addLayout(filters)
        categories = QHBoxLayout()
        endpoints = ("Source", "Sink", "Cable", "Port")
        self._categories = {}
        for key, label, options in (
            ("sender", "全部发送端", endpoints), ("receiver", "全部接收端", endpoints),
            ("sop", "全部 SOP", ("SOP", "SOP'", "SOP''", "Hard Reset", "Cable Reset")),
            ("crc", "全部 CRC", ("valid", "invalid", "unavailable")),
            ("state", "全部状态", ("valid", "complete", "invalid", "partial", "pending", "unsupported", "context_missing")),
            ("event_type", "全部事件", ("Attach", "Detach", "Hard Reset", "Cable Reset", "Protocol Error",
                                       "Sync Trigger", "OVP", "OCP", "Source Found", "Sink Error", "Sink Warning", "Firmware Event")),
        ):
            box = QComboBox()
            box.setAccessibleName(label)
            box.addItem(label, "")
            for option in options:
                box.addItem(option, option)
            box.currentIndexChanged.connect(self.search)
            self._categories[key] = box
            categories.addWidget(box)
        self._button(categories, "清除", self._clear)
        layout.addLayout(categories)
        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(("帧", "设备 µs", "发送", "接收", "SOP", "消息", "CRC", "事件", "备注"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda _: self.open_selected())
        layout.addWidget(self.table, 1)
        actions = QHBoxLayout()
        self.status = QLabel()
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        actions.addWidget(self.status, 1)
        self.previous = self._button(actions, "上一页", self._previous)
        self.next = self._button(actions, "下一页", self._next)
        self._button(actions, "打开原始记录", self.open_selected)
        layout.addLayout(actions)

    @staticmethod
    def _button(layout, label, action):
        button = QPushButton(label)
        button.clicked.connect(action)
        layout.addWidget(button)
        return button

    def refresh(self):
        self._before = ""
        self.request.emit("sessions", None, self._before)

    def _older(self):
        if self._session_rows:
            self._before = self._session_rows[-1]["started"]
            self.request.emit("sessions", None, self._before)

    def search(self):
        self._page_cursors = [0]
        self._query()

    def _clear(self):
        for field in (self.keyword, self.start, self.end):
            field.clear()
        self.flagged.setChecked(False)
        for box in self._categories.values():
            box.blockSignals(True)
            box.setCurrentIndex(0)
            box.blockSignals(False)
        self.search()

    def _query(self):
        session = self.sessions_box.currentData()
        self._serial += 1
        self._current_query = self._serial
        if not session:
            self._show_rows([])
            return
        try:
            bounds = [int(item.text()) if item.text() else None for item in (self.start, self.end)]
            if any(value is not None and not 0 <= value < 2**64 for value in bounds):
                raise ValueError
            if all(value is not None for value in bounds) and bounds[0] > bounds[1]:
                raise ValueError
        except ValueError:
            self.status.setText("设备时间范围无效")
            return
        self.request.emit("query", self._current_query, (session, {
            "after": self._page_cursors[-1], "limit": 201, "start": bounds[0], "end": bounds[1],
            "text": self.keyword.text().strip(), "flagged": self.flagged.isChecked(),
            **{field: box.currentData() for field, box in self._categories.items()},
        }))

    def _previous(self):
        if len(self._page_cursors) > 1:
            self._page_cursors.pop()
            self._query()

    def _next(self):
        if self._rows:
            self._page_cursors.append(self._rows[-1]["frame"])
            self._query()

    def _delete(self):
        session = self.sessions_box.currentData()
        if not session:
            return
        if self._active_capture():
            self.status.setText("请先停止捕获")
            return
        if QMessageBox.question(self, "删除历史会话", "删除此会话的本地历史、采样与标注？",
                                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.request.emit("remove", None, session)

    def open_selected(self):
        row = self.table.currentRow()
        session = self.sessions_box.currentData()
        if session and 0 <= row < len(self._rows):
            try:
                path = self._replay_path(session)
            except OSError as exc:
                self.status.setText(str(exc))
            else:
                self.request.emit("replay", self._rows[row]["frame"], (session, path))

    def result(self, action, token, payload, error):
        if action not in ("sessions", "query", "remove", "replay"):
            return
        if action == "query" and token != self._current_query:
            return
        if error:
            self.status.setText(error)
        elif action == "sessions":
            self._session_rows, size = payload
            current = self.sessions_box.currentData()
            self.sessions_box.blockSignals(True)
            self.sessions_box.clear()
            for row in self._session_rows:
                started = datetime.fromisoformat(row["started"]).astimezone()
                self.sessions_box.addItem(f"{started:%Y-%m-%d %H:%M:%S} · {row['id'][:8]}", row["id"])
            if (selected := self.sessions_box.findData(current)) >= 0:
                self.sessions_box.setCurrentIndex(selected)
            self.sessions_box.blockSignals(False)
            self.older.setEnabled(len(self._session_rows) == 100)
            self.status.setText(f"历史库 {size / (1024 * 1024):.2f} MiB")
            self.search()
        elif action == "query":
            self._show_rows(payload)
        elif action == "remove":
            self.refresh()

    def _show_rows(self, rows):
        has_next = len(rows) > 200
        rows = self._rows = rows[:200]
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            note = ("★ " if row["flagged"] else "") + (row["note"] or "")
            values = (row["frame"], int(row["timestamp"]), row["sender"], row["receiver"], row["sop"],
                      row["message"], row["crc"], row["event_type"], note)
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(str(value)))
        self.previous.setEnabled(len(self._page_cursors) > 1)
        self.next.setEnabled(has_next)
