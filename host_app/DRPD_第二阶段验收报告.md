# 电子负载与 USB-PD 综合测试平台第二阶段验收报告

| 项目 | 内容 |
| --- | --- |
| 核验日期 | 2026-11-26（北京时间） |
| 阶段范围 | USB-PD 离线协议解析引擎 |
| 当前结论 | **基础解析通过，第二阶段整体验收尚未完成**。本报告记录 M0–M3 已交付部分和当前可复用接口 |
| 上位机版本 | 本地 `feature/usb-pd-decoder`，提交 `246fb17` |
| 第一阶段基线 | `feature/drpd-transport`，提交 `6771561` |
| 规范基线 | USB PD Revision 3.2 Version 1.1（2024-10） |
| 实机样本来源 | 2026-11-25 第一阶段录制，DRPD 固件 `1.0.0-beta.1` |

## 1. 里程碑验收表

| 里程碑 | 状态 | 交付和验证结果 |
| --- | --- | --- |
| M0 样本与规则 | 通过 | 样本索引记录原始 SCPI 块、采集日期、固件版本和预期字段。SOP、Header、CRC 规则已对照 USB-IF 规范、DRPD Python 和固件定义。实机样本与人工构造边界样本分别标注 |
| M1 SOP 与 Header | 通过 | 支持 SOP、SOP′、SOP″ 识别，独立处理 Hard Reset、Cable Reset 和固件事件。能诊断未知或有歧义的有序集、短 Header、保留位及普通报文长度不符 |
| M2 主机 CRC32 | 通过 | 用实机 `Source_Capabilities`、独立按位参考算法和单字节损坏样本核对 CRC。结果分别保存固件解码状态以及主机接收值、计算值、比较状态。截断或固件解码失败时 CRC 为不可判定 |
| M3 消息分类与正文拆分 | 基础范围通过 | 已按 SOP、类别和线上版本分类首批控制及普通数据消息。实机 `Source_Capabilities` 正确识别，原始数据对象按小端拆分。`Request`、`Vendor_Defined` 及控制消息分支有人工构造测试。请求与前序 PDO 的上下文关联归入 M4 |
| M4 PDO/RDO | 待完成 | 当前只提供原始 32 位数据对象与 `Request` 对象数量检查。能力类型、物理量换算、RDO 与前序 PDO 的关联仍待验收 |
| M5 VDM/VDO | 待完成 | 已识别 `Vendor_Defined` 的消息类别。SVID、Structured/Unstructured 区分、命令字段和厂商载荷解释留待实现 |
| M6 Extended Message | 待完成 | 已识别 Header 的扩展标志并保留原报文。Extended Header、分块状态、长度校验与重组仍待实现 |
| M7 统一入口、回归和性能 | 部分完成 | `parse_capture()` 可离线处理四类结果，第一阶段测试及当前新增测试均通过。第二阶段完整功能回归、重新采集的 DRPD CDC / 双实机回归和耗时、内存基线待验收 |

## 2. 实机样本回放和测试结果

通过第一阶段的 `BinaryBlockParser` 和 `CaptureRecordParser` 加载三条已提交的实机记录，再调用第二阶段解析入口。已在禁用第三方站点包加载的 Python 进程中回放成功，过程未导入 PySide6。下表的字节数是捕获记录载荷长度，SCPI 外层块头和尾部 LF 另计。

| 样本 | 载荷 | 核验结果 |
| --- | ---: | --- |
| 固件事件 | 152 字节 | 输出 `FirmwareEventResult`，保留事件类型 `9`、设备侧时间戳 `59755786 µs` 和原始事件内容 |
| Hard Reset | 288 字节 | 输出 `ResetResult`，SOP 字节 `07 07 07 19`，原记录含 128 项脉宽计数 |
| `Source_Capabilities` | 1428 字节 | 输出 `PDMessageResult`，SOP 字节 `18 18 18 11`，解析出 7 个原始数据对象。固件解码结果为 `0`，接收 CRC 与主机计算值均为 `0x34737FBF` |

### `Source_Capabilities` 的第三阶段验收基准

| 字段 | 期望值 |
| --- | --- |
| 原始 Header | 字节 `A1 77`，小端值 `0x77A1` |
| 消息类别和编号 | `data`，`Source_Capabilities`，类型码 `1`，消息 ID `3` |
| 线上规范版本及角色 | 版本字段 `2`（PD 3.x），功率角色 Source，数据角色 DFP |
| 时间范围 | DRPD 设备侧 `32788569–32789980 µs`，可供报文详情回放 |
| 正文与 CRC | 28 字节正文、4 字节 CRC。`decoded_data` 共 34 字节，包括 2 字节 Header |
| 原始对象，按报文顺序 | `0x0A01912C`、`0x0002D12C`、`0x0003C12C`、`0x0004B12C`、`0x000641F4`、`0xC8DC3264`、`0xC9903264` |

