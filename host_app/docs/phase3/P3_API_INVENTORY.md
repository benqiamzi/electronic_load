# 第三阶段接口清单

| 公开入口 | 输入与输出 | 用法 |
| --- | --- | --- |
| `WorkspaceManager.select(index)` | 工作区索引，发出 `changed(index)` | 驱动菜单与页面，以 `QSettings` 持久化。 |
| `DeviceService.available_ports()` / `connect_port(port)` | 串口名称与描述，发出 `changed(DeviceState)` / `error(str)` | 从界面线程枚举串口、排队启动和管理 DRPD 工作线程。 |
| `DeviceService.start_capture` / `stop_capture` | 请求信号，状态来自 `changed` | 在 DRPD 线程调用捕获服务，等待固件读回开关状态。 |
| `DeviceService.batch_ready` / `acknowledge` | 有序 `AnalysisEvent` 批次和令牌 | 界面消费后返还令牌。 |
| `DeviceService.snapshot` / `snapshot_ready` | 请求快照，返回 `CaptureSnapshot` 或空值 | 文件线程按快照字节边界读取实时归档。 |
| `AnalysisService.consume(index, record, provenance)` | `CaptureRecord` 或 `FirmwareEvent`，返回 `AnalysisEvent` | 实时、回放和导出分别构造实例，按捕获顺序传入，遇会话边界调用 `reset()`。 |
| `ReplayService.load(path)` / `control(action, value)` | 路径或播放指令，发出 `changed`、`batch_ready` 或 `error` | 通过工作线程的排队信号调用，批量更新使用确认令牌。 |
| `ExportService.export(job, cancelled)` | `ExportJob`、可选取消回调，返回导出记录数 | 文件线程调用。支持 `raw`、`csv`、`json`、`diagnostics`。 |

## 捕获文件

`.drpd` 是 UTF-8 JSON Lines，首行声明 `format`、`version`、`app_version` 以及可用的固件、来源和捕获周期。记录行保存完整原始捕获载荷 `payload_hex`、`provenance` 和可用的 `cycle_time_ns`。会话边界使用 `{"boundary": true}`。原始十六进制来自设备返回的捕获载荷，含时间戳、脉宽与已解码字节。原始载荷也包括固件事件内容。

`CaptureReader` 还支持第二阶段索引式真实样本 JSON 与原始 SCPI 二进制块十六进制文本。缺少时基元数据的文件按 10 ns 导入。解析 JSON 包含原始记录、分析结果、诊断和来源，CSV 提供帧、时间、SOP、消息类型、CRC、状态、诊断代码和解码字节。

[架构和线程边界](P3_ARCHITECTURE.md)
