from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import math
import os
from pathlib import Path
import tempfile

from .. import __version__
from ..devices.drpd.binary_block import BinaryBlockParser, DEFAULT_MAX_PAYLOAD_BYTES
from ..devices.drpd.capture_record import CaptureRecord, CaptureRecordParser, FirmwareEvent


FORMAT = "electronic-load-drpd-capture"
VERSION = 1
_LINE_LIMIT = 2 * DEFAULT_MAX_PAYLOAD_BYTES + 512
_FIXTURE_LIMIT = 32 * 1024 * 1024
PROVENANCE = ("real", "synthetic", "unlabelled")


@dataclass(frozen=True, slots=True)
class CaptureEntry:
    record: CaptureRecord | FirmwareEvent | None
    provenance: str = "unlabelled"
    session_id: str = ""
    session_index: int = 0
    boundary_metadata: dict | None = None


@dataclass(frozen=True, slots=True)
class CaptureSnapshot:
    path: Path
    size: int
    count: int


def _json_line(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


class CaptureJournal:
    """A raw, append-only stream. A flushed offset forms a stable export snapshot."""

    def __init__(self, path: Path, metadata: dict) -> None:
        self.path = path
        self.count = 0
        self.committed_count = 0
        self.size = 0
        self._file = path.open("wb")
        try:
            self._file.write(_json_line({**metadata, "format": FORMAT, "version": VERSION, "app_version": __version__,
                                         "created_utc": datetime.now(timezone.utc).isoformat()}))
            self.flush()
        except BaseException:
            self._file.close()
            raise

    def boundary(self, **metadata) -> None:
        self._file.write(_json_line({**metadata, "boundary": True}))

    def append(self, record: CaptureRecord | FirmwareEvent, provenance: str) -> None:
        self._file.write(_json_line({"payload_hex": record.raw_payload.hex(), "provenance": provenance,
                                     "cycle_time_ns": record.cycle_time_ns if isinstance(record, CaptureRecord) else None}))
        self.count += 1

    def flush(self) -> CaptureSnapshot:
        self._file.flush()
        self.size = self._file.tell()
        self.committed_count = self.count
        return CaptureSnapshot(self.path, self.size, self.committed_count)

    def close(self) -> None:
        self._file.close()


def _cycle(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0 or not math.isfinite(value):
        raise ValueError("捕获周期必须是有限的正数")
    return float(value)


def _origin(value) -> str:
    if value not in PROVENANCE:
        raise ValueError("无法识别捕获来源")
    return value


def _record(payload: bytes, cycle: float, origin: str) -> CaptureEntry:
    if len(payload) > DEFAULT_MAX_PAYLOAD_BYTES:
        raise ValueError("单帧长度超过 DRPD 捕获上限")
    return CaptureEntry(CaptureRecordParser.parse(payload, cycle), _origin(origin))


def _wire(hex_line: str, cycle: float, origin: str) -> CaptureEntry:
    if len(hex_line) > _LINE_LIMIT:
        raise ValueError("原始块长度超过 DRPD 捕获上限")
    parser = BinaryBlockParser()
    blocks = parser.feed(bytes.fromhex(hex_line))
    if len(blocks) != 1 or parser.has_pending_data:
        raise ValueError("每条索引必须对应一个完整 SCPI 块")
    return _record(blocks[0], cycle, origin)


class CaptureReader:
    """Read the native stream incrementally, or import a phase-two real fixture index."""

    def __init__(self, path: Path, *, limit: int | None = None) -> None:
        self.path = path
        self._file = path.open("rb")
        self.size = min(path.stat().st_size, limit) if limit is not None else path.stat().st_size
        self.metadata = {}
        self._position = 0
        try:
            first = self._file.readline(_LINE_LIMIT + 1)
            try:
                header = json.loads(first)
            except (ValueError, UnicodeError):
                header = None
            if isinstance(header, dict) and "format" in header:
                if header["format"] != FORMAT or type(header.get("version")) is not int or header["version"] != VERSION:
                    raise ValueError("捕获文件格式或版本不受支持")
                self.metadata = header
                self._entries = self._native_entries()
            else:
                self._file.seek(0)
                self._entries = self._import_entries(first.lstrip().startswith(b"{"))
        except BaseException:
            self.close()
            raise

    @property
    def progress(self) -> float:
        return min(1.0, self._position / self.size) if self.size else 1.0

    def _line(self) -> bytes:
        remaining = self.size - self._file.tell()
        line = self._file.readline(min(_LINE_LIMIT + 1, max(0, remaining)))
        self._position = self._file.tell()
        if len(line) > _LINE_LIMIT:
            raise ValueError("单条捕获文件记录过长")
        return line

    def _native_entries(self) -> Iterator[CaptureEntry]:
        default_cycle = _cycle(self.metadata.get("capture_cycle_ns", 10.0))
        session_id = self.metadata.get("session_id", "")
        session_index = 0
        while line := self._line():
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("捕获文件记录必须为对象")
            if item.get("boundary") is True:
                session_id = item.get("session_id", "")
                session_index = 0
                yield CaptureEntry(None, session_id=session_id if isinstance(session_id, str) else "",
                                   boundary_metadata=item)
                continue
            payload = item.get("payload_hex")
            if not isinstance(payload, str):
                raise ValueError("捕获文件缺少原始载荷")
            cycle = item.get("cycle_time_ns")
            entry = _record(bytes.fromhex(payload), default_cycle if cycle is None else _cycle(cycle),
                            item.get("provenance", "unlabelled"))
            session_index += 1
            yield CaptureEntry(entry.record, entry.provenance, session_id if isinstance(session_id, str) else "",
                               session_index)

    def _import_entries(self, indexed: bool) -> Iterator[CaptureEntry]:
        if not indexed:
            self.metadata = {"capture_cycle_ns": 10.0, "provenance": "unlabelled", "format": "SCPI hex"}
            while line := self._line():
                if line.strip():
                    yield _wire(line.decode("ascii").strip(), 10.0, "unlabelled")
            return
        if self.size > _FIXTURE_LIMIT:
            raise ValueError("JSON 索引过大，请使用逐行的原生捕获文件")
        fixture = json.load(self._file)
        if not isinstance(fixture, dict) or not any(key in fixture for key in ("records", "sessions", "wire_hex")):
            raise ValueError("不是受支持的原始捕获索引")
        self.metadata = {k: v for k, v in fixture.items() if k not in ("records", "sessions", "wire_hex", "inquiries")}
        origin = _origin(fixture.get("provenance", "unlabelled"))
        groups = fixture.get("sessions") or [fixture]
        self._position = 0
        for i, group in enumerate(groups):
            if i:
                yield CaptureEntry(None)
            cycle = _cycle(group.get("capture_cycle_ns", fixture.get("capture_cycle_ns", 10.0)))
            if "inquiries" in group and isinstance(group["inquiries"], list):
                samples = [row for inquiry in group["inquiries"] for row in inquiry["records"]]
            else:
                samples = group.get("records", [group])
            cache = {}
            for n, sample in enumerate(samples, 1):
                raw = sample.get("wire_hex")
                if raw is None:
                    name = sample.get("wire_file", group.get("wire_file"))
                    if not isinstance(name, str) or Path(name).name != name or name in (".", ".."):
                        raise ValueError("样本索引必须引用同目录的原始块文件")
                    if name not in cache:
                        path = self.path.parent / name
                        if path.stat().st_size > _FIXTURE_LIMIT:
                            raise ValueError("索引引用的原始块文件过大")
                        cache[name] = path.read_text(encoding="ascii").splitlines()
                    line = sample.get("wire_line")
                    if type(line) is not int or not 1 <= line <= len(cache[name]):
                        raise ValueError("样本索引的行号无效")
                    raw = cache[name][line - 1]
                self._position = round(self.size * (i + n / len(samples)) / len(groups))
                yield _wire(raw, cycle, sample.get("provenance", group.get("provenance", origin)))

    def __iter__(self) -> Iterator[CaptureEntry]:
        return self._entries

    def close(self) -> None:
        self._file.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


@contextmanager
def atomic_output(destination: Path):
    """Replace a user-selected destination only after a complete successful export."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", prefix=".drpd-", dir=destination.parent, delete=False) as output:
            temporary = Path(output.name)
            yield output
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def json_value(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [json_value(item) for item in (sorted(value) if isinstance(value, (set, frozenset)) else value)]
    return value
