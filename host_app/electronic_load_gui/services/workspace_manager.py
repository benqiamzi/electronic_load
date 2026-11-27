from PySide6.QtCore import QObject, QSettings, Signal


class WorkspaceManager(QObject):
    changed = Signal(int)

    def __init__(self, parent: QObject, settings: QSettings | None = None) -> None:
        super().__init__(parent)
        self.settings = settings if settings is not None else QSettings("ElectronicLoad", "Host UI")
        self.index = 1 if self.settings.value("workspace/active") == "usb_pd" else 0

    def select(self, index: int) -> None:
        if index not in (0, 1) or index == self.index:
            return
        self.index = index
        self.settings.setValue("workspace/active", "usb_pd" if index else "electronic_load")
        self.changed.emit(index)
