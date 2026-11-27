from dataclasses import fields, is_dataclass
from collections.abc import Mapping
from enum import Enum
import re

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import QHeaderView, QPlainTextEdit, QTabWidget, QTreeWidget, QTreeWidgetItem

from .devices.drpd.capture_record import CaptureRecord
from .services.analysis_service import AnalysisEvent, event_state
from .services.log_service import Annotation
from .theme import PLACEHOLDER


STATUS_TEXT = {"valid": "有效", "complete": "完整", "partial": "部分", "pending": "等待分块",
               "invalid": "无效", "context_missing": "缺少上下文", "unsupported": "语义未支持", "unknown": "未知"}
CRC_TEXT = {"valid": "通过", "invalid": "错误", "unavailable": "不可用"}
SOURCE_TEXT = {"real": "实机", "synthetic": "构造", "unlabelled": "未标注"}
_HEX_SEARCH = re.compile(r"(?:0x)?([a-f0-9\s:]+)$", re.IGNORECASE)


def summary(event: AnalysisEvent) -> str:
    message = event.message
    if message is None:
        return getattr(event.record, "event_text", "") or (event.diagnostics[0].code if event.diagnostics else "")
    if event.power is not None and (rdo := event.power.rdo) is not None:
        selected = rdo.selected_pdo
        voltage = rdo.operating_voltage_mv or (selected.voltage_max_mv if selected and selected.voltage_min_mv == selected.voltage_max_mv else None)
        values = [f"PDO {rdo.object_position}"]
        for value, unit in ((voltage, "mV"), (rdo.operating_current_ma, "mA"), (rdo.operating_power_mw, "mW")):
            if value is not None:
                values.append(f"{value} {unit}")
        return " · ".join(values)
    if message.pdos:
        return f"{len(message.pdos)} 个 PDO"
    if message.vdm is not None:
        vdm = message.vdm
        kind = vdm.command_type.name if vdm.command_type is not None else vdm.vdm_type.value
        return f"0x{vdm.svid:04X} · {vdm.command_name or kind} {kind if vdm.command_name else ''}".rstrip()
    if message.extended_message is not None:
        ext = message.extended_message
        if ext.header is not None:
            return (f"请求分块 {ext.header.chunk_number}" if ext.header.request_chunk else
                    f"{len(ext.chunk_payload)} / {ext.header.data_size} B" +
                    (f" · 分块 {ext.header.chunk_number}" if ext.header.chunked else ""))
    return " ".join(f"{value:08X}" for value in message.data_objects)


