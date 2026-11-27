from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

from .analysis_service import AnalysisEvent, event_state
from .capture_file import FORMAT, VERSION, _json_line, atomic_output


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY, started TEXT NOT NULL, metadata TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS records (
    session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    frame INTEGER NOT NULL, timestamp TEXT NOT NULL, sender TEXT NOT NULL, receiver TEXT NOT NULL,
    sop TEXT NOT NULL, message TEXT NOT NULL, crc TEXT NOT NULL, state TEXT NOT NULL,
    event_type TEXT NOT NULL, diagnostics TEXT NOT NULL, payload BLOB NOT NULL, cycle REAL,
    PRIMARY KEY (session, frame)
);
CREATE INDEX IF NOT EXISTS records_time ON records (session, timestamp, frame);
CREATE TABLE IF NOT EXISTS samples (
    session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    timestamp TEXT NOT NULL, received TEXT NOT NULL, voltage REAL NOT NULL, current REAL NOT NULL, sample TEXT NOT NULL,
    PRIMARY KEY (session, timestamp)
);
CREATE TABLE IF NOT EXISTS annotations (
    session TEXT NOT NULL, frame INTEGER NOT NULL, flagged INTEGER NOT NULL, note TEXT NOT NULL,
    PRIMARY KEY (session, frame)
);
"""


@dataclass(frozen=True, slots=True)
class Annotation:
    flagged: bool = False
    note: str = ""


def timestamp_key(value: int) -> str:
    return f"{value:020d}"


class LogService:
    """Persist history on worker-owned SQLite connections."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=2)
        self.db.row_factory = sqlite3.Row
        try:
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError(f"历史日志数据库版本 {version} 不受支持")
            self.db.execute("PRAGMA foreign_keys = ON")
            if version == 0:
                self.db.execute("PRAGMA journal_mode = WAL")
                self.db.executescript(f"BEGIN IMMEDIATE; {_SCHEMA} PRAGMA user_version = 1; COMMIT;")
        except BaseException:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.db.close()

    def start(self, session: str, metadata: dict):
        with self.db:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                            (session, datetime.now(timezone.utc).isoformat(), json.dumps(metadata)))

    def add(self, events: tuple[AnalysisEvent, ...]):
        with self.db:
            self.db.executemany(
                "INSERT INTO records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ((e.session_id, e.session_index, timestamp_key(e.timestamp_us), e.sender, e.receiver,
                  e.sop, e.message_name, e.crc, event_state(e), e.event_type,
                  " ".join(d.code for d in e.diagnostics), e.record.raw_payload, getattr(e.record, "cycle_time_ns", None))
                 for e in events),
            )

    def add_sample(self, session, sample):
        with self.db:
            data = asdict(sample)
            data["received_at"] = sample.received_at.isoformat()
            self.db.execute("INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?, ?)",
                            (session, timestamp_key(sample.timestamp_us), sample.received_at.isoformat(),
                             sample.voltage, sample.current, json.dumps(data)))

    def sessions(self, before: str = "", limit: int = 100):
        sql = "SELECT id, started, metadata FROM sessions"
        if before:
            sql += " WHERE started < ?"
        return [dict(row) for row in self.db.execute(sql + " ORDER BY started DESC LIMIT ?",
                                                     (before, limit) if before else (limit,))]

    def query(self, session: str, *, after=0, limit=200, start=None, end=None, text="", **filters):
        criteria = ["r.session = ?", "r.frame > ?"]
        params = [session, after]
        for operator, value in ((">=", start), ("<=", end)):
            if value is not None:
                criteria.append(f"r.timestamp {operator} ?")
                params.append(timestamp_key(value))
        for field in ("sender", "receiver", "sop", "crc", "state", "event_type"):
            if filters.get(field):
                criteria.append(f"r.{field} = ?")
                params.append(filters[field])
        if text:
            criteria.append("instr(lower(r.message || ' ' || r.diagnostics || ' ' || coalesce(a.note, '')), lower(?)) > 0")
            params.append(text)
        if filters.get("flagged"):
            criteria.append("a.flagged = 1")
        params.append(limit)
        sql = """
            SELECT r.frame, r.timestamp, r.sender, r.receiver, r.sop, r.message, r.crc, r.state,
                   r.event_type, r.diagnostics, a.flagged, a.note
            FROM records r LEFT JOIN annotations a ON r.session = a.session AND r.frame = a.frame
        """
        return [dict(row) for row in self.db.execute(
            sql + " WHERE " + " AND ".join(criteria) + " ORDER BY r.frame LIMIT ?", params
        )]

    def samples(self, session: str, start: int, end: int, limit: int = 4000):
        rows = self.db.execute(
            "SELECT timestamp, voltage, current FROM samples WHERE session = ? AND timestamp BETWEEN ? AND ? "
            "ORDER BY timestamp DESC LIMIT ?", (session, timestamp_key(start), timestamp_key(end), limit)
        ).fetchall()
        return [(int(row["timestamp"]), row["voltage"], row["current"]) for row in reversed(rows)]

    def annotation(self, session: str, frame: int) -> Annotation:
        row = self.db.execute("SELECT flagged, note FROM annotations WHERE session = ? AND frame = ?",
                              (session, frame)).fetchone()
        return Annotation(bool(row["flagged"]), row["note"]) if row else Annotation()

    def annotate(self, session: str, frame: int, value: Annotation):
        with self.db:
            if value.flagged or value.note:
                self.db.execute("INSERT OR REPLACE INTO annotations VALUES (?, ?, ?, ?)",
                                (session, frame, value.flagged, value.note))
            else:
                self.db.execute("DELETE FROM annotations WHERE session = ? AND frame = ?", (session, frame))

    def annotations(self, session: str, start: int, end: int) -> dict:
        rows = self.db.execute(
            "SELECT frame, flagged, note FROM annotations WHERE session = ? AND frame BETWEEN ? AND ?",
            (session, start, end),
        )
        return {row["frame"]: Annotation(bool(row["flagged"]), row["note"]) for row in rows}

    def remove(self, session: str):
        with self.db:
            self.db.execute("DELETE FROM sessions WHERE id = ?", (session,))
            self.db.execute("DELETE FROM annotations WHERE session = ?", (session,))

    def size_bytes(self):
        return sum(path.stat().st_size for path in (self.path, Path(f"{self.path}-wal")) if path.exists())

    def export_raw(self, session: str, path: Path, cancelled=lambda: False):
        with self.db:
            self.db.execute("BEGIN")
            row = self.db.execute("SELECT metadata FROM sessions WHERE id = ?", (session,)).fetchone()
            if row is None:
                raise ValueError("历史会话不可用")
            with atomic_output(path) as file:
                file.write(_json_line({**json.loads(row["metadata"]), "session_id": session,
                                       "format": FORMAT, "version": VERSION}))
                for record in self.db.execute(
                    "SELECT payload, cycle FROM records WHERE session = ? ORDER BY frame", (session,)
                ):
                    if cancelled():
                        raise InterruptedError("历史回放已取消")
                    file.write(_json_line({"payload_hex": record["payload"].hex(), "provenance": "real",
                                           "cycle_time_ns": record["cycle"]}))
