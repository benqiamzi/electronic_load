from dataclasses import asdict, dataclass, replace
import re

from PySide6.QtCore import QObject, Signal, Slot

from .telemetry_service import unsigned


EVENTS = ("OFF", "PREAMBLE_START", "SOP_START", "HEADER_START", "DATA_START", "MESSAGE_COMPLETE",
          "HARD_RESET_RECEIVED", "INVALID_KCODE", "CRC_ERROR", "TIMEOUT_ERROR", "RUNT_PULSE_ERROR", "ANY_ERROR")
SENDERS = ("ANY", "SOURCE", "SINK", "CABLE")
SYNC_MODES = ("PULSE_HIGH", "PULSE_LOW", "TOGGLE", "PULL_DOWN")
_PREFIXES = (
    "TRIG:EV:TYPE", "TRIG:EV:THRESH", "TRIG:EV:SEND", "TRIG:EV:MSGTYPE:FILT",
    "TRIG:EV:AUTOREPEAT", "TRIG:SYNC:MODE", "TRIG:SYNC:PULSE",
)
_FILTER = re.compile(r"(?:CONTROL|DATA):(?:[0-9]|[12][0-9]|3[01])")


@dataclass(frozen=True, slots=True)
class TriggerConfig:
    event: str
    threshold: int
    sender: str
    filters: tuple[str, ...]
    repeat: str
    sync: str
    width_us: int

    def validate(self, *, min_number=1):
        if self.event not in EVENTS or self.sender not in SENDERS or self.sync not in SYNC_MODES:
            raise ValueError("触发枚举不受固件支持")
        if self.repeat not in ("ON", "OFF") or not min_number <= self.threshold < 2**32 or not min_number <= self.width_us < 2**32:
            raise ValueError("次数和脉宽须为 1–4294967295 的整数")
        if len(self.filters) > 8 or len(set(self.filters)) != len(self.filters) or any(
            not _FILTER.fullmatch(item) for item in self.filters
        ):
            raise ValueError("最多 8 个互异过滤项，格式为 CONTROL:0–31 或 DATA:0–31")

    @classmethod
    def parse(cls, lines):
        event, count, sender, filters, repeat, sync, width = lines
        config = cls(event, unsigned(count, 32), sender, tuple(filters.split()), repeat, sync, unsigned(width, 32))
        config.validate(min_number=0)
        return config


@dataclass(frozen=True, slots=True)
class TriggerState:
    available: bool = False
    busy: bool = False
    writing: bool = False
    config: TriggerConfig | None = None
    status: str = ""
    count: int | None = None
    message: str = ""


class TriggerService(QObject):
    changed = Signal(object)

    def __init__(self, protocol, can_configure, parent=None):
        super().__init__(parent)
        self._protocol = protocol
        self._can_configure = can_configure
        self._state = TriggerState()
        self._generation = 0

    def activate(self, firmware):
        self._publish(available=firmware == "1.0.0-beta.1")
        if self._state.available:
            self.refresh()

    def disconnect(self):
        self._generation += 1
        self._state = TriggerState()
        self.changed.emit(self._state)

    def metadata(self):
        return asdict(self._state.config) if self._state.config is not None and not self._state.writing else None

    @property
    def writing(self):
        return self._state.writing

    @property
    def loading_initial_config(self):
        return self._state.busy and self._state.config is None and not self._state.writing

    def _publish(self, **changes):
        self._state = replace(self._state, **changes)
        self.changed.emit(self._state)

    @Slot()
    def refresh(self):
        if self._state.available and not self._state.busy:
            self._execute(())

    @Slot(object)
    def apply(self, config: TriggerConfig):
        if not self._state.available or self._state.busy or not self._can_configure():
            return
        try:
            config.validate()
        except ValueError as exc:
            self._publish(message=str(exc))
            return
        event, threshold, sender, filters, repeat, sync, width = _PREFIXES
        commands = (
            f"{event} OFF", f"{threshold} {config.threshold}", f"{sender} {config.sender}", f"{filters}:CLEAR",
            *(f"{filters} {slot}, {item}" for slot, item in enumerate(config.filters)),
            f"{repeat} {config.repeat}", f"{sync} {config.sync}", f"{width} {config.width_us}",
            f"{event} {config.event}",
        )
        self._execute(commands, expected=config)

    @Slot()
    def reset(self):
        if self._state.available and not self._state.busy and self._can_configure():
            self._execute(("TRIG:RESET",))

    def _execute(self, commands, expected=None):
        generation = self._generation
        self._publish(busy=True, writing=bool(commands), message="")
        writes = iter(commands)
        reads = iter(("TRIG:STAT?", "TRIG:EV:COUNT?", *(prefix + "?" for prefix in _PREFIXES)))
        replies = []

        def fail(error):
            if generation == self._generation:
                self._publish(busy=False, writing=False, config=None, count=None, status="", message=str(error))

        def received(line):
            replies.append(line)
            read_next()

        def read_next():
            if generation != self._generation:
                return
            query = next(reads, None)
            if query is not None:
                self._protocol.query_text(query, received, errback=fail)
                return
            try:
                status, count, *settings = replies
                if status not in ("IDLE", "ARMED", "TRIGGERED"):
                    raise ValueError("触发状态回读无效")
                actual_count = unsigned(count, 32)
                config = TriggerConfig.parse(settings)
            except ValueError as exc:
                fail(exc)
                return
            message = ""
            if commands:
                message = "设备配置已读回" if expected is None or config == expected else "设备读回值与请求不同"
            self._publish(busy=False, writing=False, config=config, status=status, count=actual_count, message=message)

        def write_next():
            if generation != self._generation:
                return
            command = next(writes, None)
            if command is None:
                read_next()
            else:
                self._protocol.command(command, callback=write_next, errback=fail)

        write_next()