class CaptureTableModel(QAbstractTableModel):
    HEADERS = ("帧", "时间 µs", "SOP", "发送端", "版本", "消息类型", "ID", "CRC", "状态", "来源", "摘要", "接收端", "备注")
    EventRole = Qt.ItemDataRole.UserRole + 1
    SortRole = Qt.ItemDataRole.UserRole + 2

    def __init__(self, parent=None, *, row_limit=4000, byte_limit=16 * 1024 * 1024) -> None:
        super().__init__(parent)
        self.rows = []
        self._sizes = []
        self._bytes = 0
        self.row_limit = row_limit
        self.byte_limit = byte_limit
        self.hidden = 0
        self.annotations = {}

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        event = self.rows[index.row()]
        if role == self.EventRole:
            return event
        state = event_state(event)
        if role == Qt.ItemDataRole.ForegroundRole and index.column() in (7, 8):
            if index.column() == 7:
                color = "#a32937" if event.crc == "invalid" else None
            else:
                color = "#a32937" if state == "invalid" else "#8e4b14" if event.diagnostics else None
            return QBrush(QColor(color)) if color else None
        annotation = self.annotation(event)
        if role == Qt.ItemDataRole.ToolTipRole and annotation.note:
            return annotation.note
        if role not in (Qt.ItemDataRole.DisplayRole, self.SortRole):
            return None
        header = event.message.header if event.message else None
        columns = (event.index, event.timestamp_us, event.sop or PLACEHOLDER, event.sender or PLACEHOLDER,
                   ("1.0", "2.0", "3.x", "保留")[header.spec_revision] if header else PLACEHOLDER,
                   event.message_name, header.message_id if header else PLACEHOLDER, CRC_TEXT[event.crc],
                   STATUS_TEXT[state], SOURCE_TEXT[event.provenance], summary(event), event.receiver or PLACEHOLDER,
                   ("★ " if annotation.flagged else "") + annotation.note)
        return columns[index.column()]

    def annotation(self, event):
        return self.annotations.get((event.session_id, event.session_index), Annotation())

    def update_annotations(self, session, values):
        for index, annotation in values.items():
            key = (session, index)
            if annotation.flagged or annotation.note:
                self.annotations[key] = annotation
            else:
                self.annotations.pop(key, None)
        if self.rows:
            self.dataChanged.emit(self.index(0, 12), self.index(len(self.rows) - 1, 12))

    @staticmethod
    def _cost(event: AnalysisEvent) -> int:
        records = {id(event.record): event.record}
        if event.discovery is not None and event.discovery.request is not None:
            record = event.discovery.request.record
            records[id(record)] = record
        if event.extended is not None:
            reassembled = event.extended.interrupted
            if event.extended.message is not None:
                reassembled = (*reassembled, event.extended.message)
            for message in reassembled:
                for frame in (*message.frames, *message.requests):
                    records[id(frame.record)] = frame.record
        return sum(len(record.raw_payload) + 32 * len(getattr(record, "pulse_widths", ())) + 1024
                   for record in records.values())

    def append(self, events) -> None:
        incoming = list(events)
        sizes = [self._cost(event) for event in incoming]
        incoming_bytes = sum(sizes)
        trim = 0
        while len(incoming) - trim > self.row_limit or incoming_bytes > self.byte_limit:
            incoming_bytes -= sizes[trim]
            trim += 1
        evict = 0
        while (len(self.rows) - evict + len(incoming) - trim > self.row_limit
               or self._bytes + incoming_bytes > self.byte_limit):
            self._bytes -= self._sizes[evict]
            evict += 1
        if evict:
            self.beginRemoveRows(QModelIndex(), 0, evict - 1)
            for event in self.rows[:evict]:
                self.annotations.pop((event.session_id, event.session_index), None)
            del self.rows[:evict]
            del self._sizes[:evict]
            self.endRemoveRows()
        self.hidden += evict + trim
        incoming = incoming[trim:]
        if incoming:
            self.beginInsertRows(QModelIndex(), len(self.rows), len(self.rows) + len(incoming) - 1)
            self.rows.extend(incoming)
            self._sizes.extend(sizes[trim:])
            self._bytes += incoming_bytes
            self.endInsertRows()

    def clear(self, *, display_only=False) -> None:
        self.beginResetModel()
        self.hidden = self.hidden + len(self.rows) if display_only else 0
        self.rows.clear()
        self.annotations.clear()
        self._sizes.clear()
        self._bytes = 0
        self.endResetModel()


