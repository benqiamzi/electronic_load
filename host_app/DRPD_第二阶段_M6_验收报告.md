# DRPD 第二阶段 M6 验收报告

| 项目 | 结果 |
| --- | --- |
| 验收日期 | 2026-11-26 |
| 开发分支 | `feature/usb-pd-decoder` |
| 前置基线 | M4/M5 GitHub 提交 `14feb21`，120 项全量测试、75 项纯 Python 协议测试通过 |
| 规范 | USB PD Revision 3.2 Version 1.1（2024-10） |
| 验收结论 | M6-01 至 M6-09 软件交付通过。实机验证覆盖 3 条使用分块格式的单块扩展消息 |

## 规范核对

Extended Header、分块、填充和大小上限依据 §6.2.1.2 及表 6.3、6.84。类型码依据表 6.53。EPR 能力和请求依据 §6.5.15、§6.4.9 和表 6.23–6.26，AVS 电流上限依据 §6.4.2.8、§7.1.4.3.2。 [USB-IF 规范版本说明](https://www.usb.org/euconformity)

| Extended Header 位 | 含义 | 校验 |
| --- | --- | --- |
| 15 | Chunked | 清零表示 Unchunked，线上 PD Header 对象数为零 |
| 14:11 | Chunk Number | 数据块 0–9，请求块 1–9，Unchunked 时为零 |
| 10 | Request Chunk | 分块反向请求，Data Size 为零，PD Header 有一个对象 |
| 9 | Reserved | 必须为零 |
| 8:0 | Data Size | 整个数据块的长度，最多 260 字节 |

| 帧型 | 有效内容与物理边界 |
| --- | --- |
| Unchunked | SOP，Extended Header 后为 0–260 字节有效数据，无填充 |
| Chunk Data | 每块最多 26 字节，最后一块取余量。Extended Header 和有效字节按 4 字节边界补零 |
| Request Chunk | 仅 Extended Header 和 2 字节零填充。按同 SOP、同消息类型及反向发送端关联 |

| 类型码 | 识别范围 |
| --- | --- |
| `0x01`–`0x07` | Source_Capabilities_Extended、Status、电池与 Manufacturer Info |
| `0x08`–`0x0B` | Security 和 Firmware Update 请求及响应 |
| `0x0C`–`0x10` | PPS Status、Country Info/Codes、Sink Capabilities Extended、Extended Control |
| `0x11`、`0x12`、`0x1E` | EPR Source Capabilities、EPR Sink Capabilities、Vendor Defined Extended |
| 其他 | 保留原始类型码和载荷，给出未知类型诊断 |

EPR Source Capabilities 语义解码已实现。其他扩展类型在本阶段验证单帧格式和重组载荷，保留原字节供进一步解码。

| EPR/AVS 字段 | 实施结果 |
| --- | --- |
| 能力列表 | 槽 1–7 为 SPR，保留未使用的零填充槽。槽 8–11 为 EPR Fixed 或 EPR AVS |
| `EPR_Request` | 两个 32 位对象依次为 RDO、所选 PDO 的原字回显。回显与最新有效通告逐位核对 |
| SPR AVS RDO | 电压字段 25 mV 编码，低两位为零形成 100 mV 步长。电流单位 50 mA，按 15 V 和 20 V 档核对 |
| EPR AVS RDO | 电压及电流步长同上，允许电流取 PDP/电压与 5 A 的较小值，再向下取整至 50 mA |

## 实机证据

2026-11-26 20:24–20:37（北京时间），DRPD `COM15` 使用 `1.0.0-beta.1` 固件和 10 ns 捕获周期，在 `PE_SNK_READY` 分两轮执行只读查询。两轮结束均恢复捕获开关至 `OFF`。以下帧均经原始 CDC Binary Block、`CaptureRecord`、`parse_capture()` 和重组入口回放。 [真实样本索引](tests/fixtures/usb_pd_extended_real.json)

| 帧 | DRPD 起始时间（µs） | Data Size | 零填充 | 主机验证 CRC |
| --- | ---: | ---: | ---: | --- |
| Source_Capabilities_Extended | 1,172,683,342 | 25 B | 1 B | `0x253923B7` |
| Status | 1,173,185,845 | 7 B | 3 B | `0x29C8CF7B` |
| Get_Manufacturer_Info | 1,949,196,664 | 2 B | 0 B | `0xE311A27D` |

三帧均为 Chunked 格式的 Chunk 0，单块即可恢复完整载荷。Get_Manufacturer_Info 收到对端 `Not_Supported`。固件报告 EPR 配置开关为 `ON`，缓存的 EPR PDO 数为 `0`。本轮实机覆盖通用扩展帧格式、三组 CRC 和零填充，Unchunked、多块、反向分块请求及 EPR/AVS 路径由构造样本验证。 [构造样本索引](tests/fixtures/usb_pd_extended_synthetic.json)

## 验收与生命周期

| 编号 | 验证内容 | 结果 |
| --- | --- | --- |
| M6-01 | Extended Header 位域、保留位及组合诊断 | 通过 |
| M6-02 | 0–260 字节 Unchunked、无填充、未知类型及 CRC | 通过 |
| M6-03 | 两块和十块重组、乱序排序、只拼接有效字节和来源回溯 | 通过 |
| M6-04 | 反向 Request Chunk、已收分块请求、请求越界和关联缺失 | 通过 |
| M6-05 | 设备时间超时、Reset/断开、SOP/类型/发送端隔离及资源上限 | 通过 |
| M6-06 | 重复、冲突、缺块、截断、迟到分块及随机输入 | 通过 |
| M6-07 | EPR Source Capabilities 完整与部分解析、SPR 零槽、EPR PDO 类型与顺序 | 通过 |
| M6-08 | SPR AVS、EPR Fixed/AVS 关联、PDO 回显、范围和能力更新 | 通过 |
| M6-09 | 144 项全量测试、99 项无 PySide6 协议测试、离线性能和内存基线 | 通过 |

- 重组默认使用 1 s 的设备时间保留窗口，最多 16 条活动传输和 256 KiB 的捕获来源数据。字节上限计入原始包、解码字节、SOP 和脉宽条目，Python 分配另行测量。近期完成帧的去重摘要也有数量和时间上限。
- 乱序缓存仍须等到所有编号齐全才发布完整载荷。部分结果的 `payload` 只包含从 Chunk 0 开始的连续前缀，其他已收块仍可从 `frames` 读取。
- 普通 Soft Reset 按 SOP 清理。Hard Reset 和断开清理整条链路。Cable Reset 与 Data Reset Complete 清理线缆传输。观测到电源角色切换请求时，使该 SOP 的活动传输失效。
- EPR 能力缓存仅接收完整校验的通告，独立于普通 SPR 能力。该快照用于匹配请求，合同状态及物理供电仍需由后续消息与测量确认。

## 离线性能与内存基线

在 Windows、Python 3.13.2 上交替模拟 SOP 和 SOP′，每次重组 260 B，含 10 个数据帧和 9 个反向请求帧。计时涵盖 `parse_capture()`、CRC 和 `consume()`，测试向量与串口读取置于计时区间之外。每次都核对重组载荷，回放结束后活动传输和缓存来源字节均为零。

| 指标 | 结果 |
| --- | --- |
| 4,000 次重组，76,000 帧 | 约 4.73 s，16,053 帧/s，62.29 µs/帧 |
| 扩展有效载荷吞吐 | 约 214.5 KiB/s |
| 重组器峰值来源字节计数 | 468 B（构造帧无模拟脉宽） |
| `tracemalloc` 峰值 | 7,600 帧比对为 29,729 B，76,000 帧为 29,721 B |

从 `host_app` 运行回归。纯协议测试使用 `python -S` 并检查 `PySide6` 未加载，同时以 Python 3.11 语法模式检查协议模块。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests
'test_usb_pd.py', 'test_pdo.py', 'test_rdo.py', 'test_pd_session.py', 'test_vdm.py', 'test_vdo.py',
'test_vdm_context.py', 'test_extended.py', 'test_reassembly.py', 'test_extended_context.py', 'test_epr.py' | ForEach-Object {
    python -S -m unittest discover -s tests -p $_
}
```
