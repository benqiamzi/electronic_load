# 电子负载与 USB-PD 综合测试平台第一阶段验收报告

| 项目 | 内容 |
| --- | --- |
| 验收日期 | 2026-11-25（北京时间） |
| 阶段范围 | DRPD USB CDC 通信、SCPI 事务、捕获记录解析及双实机联调 |
| 验收结论 | 通过。电子负载按当前板卡的电压采样能力验收，恒流控制留待后续单独验收 |
| 上位机版本 | `feature/drpd-transport`，验收提交 `1c201a9` |
| DRPD 固件版本 | `1.0.0-beta.1`，CDC 路由提交 `70b78e5`，复刻板 CC 选路提交 `0d1aee3` |

## 1. 验收环境与实现范围

Windows 上位机通过两条独立的 USB CDC 链路连接设备。DRPD 复刻板为 RP2350，枚举为 `COM15`（`2E8A:000A`）。电子负载为 STM32F411 `EL-F411`，固件 `0.3.6`，枚举为 `COM18`（`0483:5740`）。端口号以实际枚举为准。

DRPD 固件沿用原版 SCPI 命令和捕获记录序列化。旧应用的 CDC 端口可打开，但发送 `*IDN?` 后超时。适配后的 TinyUSB 任务将 LF 结束的命令送入原 SCPI 解释器，响应通过 CDC 返回原始文本或二进制块。实机确认二进制块为 `#<N><length><payload><LF>`，载荷中的 `00`、`0A` 和 `0D` 均保留。

复刻板的 GPIO16 选路极性与参考板不同。验收镜像使用 `DRPD_DUT_CC1_SELECT_LEVEL=0`、`PIN_CC_OUT_HIGH=19`、`PIN_CC_OUT_LOW=20`、`PIN_HW_REVISION_DETECT=0` 和 `PIN_SYNC=2`。匹配选路极性后，复刻板进入 `PE_SNK_READY` 并收到普通 PD 数据报文。刷写前已备份并校验 2 MiB 闪存，验收镜像仅写入应用区并完成读回校验。

## 2. 验收结果

| 验收项 | 结果与证据 |
| --- | --- |
| CDC 文本与捕获控制 | 实机通过 `*IDN?` 识别设备。捕获开关写入和读回成功，`BUS:CC:CAP:CYCLETIME?` 返回 **10 ns**，`BUS:CC:CAP:COUNT?` 返回可用记录数 |
| 连续读取与特殊字节 | 两轮连续捕获共读回 **323 条**，包括 50 条 Hard Reset 和 273 条固件事件。逐条核对外层块长度及记录内部长度，确认载荷中的 `00`、`0A`、`0D` 未截断记录。匹配 CC 极性后的普通报文验证及最终排空另读回 10 条普通 PD 报文和 1 条固件事件 |
| 空队列与超时 | 实机空队列返回 `-200\n`，原始字节为 `2d 32 30 30 0a`。将计数查询限时设为 1 ms 后，实机触发超时且排队查询被取消；重开串口后重新读到 10 ns 周期 |
| 断连与重连 | 切换 BOOTSEL 使真实 CDC 端口从系统移除，Qt 触发断连清理。应用重启后，同一设备重新枚举并返回相同的身份和周期 |
| 解析与边界处理 | 自动化测试覆盖 `#41020` 分片、粘连、长度和终止符错误，以及小端时间戳、SOP、脉宽、固件事件、解码失败和未知结果。完整 `raw_payload` 可供后续诊断 |
| 双实机并行 | 两设备在同一 Qt 进程工作。以用户提供的 **6.2 V** 为参考，本次联调采用 **±0.10 V** 判据。3 次电压采样为 **6.1825–6.1850 V**，最大绝对偏差 **17.5 mV**。同期成功读回 **11 条 PD 捕获记录**，至少一条含解码数据 |
| 回归与打包 | 上位机 **45 项**测试和 DRPD 固件 **12 项**主机端测试通过。上位机 Python wheel 已构建并核对包含 DRPD 模块 |

双实机执行的是当前板卡支持的电压采样验收。`±0.10 V` 是本次联调判据；单点读数只反映本次设置下的测量差异。

### 普通 PD 报文的实机基线

实机发出 `GET_SOURCE_CAP` 后，捕获的 `Source_Capabilities` 原始 SCPI 块以 `#41428` 开头，记录载荷为 **1428 字节**。SOP 为 `18 18 18 11`，固件解码结果为 `0`，包含 **681 项脉宽计数**和 **34 字节解码数据**。起止时间戳为 `32788569` 和 `32789980` µs。

这 34 字节包含 2 字节 PD Header、28 字节消息正文及 4 字节 CRC。消息正文与同次 `SINK:INQ:RESP?` 返回的 28 字节逐字节一致。

```text
a1 77 2c 91 01 0a 2c d1 02 00 2c c1 03 00 2c b1 04 00
f4 41 06 00 64 32 dc c8 64 32 90 c9 bf 7f 73 34
```

仓库中的 [实机 CDC 样本](tests/fixtures/drpd_cdc_blocks.hex) 保留三条完整块，按行分别为 152 字节固件事件、288 字节 Hard Reset 和 1428 字节 `Source_Capabilities`，均含原始 SCPI 块头和尾部 LF。计划书的 **1020 字节**示例使用附属资料中的真实 PD 报文字节和字段规格重建，测试中的时间戳和脉宽为构造数据。

## 3. 第二阶段的输入契约

从 `electronic_load_gui.devices.drpd.device.DrpdDevice` 获取 `device.capture`。使用 `capture_received` 接收 `CaptureRecord | FirmwareEvent`，或通过 `fetch_next_capture()` 的回调消费单条记录。队列为空时，单条读取回调收到 `None`。启停捕获和轮询由 `CaptureClient` 管理。同一链路最多一项在途查询；超时、响应错位和帧格式错误会结束当前及排队请求，重开串口后恢复。