class CaptureFilter(QSortFilterProxyModel):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSortRole(CaptureTableModel.SortRole)
        self.criteria = {}

    def configure(self, **values) -> None:
        if hasattr(self, "endFilterChange"):
            self.beginFilterChange()
            self.criteria = values
            self.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        else:
            self.criteria = values
            self.invalidateRowsFilter()

    def filterAcceptsRow(self, source_row, parent) -> bool:
        event = self.sourceModel().rows[source_row]
        c = self.criteria
        message = event.message
        if c.get("sop") and event.sop != c["sop"]:
            return False
        if c.get("message") and c["message"] not in event.message_name.casefold():
            return False
        if c.get("crc") and event.crc != c["crc"]:
            return False
        if c.get("state") and event_state(event) != c["state"]:
            return False
        for field in ("sender", "receiver", "event_type"):
            if c.get(field) and getattr(event, field) != c[field]:
                return False
        annotation = self.sourceModel().annotation(event)
        if c.get("flagged") and not annotation.flagged:
            return False
        if c.get("start") is not None and event.timestamp_us < c["start"]:
            return False
        if c.get("end") is not None and event.timestamp_us > c["end"]:
            return False
        scope = c.get("scope")
        if scope == "power" and not (message and (message.pdos or message.rdo is not None)):
            return False
        if scope == "vdm" and not (message and message.vdm is not None):
            return False
        if scope == "extended" and not (message and message.extended_message is not None):
            return False
        if (c.get("diagnostics_only") or c.get("level")) and not event.diagnostics and event.crc != "invalid":
            return False
        if c.get("level"):
            level = "error" if event_state(event) == "invalid" or event.crc == "invalid" else "warning"
            if level != c["level"]:
                return False
        needle = c.get("keyword")
        if not needle:
            return True
        items = [event.message_name, event.event_type, summary(event), annotation.note, *(issue.code for issue in event.diagnostics)]
        if message:
            items.extend(f"0x{word:08X}" for word in message.data_objects)
        if message and message.vdm:
            items.extend(f"0x{svid:04X}" for svid in message.vdm.discovered_svids or ())
        if needle in " ".join(items).casefold():
            return True
        found = _HEX_SEARCH.fullmatch(needle)
        if not found:
            return False
        hex_digits = re.sub(r"[\s:]", "", found[1])
        raw = getattr(event.record, "decoded_data", getattr(event.record, "event_text_bytes", b""))
        return bool(hex_digits) and hex_digits in raw.hex()


_FIELD_NAMES = {
    "raw": "原始值", "raw_bytes": "Header 字节", "raw_value": "Header 原始值", "message_type": "消息类型码",
    "data_role": "数据角色位", "spec_revision": "版本位", "power_role": "电源角色位", "cable_plug": "线缆发送端标记",
    "message_id": "消息 ID", "num_data_objects": "数据对象数", "extended": "Extended", "index": "序号",
    "object_position": "所选 PDO 位置", "supply_type": "供电类型", "request_type": "请求类型", "status": "状态",
    "svid": "SVID", "vdm_type": "VDM 类型", "version_major": "主版本位", "version_minor": "次版本位",
    "command_type": "命令类型", "command": "命令编号", "command_name": "命令", "usb_vid": "USB VID",
    "usb_pid": "USB PID", "bcd_device": "bcdDevice", "xid": "XID", "reserved_bits": "保留位", "pdo_echo": "PDO 回显",
    "chunk_number": "分块号", "data_size": "Data Size（B）", "request_chunk": "Request Chunk", "chunked": "Chunked",
    "received_chunks": "已收分块", "missing_chunks": "缺失分块", "direction": "方向", "payload": "有效载荷",
    "voltage_min_mv": "最低电压", "voltage_max_mv": "最高电压", "current_max_ma": "最大电流",
    "power_max_mw": "最大功率", "operating_voltage_mv": "请求电压", "operating_current_ma": "工作电流",
    "operating_power_mw": "工作功率", "maximum_operating_current_ma": "最大工作电流",
    "maximum_operating_power_mw": "最大工作功率", "selected_pdo": "关联 PDO", "capabilities": "能力标志",
    "pps_power_limited": "PPS 功率受限", "mode_position": "模式位置", "structured_version": "VDM 版本",
}
_HEX_FIELDS = {"raw", "raw_value", "raw_header", "reserved_bits", "svid", "usb_vid", "usb_pid", "xid", "bcd_device", "pdo_echo"}


