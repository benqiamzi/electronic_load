import csv
from contextlib import nullcontext
from dataclasses import dataclass
import io
import json
from pathlib import Path

from .. import __version__
from .analysis_service import AnalysisService, event_state
from .capture_file import FORMAT, VERSION, CaptureReader, CaptureSnapshot, atomic_output, json_value
from .log_service import Annotation, LogService


@dataclass(frozen=True, slots=True)
class ExportJob:
    source: Path
    destination: Path
    kind: str
    snapshot: CaptureSnapshot | None = None
    log_path: Path | None = None


class ExportService:
    def export(self, job: ExportJob, cancelled=lambda: False) -> int:
        if job.source.resolve() == job.destination.resolve():
            raise ValueError("请选择与当前捕获文件不同的导出位置")
        if job.kind == "raw" and job.snapshot is not None:
            with job.source.open("rb") as source, atomic_output(job.destination) as output:
                remaining = job.snapshot.size
                while remaining:
                    self._check(cancelled)
                    data = source.read(min(remaining, 65536))
                    if not data:
                        raise ValueError("捕获快照短于预期")
                    output.write(data)
                    remaining -= len(data)
            return job.snapshot.count

        limit = job.snapshot.size if job.snapshot is not None else None
        log = LogService(job.log_path) if job.kind in ("csv", "json") and job.log_path and job.log_path.is_file() else nullcontext()
        with log as history, CaptureReader(job.source, limit=limit) as reader, atomic_output(job.destination) as output:
            if history is not None:
                history.db.execute("BEGIN")
            entries = iter(reader)
            first = next(entries, None)
            index = 0
            analysis = AnalysisService()
            metadata = reader.metadata
            if job.kind == "raw":
                self._line(output, {**metadata, "format": FORMAT, "version": VERSION, "app_version": __version__})
            elif job.kind == "json":
                output.write(b'{"version":1,"app_version":')
                output.write(json.dumps(__version__).encode("utf-8"))
                output.write(b',"metadata":')
                output.write(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
                output.write(b',"records":[\n')
            elif job.kind == "csv":
                output.write(b"\xef\xbb\xbf")
                self._csv_row(output, ("帧", "时间 µs", "来源", "SOP", "消息类型", "CRC", "状态", "诊断", "原始字节",
                                       "会话", "会话帧", "发送端", "接收端", "事件", "标记", "备注"))
            elif job.kind == "diagnostics":
                output.write("# USB PD 捕获诊断\n\n帧号引用原始捕获顺序。\n\n".encode("utf-8"))
            else:
                raise ValueError("未知导出格式")

            diagnostic_count = 0
            entry = first
            while entry is not None:
                self._check(cancelled)
                record = entry.record
                if record is None:
                    analysis.reset()
                    if job.kind == "raw":
                        self._line(output, entry.boundary_metadata or {"boundary": True})
                else:
                    index += 1
                    if job.kind == "raw":
                        self._line(output, {"payload_hex": record.raw_payload.hex(), "provenance": entry.provenance,
                                            "cycle_time_ns": getattr(record, "cycle_time_ns", None)})
                    else:
                        event = analysis.consume(index, record, entry.provenance, entry.session_id, entry.session_index)
                        annotation = (history.annotation(entry.session_id, entry.session_index)
                                      if history is not None and entry.session_id else Annotation())
                        if job.kind == "json":
                            if index > 1:
                                output.write(b",\n")
                            output.write(json.dumps({**json_value(event), "annotation": json_value(annotation)},
                                                    ensure_ascii=False).encode("utf-8"))
                        elif job.kind == "csv":
                            raw = getattr(record, "decoded_data", getattr(record, "event_text_bytes", b""))
                            self._csv_row(output, (index, event.timestamp_us, event.provenance, event.sop,
                                                   event.message_name, event.crc, event_state(event),
                                                   ", ".join(issue.code for issue in event.diagnostics), raw.hex(" "),
                                                   entry.session_id, entry.session_index or "", event.sender, event.receiver,
                                                   event.event_type, int(annotation.flagged), annotation.note))
                        elif event.diagnostics:
                            diagnostic_count += len(event.diagnostics)
                            output.write(f"## 帧 {index} · {event.timestamp_us} µs · {event.message_name}\n\n".encode("utf-8"))
                            for issue in event.diagnostics:
                                message = issue.message.replace("\n", " ")
                                output.write(f"- `{issue.code}` {message}\n".encode("utf-8"))
                            output.write(f"\n原始捕获载荷 `{record.raw_payload.hex(' ')}`\n\n".encode("utf-8"))
                entry = next(entries, None)
            if job.kind == "json":
                output.write(b"\n]}\n")
            elif job.kind == "diagnostics":
                output.write(f"共 {index} 帧，{diagnostic_count} 条诊断。\n".encode("utf-8"))
            return index

    @staticmethod
    def _line(output, value) -> None:
        output.write((json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"))

    @staticmethod
    def _csv_row(output, row) -> None:
        line = io.StringIO(newline="")
        csv.writer(line).writerow(row)
        output.write(line.getvalue().encode("utf-8"))

    @staticmethod
    def _check(cancelled) -> None:
        if cancelled():
            raise InterruptedError("导出已取消")