上位机全量 **61 项测试通过**，包括第一阶段已有的 45 项和第二阶段新增的 16 项。新增测试覆盖三个实机样本、CRC 正常与损坏、固件失败、未知 SOP、保留位、异常长度、控制消息和普通数据对象。支持类别中的人工构造样本用于离线边界测试，当前实机证据为上述三条历史捕获的回放。

## 3. 第三阶段可接入的解析接口

数据链为 `DrpdDevice.capture.capture_received` → `parse_capture(record)` → Qt 列表和详情模型。离线回放可直接把历史 `CaptureRecord` 或 `FirmwareEvent` 传给同一个入口。解析结果保留对原捕获记录的引用，显示数据可以追溯到原始载荷。

| 结果类型 | 第三阶段可直接使用的字段 |
| --- | --- |
| `PDMessageResult` | `record`、`sop`、`header`、`message_type`、`body`、`data_objects`。状态来源包括 `header_status`、`body_status`、`message_type.status`、`parse_status`、`firmware_decode_result` 和 `crc_valid`。详情可展示 `crc_received`、`crc_calculated`、`diagnostics` 和 `raw_decoded_data` |
| `ResetResult` | `record` 和 `sop`，列表可显示 Hard Reset 或 Cable Reset，详情可显示有序集及原始载荷 |
| `FirmwareEventResult` | `record.timestamp_us`、`event_type`、`event_text`、`event_text_bytes` 和 `text_encoding_valid`，用于事件行与详情 |
| `ParseFailureResult` | `record`、`sop`、`parse_status`、`diagnostics`，用于未知 SOP、短 Header 和无法进入普通解析的记录 |

`crc_valid` 有 `True`、`False` 和 `None` 三种值，分别表示校验通过、校验不符和不可判定。扩展报文可出现 `unsupported`，未知类型的 `message_type.name` 可以为 `None`，此时可显示原始类型码。`record.raw_payload` 是第一阶段的完整捕获载荷，`raw_decoded_data` 是固件解码字节，两者适合在详情中分别标注。DRPD 时间戳使用设备侧 µs，电压曲线与报文对齐需要后续独立建立时钟基准。

## 4. 第三阶段规划输入

建议首轮交付聚焦 **PD 报文列表与消息详情**。列表消费四种现有结果，详情展示已解析字段、诊断信息和十六进制原始内容。界面可先基于离线实机样本交付，再接入实时 `capture_received`。组件层沿用第一阶段的捕获接口和第二阶段的纯 Python 解析入口。

| 建议工作项 | 可写入第三阶段规划书的验收口径 |
| --- | --- |
| 离线列表和类型分组 | 导入上述 3 个实机样本，分别出现固件事件、Hard Reset 和 `Source_Capabilities` 条目。点击条目能打开对应详情 |
| 普通 PD 详情 | `Source_Capabilities` 展示 `0x77A1`、消息 ID `3`、7 个原始对象及 `0x34737FBF` 的 CRC 结果。按设备侧时间戳排序，保留原始字节视图 |
| 失败与未知记录 | 注入测试中的 CRC 损坏、截断及未知 SOP 样本，确认列表保留条目，详情显示诊断和原始数据。区分 CRC 错误及不可判定 |
| 实时追加与断开 | 新捕获能追加到列表，断开后历史条目仍可查看，重新连接后新记录可继续显示。Qt 交互与电子负载电压刷新在同一进程接受单独回归 |
| 语义详情扩展 | 等 M4、M5 接口核验后展示 PDO/RDO 的物理单位及 VDM 字段。等 M6 验收后展示扩展消息的分块和重组状态。在此之前显示原始对象和已有状态 |
| 范围与基线 | 列表更新策略、缓存上限和性能指标需要第三阶段另行定量。波形联动、跨设备时间同步、持久化和电子负载恒流验收各自规划 |

**进入第三阶段的条件。** 列表和基础详情可用当前接口开始。若第三阶段交付要求完整的 PDO/RDO/VDO 详情或扩展报文重组展示，应把相应解析模块的验收列为依赖。

## 5. 复现与资料索引

Windows 上在 `host_app` 目录执行。第二条命令单独运行 16 项第二阶段测试。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests -v
python -m unittest discover -s tests -p test_usb_pd.py -v
```

| 资料 | 位置 |
| --- | --- |
| 第一阶段实机记录、接口和验收口径 | [第一阶段验收报告](DRPD_第一阶段验收报告.md) |
| 规范基线和上位机入口 | [上位机 README](README.md)、[USB-IF 规范版本说明](https://usb.org/euconformity) |
| 解析入口与返回类型 | [解析器](electronic_load_gui/protocols/usb_pd/parser.py)、[结果模型](electronic_load_gui/protocols/usb_pd/models.py) |
| 实机数据、预期结果和测试 | [样本索引](tests/fixtures/usb_pd_real.json)、[原始 CDC 块](tests/fixtures/drpd_cdc_blocks.hex)、[阶段测试](tests/test_usb_pd.py) |