def _text(value, key="") -> str:
    if value is None:
        return PLACEHOLDER
    if isinstance(value, Enum):
        return value.name if isinstance(value.value, int) else STATUS_TEXT.get(value.value, value.value)
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, bytes):
        return value.hex(" ").upper() or PLACEHOLDER
    if isinstance(value, int) and key in _HEX_FIELDS:
        return f"0x{value:0{4 if key in {'svid', 'usb_vid', 'usb_pid', 'bcd_device'} else 8}X}"
    if isinstance(value, (tuple, list, set, frozenset)):
        return ", ".join(_text(item) for item in value) or PLACEHOLDER
    unit = {"mv": "mV", "ma": "mA", "mw": "mW", "us": "µs"}.get(key.rsplit("_", 1)[-1])
    return f"{value} {unit}" if unit and isinstance(value, (int, float)) else str(value)


def field_node(parent, title: str, data=None, *, key="", omit=()):
    item = QTreeWidgetItem(parent)
    item.setText(0, title)
    if is_dataclass(data):
        for field in fields(data):
            value = getattr(data, field.name)
            if field.name not in omit and value is not None and field.name not in ("diagnostics", "frames", "requests"):
                field_node(item, _FIELD_NAMES.get(field.name, field.name.replace("_", " ")), value, key=field.name)
    elif isinstance(data, Mapping):
        for name, value in data.items():
            field_node(item, _FIELD_NAMES.get(name, str(name)), value, key=name)
    else:
        text = _text(data, key)
        item.setText(1, text)
        item.setToolTip(1, text)
    return item


def _hex_dump(data: bytes) -> str:
    return "\n".join(f"{start:04X}  {data[start:start + 16].hex(' ').upper()}" for start in range(0, len(data), 16)) or PLACEHOLDER