| 输入 | 字段和使用方式 |
| --- | --- |
| `CaptureRecord` 的时间轴 | `start_timestamp_us`、`end_timestamp_us` 是 DRPD 设备侧时间戳，单位 µs。可用于设备内排序和时差计算。与电子负载测量的时间关联需单独建立时间基准 |
| `CaptureRecord` 的报文数据 | `sop_bytes` 保留 4 字节有序集。`decode_result` 保留固件原始值，包括未知值。`decoded_data` 保留完整解码字节；普通完整报文仍含 PD Header 和 CRC，失败记录可能只有部分字节 |
| `CaptureRecord` 的波形数据 | `pulse_widths` 为原始脉宽计数，`cycle_time_ns` 来自设备查询，`pulse_widths_ns` 提供转换值。周期缓存随串口关闭清理 |
| `CaptureRecord` 的诊断数据 | `raw_payload` 是去掉 SCPI 外层块头和尾部 LF 后的完整记录载荷。`is_hard_reset` 标记固件成功解码、SOP 为 `07 07 07 19` 且无数据字节的记录 |
| `FirmwareEvent` | 独立记录类型，提供 `timestamp_us`、`event_type`、`event_text`、`event_text_bytes`、`text_encoding_valid` 和 `raw_payload`。可作为与报文同时间轴的设备事件使用 |

载荷以小端序编码，前 28 字节依次为两项 `uint64` 时间戳、`uint32` 解码结果、4 字节 SOP 和 `uint32` 脉宽条目数 `N`。随后是 `N` 项 `uint16` 脉宽计数、`uint32` 数据长度 `M`、`M` 字节数据。总长度为 `32 + 2 × N + M`。当前主机侧默认单条载荷上限为 **11494 字节**，可通过 `DrpdDevice(max_payload_bytes=...)` 调整。新固件扩大缓冲区时，应同步核对主机上限和边界测试。

## 4. 第二阶段规划输入

| 建议工作项 | 可沿用的第一阶段成果 | 可写入规划书的验收口径 |
| --- | --- | --- |
| SOP、PD Header 与报文分类 | `sop_bytes`、`decoded_data`、`is_hard_reset` 和实机样本 | 普通报文按头部正确分类。Hard Reset 和固件事件进入各自分支。短包、未知类型和失败记录保留原始字节并给出状态 |
| CRC32 校验 | 完整解码字节和固件 `decode_result` | 用实机完整报文及单字节损坏样本验证主机计算结果。主机 CRC 结果和固件解码结果作为两个独立字段保留 |
| 控制与数据报文、PDO/RDO/VDO | 1428 字节实机 `Source_Capabilities` 样本及固件独立返回的 28 字节消息正文 | 首先用实机样本核对 Header 与 PDO 拆分，再补充控制报文、Request 和 VDM 样本覆盖 RDO/VDO。用长度异常样本验证边界处理 |
| Extended Message | 捕获记录的完整 `decoded_data` 和 `raw_payload` | 明确支持的扩展头和分块范围，补齐正常、缺块、重复块及截断样本，并验证无法重组时的诊断输出 |
| 第二阶段交付范围 | `CaptureRecord` 和 `FirmwareEvent` 已可独立生产与测试 | 优先交付可脱离串口运行的协议解析模块与回归样本。报文列表、波形关联、跨设备时钟和持久化可在规划书中分别估算 |

样本扩充可优先覆盖 Request、Accept、PS_RDY、VDM、Extended Message 和 CRC 异常。大负载吞吐、队列积压以及跨设备时间关联需要各自的测量方法。电子负载恒流控制按独立事项规划实机验收。

## 5. 复现命令与资料索引

以下 PowerShell 命令在 `host_app` 目录执行。串口号、参考电压和容差按实际接线设置。`--wire-log` 需要新文件名。

```powershell
New-Item -ItemType Directory -Force ../tmp | Out-Null
python -m unittest discover -s tests -v
python -m electronic_load_gui.devices.drpd --list
python -m electronic_load_gui.devices.drpd COM15 --capture-seconds 10 --verify-empty --wire-log ../tmp/drpd-cdc-retest.jsonl
python tests/drpd_dual_hardware.py COM15 COM18 --voltage 6.2 --tolerance 0.10
```

固件主机端测试在 DRPD 固件工作区执行 `ctest --test-dir build/hosttests -C Debug --output-on-failure`。

| 资料 | 位置 |
| --- | --- |
| 开发说明与运行入口 | [上位机 README](README.md) |
| 可复用驱动与解析入口 | [DrpdDevice](electronic_load_gui/devices/drpd/device.py)、[CaptureClient](electronic_load_gui/devices/drpd/capture_client.py)、[记录类型与解析器](electronic_load_gui/devices/drpd/capture_record.py) |
| 已提交的原始样本与双机脚本 | [CDC 实机样本](tests/fixtures/drpd_cdc_blocks.hex)、[双实机验收脚本](tests/drpd_dual_hardware.py) |
| 本机原始日志 | [改造前 CDC 基线](../tmp/drpd-cdc-before.jsonl)、[连续捕获](../tmp/drpd-cdc-live.jsonl)、[扩展捕获](../tmp/drpd-cdc-live-extended.jsonl)、[Source Cap 对照](../tmp/drpd-cdc-source-cap.jsonl)、[最终空队列](../tmp/drpd-cdc-final-empty.jsonl)、[双实机 6.2 V](../tmp/drpd-dual-voltage-6p2.jsonl) |

`tmp/` 中的日志保留在本次联调工作区。跨机器复核可使用已提交的原始块和复现脚本。
