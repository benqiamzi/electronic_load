from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QStyle, QToolButton, QVBoxLayout, QWidgetAction


class _WorkspaceOption(QPushButton):
    def sizeHint(self):
        # A menu action takes its size from the button, including its child labels.
        hint = super().sizeHint()
        layout = self.layout()
        return hint.expandedTo(layout.sizeHint()) if layout is not None else hint


class WorkspaceSelector(QToolButton):
    selected = Signal(int)
    NAMES = ("电子负载", "USB PD 测试")
    DESCRIPTIONS = ("实时测量、负载控制与曲线记录", "DRPD 捕获、协议分析与离线回放")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceSelector")
        self.setAccessibleName("切换工作区")
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._menu = QMenu(self)
        self.setMenu(self._menu)
        self._items = []
        self._check = self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton).pixmap(16, 16)
        for index, standard in enumerate((QStyle.StandardPixmap.SP_DriveHDIcon, QStyle.StandardPixmap.SP_ComputerIcon)):
            icon = self.style().standardIcon(standard)
            button = _WorkspaceOption()
            button.setProperty("role", "workspaceOption")
            button.setAccessibleName(self.NAMES[index])
            button.setMinimumWidth(280)
            row = QHBoxLayout(button)
            row.setContentsMargins(10, 8, 10, 8)
            icon_label = QLabel()
            icon_label.setPixmap(icon.pixmap(18, 18))
            title = QLabel(self.NAMES[index])
            title.setProperty("role", "summary")
            caption = QLabel(self.DESCRIPTIONS[index])
            caption.setProperty("role", "caption")
            check = QLabel()
            check.setFixedSize(16, 16)
            labels = QVBoxLayout()
            labels.setSpacing(2)
            labels.addWidget(title)
            labels.addWidget(caption)
            row.addWidget(icon_label)
            row.addLayout(labels, 1)
            row.addWidget(check)
            for label in (icon_label, title, caption, check):
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            action = QWidgetAction(self._menu)
            action.setText(self.NAMES[index])
            action.setDefaultWidget(button)
            button.clicked.connect(action.trigger)
            action.triggered.connect(lambda checked=False, value=index: self._select(value))
            self._menu.addAction(action)
            self._items.append((button, icon, check))
        self.set_current(0)

    def _select(self, index: int) -> None:
        self._menu.close()
        self.selected.emit(index)

    def set_current(self, index: int) -> None:
        self.setText(self.NAMES[index])
        self.setIcon(self._items[index][1])
        for position, (button, _, check) in enumerate(self._items):
            active = position == index
            if active:
                check.setPixmap(self._check)
            else:
                check.clear()
            button.setProperty("active", active)
            button.style().unpolish(button)
            button.style().polish(button)