class PacketDetails(QTabWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.protocol = self._tree("协议字段")
        self.raw = QPlainTextEdit(readOnly=True)
        self.raw.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.raw.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.addTab(self.raw, "原始数据")
        self.power = self._tree("PDO/RDO")
        self.vdm = self._tree("VDM/VDO")
        self.extended = self._tree("Extended/EPR")
        self.diagnostics = self._tree("诊断")
        self.set_event(None)

    def _tree(self, title: str) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(("字段", "值"))
        tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        tree.header().resizeSection(0, 225)
        tree.setAlternatingRowColors(True)
        self.addTab(tree, title)
        return tree

    def set_event(self, event: AnalysisEvent | None) -> None:
        trees = (self.protocol, self.power, self.vdm, self.extended, self.diagnostics)
        for tree in trees:
            tree.clear()
        if event is None:
            self.raw.clear()
            field_node(self.protocol, "请选择一条捕获记录")
            return
        record, msg = event.record, event.message
        root = field_node(self.protocol, event.message_name, STATUS_TEXT[event_state(event)])
        field_node(root, "原始捕获索引", event.index)
        field_node(root, "时间 µs", event.timestamp_us)
        field_node(root, "来源", SOURCE_TEXT[event.provenance])
        field_node(root, "SOP", event.sop or None)
        field_node(root, "CRC", CRC_TEXT[event.crc])
        if isinstance(record, CaptureRecord):
            capture = field_node(root, "捕获记录")
            field_node(capture, "结束时间 µs", record.end_timestamp_us)
            field_node(capture, "设备解码结果", record.decode_result, key="raw")
            field_node(capture, "解码数据长度 B", record.data_length)
            field_node(capture, "捕获周期 ns", record.cycle_time_ns)
            field_node(capture, "脉宽条目数", record.pulse_count)
            if record.pulse_widths:
                field_node(capture, "最短脉宽 ns", min(record.pulse_widths) * record.cycle_time_ns)
                field_node(capture, "最长脉宽 ns", max(record.pulse_widths) * record.cycle_time_ns)
        if msg:
            field_node(root, "PD Header", msg.header)
            for index, value in enumerate(msg.data_objects, 1):
                field_node(root, f"数据对象 {index}", value, key="raw")
            if msg.crc_received is not None:
                field_node(root, "接收 CRC", msg.crc_received, key="raw")
                field_node(root, "计算 CRC", msg.crc_calculated, key="raw")
            if msg.extended_message is not None:
                field_node(root, "Extended Header", msg.extended_message.header)
        elif not isinstance(record, CaptureRecord):
            field_node(root, "固件事件", record.event_text)
        decoded = record.decoded_data if isinstance(record, CaptureRecord) else record.event_text_bytes
        self.raw.setPlainText(f"帧 {event.index} · {SOURCE_TEXT[event.provenance]}\n\n"
                              f"解码字节 · {len(decoded)} B\n{_hex_dump(decoded)}\n\n"
                              f"原始捕获载荷 · {len(record.raw_payload)} B\n{_hex_dump(record.raw_payload)}")
        self._power_fields(event)
        self._vdm_fields(event)
        self._extended_fields(event)
        for diagnostic in event.diagnostics:
            issue = field_node(self.diagnostics, diagnostic.code, diagnostic.message)
            field_node(issue, "层", diagnostic.layer)
            field_node(issue, "原始帧", event.index)
        if not event.diagnostics:
            field_node(self.diagnostics, "此帧没有诊断")
        for tree in trees:
            tree.expandToDepth(1)

    def _power_fields(self, event: AnalysisEvent) -> None:
        if event.message is not None:
            for pdo in event.message.pdos:
                field_node(self.power, f"PDO {pdo.index} · {pdo.supply_type.value}", pdo)
        rdo = event.power.rdo if event.power else None
        if rdo is not None:
            field_node(self.power, "RDO", rdo)
        if self.power.topLevelItemCount() == 0:
            field_node(self.power, "此帧没有 PDO/RDO")

    def _vdm_fields(self, event: AnalysisEvent) -> None:
        vdm = event.message.vdm if event.message else None
        if vdm is None:
            field_node(self.vdm, "此帧没有 VDM/VDO")
            return
        field_node(self.vdm, "VDM Header", vdm, omit=("vdos", "discovered_svids"))
        if vdm.discovered_svids is not None:
            field_node(self.vdm, "发现的 SVID", ", ".join(f"0x{svid:04X}" for svid in vdm.discovered_svids))
        for vdo in vdm.vdos:
            field_node(self.vdm, f"VDO {vdo.index} · {vdo.category}", vdo)
        discovery = event.discovery
        if discovery and discovery.request:
            field_node(self.vdm, "前序请求时间 µs", discovery.request.record.start_timestamp_us)
            field_node(self.vdm, "请求 SVID", discovery.request.vdm.svid, key="svid")
        if discovery and discovery.mode:
            field_node(self.vdm, "关联 Mode", discovery.mode)

    def _extended_fields(self, event: AnalysisEvent) -> None:
        ext = event.message.extended_message if event.message else None
        if ext:
            field_node(self.extended, "单帧扩展消息", ext, omit=("raw_body",))
        if event.extended:
            if event.extended.message:
                field_node(self.extended, "重组载荷", event.extended.message)
                sources = event.extended.message.frames
                field_node(self.extended, "分块来源时间 µs", tuple(frame.record.start_timestamp_us for frame in sources))
            for ended in event.extended.interrupted:
                field_node(self.extended, "中止的重组", ended)
            if event.extended.epr:
                epr = event.extended.epr
                field_node(self.extended, "EPR 能力状态", epr.status)
                for index, pdo in enumerate(epr.slots, 1):
                    field_node(self.extended, f"{'SPR' if index <= len(epr.spr_slots) else 'EPR'} 槽 {index}", pdo)
        field_node(self.extended, "本次会话已观察到 EPR Source Capabilities", event.epr_observed)
        field_node(self.extended, "当前有效 EPR PDO 数", event.epr_pdo_count)
        if event.power and event.power.rdo and event.message.message_type.name == "EPR_Request":
            field_node(self.extended, "EPR 请求能力上下文", event.power.rdo.status)
