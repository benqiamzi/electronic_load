import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from electronic_load_gui.services.analysis_service import AnalysisService, event_state
from electronic_load_gui.services.capture_file import CaptureJournal, CaptureReader
from electronic_load_gui.services.export_service import ExportJob, ExportService
from electronic_load_gui.services.log_service import Annotation, LogService

from protocol_m7_fixtures import parse_wire, synthetic_mixed_wire
from test_usb_pd import FIXTURES


class PdServiceTests(unittest.TestCase):
    def test_history_pages_annotations_and_exports_preserve_session_payloads(self):
        _, wire, _ = synthetic_mixed_wire()
        raw_records = tuple(parse_wire(wire))[:3]
        session = "a" * 32
        analysis = AnalysisService()
        events = tuple(analysis.consume(i, record, "real", session, i)
                       for i, record in enumerate(raw_records, 1))
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            path = root / "history.db"
            with LogService(path) as db:
                db.start(session, {"capture_cycle_ns": 10.0})
                db.add(events)
                db.annotate(session, 2, Annotation(True, "核对原始字节"))
            with LogService(path) as db:
                self.assertEqual([row["frame"] for row in db.query(session, after=1, limit=1)], [2])
                self.assertEqual([row["frame"] for row in db.query(session, flagged=True, text="核对")], [2])
                self.assertEqual(db.query(session, start=2**64 - 1), [])
                self.assertEqual(db.annotation(session, 2), Annotation(True, "核对原始字节"))
                db.export_raw(session, root / "capture.drpd")
            with CaptureReader(root / "capture.drpd") as reader:
                restored = tuple(reader)
            self.assertEqual([item.record.raw_payload for item in restored], [item.raw_payload for item in raw_records])
            self.assertEqual([(item.session_id, item.session_index) for item in restored],
                             [(session, 1), (session, 2), (session, 3)])
            details = root / "capture.json"
            ExportService().export(ExportJob(root / "capture.drpd", details, "json", log_path=path))
            data = json.loads(details.read_text(encoding="utf-8"))
            self.assertEqual(data["records"][1]["annotation"], {"flagged": True, "note": "核对原始字节"})
            with LogService(path) as db:
                db.remove(session)
                self.assertEqual(db.query(session), [])
                self.assertEqual(db.annotation(session, 2), Annotation())

    def test_reuse_real_phase_two_indexes_preserves_raw_payload_and_provenance(self):
        for name, count in (("usb_pd_real.json", 3), ("usb_pd_request_real.json", 1),
                            ("usb_pd_vdm_real.json", 2), ("usb_pd_vdm_discovery_real.json", 18),
                            ("usb_pd_extended_real.json", 3), ("usb_pd_m7_cuktech10mini_real.json", 48)):
            with self.subTest(name=name), CaptureReader(FIXTURES / name) as reader:
                records = [item for item in reader if item.record is not None]
                self.assertEqual(len(records), count)
                self.assertTrue(all(item.provenance == "real" and item.record.raw_payload for item in records))

    def test_separate_analysis_contexts_and_lossless_stream_after_boundary(self):
        labels, wire, _ = synthetic_mixed_wire()
        records = tuple(parse_wire(wire))
        service = AnalysisService()
        results = {label: service.consume(i, record, "synthetic")
                   for i, (label, record) in enumerate(zip(labels, records, strict=True), 1)}
        self.assertEqual(results["epr_avs"].power.rdo.operating_current_ma, 4250)
        self.assertTrue(results["epr_avs"].epr_observed)
        self.assertEqual(event_state(results["epr_chunk_zero"]), "partial")
        self.assertTrue(results["epr_chunk_zero"].epr_observed)
        self.assertEqual(results["epr_chunk_zero"].epr_pdo_count, 0)
        self.assertEqual(event_state(results["epr_after_reset"]), "context_missing")
        empty = AnalysisService().consume(1, results["request"].record, "synthetic")
        self.assertEqual(event_state(empty), "context_missing")
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "capture.drpd"
            journal = CaptureJournal(path, {"capture_cycle_ns": 10.0})
            journal.append(records[0], "synthetic")
            journal.boundary()
            journal.append(records[1], "synthetic")
            snapshot = journal.flush()
            journal.append(records[2], "synthetic")
            journal.flush()
            raw = Path(directory) / "saved.drpd"
            self.assertEqual(ExportService().export(ExportJob(path, raw, "raw", snapshot)), 2)
            journal.close()
            with CaptureReader(raw) as reader:
                first, boundary, last = tuple(reader)
            self.assertIsNone(boundary.record)
            self.assertEqual((first.record, last.record), records[:2])
            self.assertEqual((first.provenance, last.provenance), ("synthetic", "synthetic"))

    def test_frozen_pdo_context_and_diagnostics_are_exported_from_ordered_source(self):
        source = FIXTURES / "usb_pd_m7_cuktech10mini_real.json"
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            raw, table, detail, diag = (Path(directory) / file for file in ("capture.drpd", "data.csv", "data.json", "diag.md"))
            service = ExportService()
            for name, target in (("raw", raw), ("csv", table), ("json", detail), ("diagnostics", diag)):
                self.assertEqual(service.export(ExportJob(source, target, name)), 48)
            with CaptureReader(raw) as reader:
                self.assertEqual(len(tuple(reader)), 48)
            with table.open(encoding="utf-8-sig", newline="") as stream:
                decoded = list(csv.reader(stream))
            self.assertEqual(len(decoded), 49)
            self.assertTrue(any("Security_Request" in row and "unavailable" in row for row in decoded))
            exported = json.loads(detail.read_text(encoding="utf-8"))
            self.assertEqual(exported["version"], 1)
            request = next(event for event in exported["records"] if (event["result"].get("message_type") or {}).get("name") == "Request")
            self.assertEqual(request["power"]["rdo"]["operating_current_ma"], 3000)
            self.assertIn("vdm_discovery_response_mismatch", diag.read_text(encoding="utf-8"))

    def test_invalid_version_and_cancelled_export_preserve_destination(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            target = Path(directory) / "output.csv"
            target.write_bytes(b"existing file")
            with self.assertRaises(InterruptedError):
                ExportService().export(ExportJob(FIXTURES / "usb_pd_real.json", target, "csv"), lambda: True)
            self.assertEqual(target.read_bytes(), b"existing file")
            malformed = Path(directory) / "version.drpd"
            malformed.write_text('{"format":"electronic-load-drpd-capture","version":999}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "版本"):
                CaptureReader(malformed)
