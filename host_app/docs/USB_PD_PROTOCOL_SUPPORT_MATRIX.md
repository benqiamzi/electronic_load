# USB-PD 协议支持矩阵

本矩阵冻结第二阶段上位机协议接口。`real-verified` 表示实机原始 CDC 回放通过。`synthetic-verified` 表示构造向量和自动化测试通过。`partial` 表示样本不完整或只解释部分字段。`unsupported` 表示语义尚未实现。`not-tested` 表示该场景缺少实机证据。

| 功能 | 软件与证据 | 范围与边界 |
| --- | --- | --- |
| DRPD CDC 块、CaptureRecord、固件事件 | `real-verified` | 报文、脉宽和原始块可回溯，截断与错误边界另有构造覆盖 |
| SOP、PD Header、CRC32 | `real-verified`，`synthetic-verified` | 实机 SOP 和 Hard Reset，SOP′、SOP″、Cable Reset 与保留位由构造样本覆盖。CRC 状态与语义状态独立 |
| Control/Data/Extended 分类 | `real-verified`，`synthetic-verified` | 未知类型保留原值。Revision、Source_Info 等未专门实现的语义保持原字 |
| Fixed/PPS Source PDO 与 Fixed RDO | `real-verified` | 酷态科 10 号充电器 Mini 通告 7 个 PDO，真实 Request 关联第 1 个 Fixed PDO |
| Variable/Battery、Sink PDO 及 Variable/Battery/PPS RDO | `synthetic-verified`，实机 `not-tested` | 整数单位换算、保留位和上限校验 |
| `PDSessionContext` | `real-verified`，`synthetic-verified` | 按 SOP 关联通告和请求，能力更新、复位和断开由回归覆盖 |
| Structured VDM 与标准命令 | `real-verified`，`synthetic-verified` | Identity、SVIDs、Modes；Enter、Exit、Attention 事件路径由构造样本覆盖 |
| Identity VDO | `partial` 实机，`synthetic-verified` 完整布局 | 实机 ACK 保留 ID Header、XID、Product，诊断缺少 DFP VDO |
| SVIDs、Modes 与 `VDMContext` | `real-verified`，`synthetic-verified` | 实机 `0x2717` 通告、`0xFF01` Mode 响应和错配；多页、重传与异常续页由构造覆盖 |
| Unstructured VDM、厂商 VDO 扩展接口 | `synthetic-verified` | 厂商头位和 VDO 保留原字。注册表输出独立字段并隔离解码器异常 |
| Extended Header 与单块 Chunked | `real-verified` | 25 B Source Capabilities Extended、7 B Status、2 B Manufacturer Info 请求。Security Request 格式异常可定位 |
| 合规 Unchunked、完整多块、反向 Request Chunk | `synthetic-verified`，实机 `not-tested` | 本次 DUT 未产生合规样本。每块长度、请求关联、乱序及重组已验证 |
| Extended 重组生命周期 | `synthetic-verified` | 超时、Reset、角色切换、断开、资源限制、来源字节计数 |
| EPR Source Capabilities、EPR Fixed/AVS、SPR AVS | `synthetic-verified`，实机 `not-tested` | EPR 能力槽与回显 PDO 校验独立。DUT 的 EPR PDO 缓存为零 |
| 其他 Extended 载荷语义、特定 Alternate Mode、完整电源合同状态机 | `unsupported` | 保留格式、原始载荷及已观察到的状态。第三阶段界面通过冻结接口消费 |

真实和构造样本索引、自动化测试映射见 [M7 测试覆盖清单](M7_TEST_COVERAGE.md)。实机和软件边界的详细证据见 [第二阶段最终验收报告](DRPD_第二阶段最终验收报告.md)。

## 第三阶段只读接口

| 类型或入口 | 界面可使用的数据 |
| --- | --- |
| `CaptureRecord`、`PDMessageResult` | 捕获时间、SOP、脉宽、原帧、Header、消息分类、body、Data Object、CRC 与诊断 |
| `PDOInfo`、`RDOInfo`、`PDSessionAnalysis` | 原始字、供电类型、mV/mA/mW、请求位置、所选 PDO、EPR 回显与诊断 |
| `VDMInfo`、`VDOInfo`、`VDMAnalysis` | SVID、版本、命令、原字、标准和厂商字段、前序请求与 Mode 关联 |
| `ExtendedHeader`、`ExtendedMessageInfo` | Chunked、块号、Request Chunk、Data Size、单帧有效载荷与填充 |
| `ExtendedAnalysis`、`ReassembledExtendedMessage`、`EPRSourceCapabilities` | 进度、已收和缺失编号、请求与数据帧来源、连续载荷、SPR/EPR 槽 |
| `ParseDiagnostic` | `layer`、`code`、`message`。界面可按 `code` 定位诊断 |

`parse_capture()` 为无状态入口。采集控制器按链路持有 `PDSessionContext`、`VDMContext` 和 `ExtendedMessageReassembler`，断开时清理会话。结果模型为只读数据类，兼容性测试覆盖既有公共字段。
