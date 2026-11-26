# DRPD 第二阶段 M5 验收报告

| 项目 | 结果 |
| --- | --- |
| 验收日期 | 2026-11-26 |
| 开发分支 | `feature/usb-pd-decoder` |
| 前置基线 | M0–M4 当前工作区，M4 验收报 86 项全量测试、41 项纯 Python 协议测试通过 |
| 规范 | USB PD Revision 3.2 Version 1.1（2024-10） |
| 验收结论 | M5 §10.1–§10.4 的交付项通过，实机覆盖 Identity、SVIDs 和 Modes 的发现请求及响应 |

## 位域与命令依据

VDM Header 依据 §6.4.4 和表 6.28–6.32，Identity 依据 §6.4.4.3.1 和表 6.33–6.38，SVID 列表依据 §6.4.4.3.2 和表 6.45。Mode VDO 的位置和响应载荷数依据 §6.4.4.3.3–§6.4.4.3.6。复位行为参考 §6.8。实现时交叉核对了 DRPD 固件 `structured_vdm` 及 DRPD Python 的 `vendor.py`。 [USB-IF 规范版本说明](https://usb.org/euconformity)

| VDM Header 位域 | Structured | Unstructured |
| --- | --- | --- |
| 31:16 | SVID | USB VID |
| 15 | 1 | 0 |
| 14:13 | 版本 Major 的线上编码，`00` 为可回放的旧版 1.0，`01` 为 2.x | 厂商自定义 |
| 12:11 | 通用命令的版本 Minor，2.x 下 `00` 为 2.0，`01` 为 2.1。16–31 号命令由 SVID 定义 | 厂商自定义 |
| 10:8 | Object Position，按命令校验 | 厂商自定义 |
| 7:6 | `00` Initiator、`01` ACK、`10` NAK、`11` BUSY | 厂商自定义 |
| 5 | 保留位 | 厂商自定义 |
| 4:0 | Command | 厂商自定义 |

| Command | 名称 | SVID 和 SOP | Object Position | 响应和 VDO |
| ---: | --- | --- | --- | --- |
| 1 | Discover Identity | PD SID `0xFF00`，SOP/SOP′ | 0 | ACK 含 ID Header、Cert Stat、Product 和适用的产品类型 VDO。NAK/BUSY 无 VDO |
| 2 | Discover SVIDs | PD SID，SOP/SOP′ | 0 | ACK 含 1–6 个 SVID 对。NAK/BUSY 无 VDO |
| 3 | Discover Modes | 被查询 SVID，SOP/SOP′ | 0 | ACK 含 1–6 个 Mode VDO，按位置组织。NAK/BUSY 无 VDO |
| 4 | Enter Mode | 目标 SVID，SOP* | 1–6 | Initiator 可带 1 个 VDO，ACK/NAK 无 VDO |
| 5 | Exit Mode | 目标 SVID，SOP* | 1–6，7 表示退出所有活动模式 | Initiator、ACK、NAK 无 VDO |
| 6 | Attention | 目标 SVID，SOP* | 1–6 | 只有 Initiator，可带 1 个 VDO |

Identity 中解码 USB VID、USB Host/Device 和 Modal 能力、产品类型和连接器类型，以及 XID、USB PID 和 `bcdDevice`。按 PD 3.x 的产品类型标注 UFP、DFP、线缆与 VPD 附属对象，检查 DRD 的零填充位置。附属对象的专用位域和旧版身份尾部保留原字。

SVID 响应的每个 VDO 先读高 16 位，再读低 16 位。零值结束当前列表。满 12 项且无零值是续页。Mode VDO 依次对应位置 1–6，模式载荷可交给显式注册的解码器。厂商返回值保存在 `vendor_fields`。

## 实机证据

2026-11-26 10:32（北京时间）在 `COM15` 的 DRPD 上查询身份。固件为 `1.0.0-beta.1`，端口状态为 `PE_SNK_READY`，捕获周期为 10 ns。发起 `SINK:INQ DISCOVER_IDENTITY` 后，固件报告收到 16 字节数据正文。原始 CDC 块、捕获字段及来源标记已固化为回放样本，抓包结束后恢复原有捕获开关。 [真实样本索引](tests/fixtures/usb_pd_vdm_real.json)

| 帧 | DRPD 起始时间（µs） | PD Header | VDM Header | 主机验证 CRC | 语义结果 |
| --- | ---: | --- | --- | --- | --- |
| Discover Identity 请求 | 5,457,247,659 | `0x128F` | `0xFF00A801` | `0x06D1477C` | SOP、Initiator、SVDM 2.1 |
| Discover Identity ACK | 5,457,250,978 | `0x47AF` | `0xFF00A041` | `0x926D121C` | SOP、ACK、SVDM 2.0、`partial` |

ACK 携带 `0x05C02B01`、`0x00000000`、`0x0000A819` 三个身份 VDO。解码得到 USB VID `0x2B01`、XID `0x00000000`、USB PID `0x0000` 和原始 `bcdDevice` `0xA819`。ID Header 的 DFP 产品类型为 3，按表 6.36 应有第四个 DFP VDO。该 ACK 的报文长度与 CRC 校验均通过，语义解析报告 `vdo_truncated` 并保留收到的三个对象。

### SVIDs 和 Modes 补充实机回归

同日 20:05–20:06（北京时间）在同一 DRPD CDC 端口记录两段独立的捕获窗口。新增索引包含 18 条原始 PD 帧，包括用于验证请求关联的 GoodCRC。所有帧的主机 CRC 均通过。 [补充实机样本索引](tests/fixtures/usb_pd_vdm_discovery_real.json)

| 查询 | 线上响应 | 回放结果 |
| --- | --- | --- |
| Discover Identity | ACK 仍缺少 DFP VDO | 保留三个身份对象并标为 `partial` |
| Discover SVIDs | ACK 的 VDO `0x27170000` | 读出 SVID `0x2717`，低半字为零终止符 |
| Discover Modes，SVID `0x2717` | 响应的 SVID 为 `0xFF01`，固件报告 `ABORTED` | 保留原始 ACK，记录 `vdm_discovery_response_mismatch`，两个 SVID 的 Mode 缓存均不更新 |
| 单独查询 Discover Modes，SVID `0xFF01` | 匹配的 ACK 携带一个 `0x00000405` | 原字保存在第 1 个 Mode VDO。该窗口缺少前序 SVID 列表，关联状态为 `context_missing` |

单独查询 `0xFF01` 的请求使用 SVDM 2.0，回复使用 2.1。依据 §6.4.4.2.3，关联结果附加 `vdm_discovery_response_version` 诊断。Mode VDO 按实收原字记录。

完整 Identity ACK、SVID 多页、Mode 事件和厂商解码器路径由明确标记的构造样本覆盖。 [构造样本索引](tests/fixtures/usb_pd_vdm_synthetic.json)

## 验收清单

| 计划条目 | 验证内容 | 结果 |
| --- | --- | --- |
| §10.1 VDM 基础解析 | 位域、1.0/2.0/2.1、标准命令与响应、SOP、角色、保留位、空对象和未知命令 | 通过 |
| §10.2 标准 VDO 解析 | Identity 及产品类型对象、SVID 终止与续页、Mode 位置、NAK/BUSY、未知 VDO 和原字回溯 | 通过 |
| §10.3 扩展能力 | 厂商注册与异常隔离，发现请求关联与错配隔离，按 SOP/SVID/响应端缓存、更新和复位 | 通过 |
| §10.4 回归和稳定性 | 全量 120 项测试，纯 Python 75 项协议测试，原始报文与样本索引，README 和验收报告 | 通过 |

运行时为 Python 3.13.2。用 `python -S` 执行纯协议测试并检查未加载 `PySide6`，同时核对源码可由 Python 3.11 语法分析器解析。从 `host_app` 目录可运行回归。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests
'test_usb_pd.py', 'test_pdo.py', 'test_rdo.py', 'test_pd_session.py', 'test_vdm.py', 'test_vdo.py', 'test_vdm_context.py' | ForEach-Object {
    python -S -m unittest discover -s tests -p $_
}
```

## 会话规则与后续范围

- `VDMContext` 仅使用基础解析、CRC 和 VDM 语义均通过的报文更新发现信息。SOP 按响应端数据角色分开，线缆按 SOP′/SOP″ 分开，Modes 再按 SVID 记录。Context 返回的 Mode 关联表示找到了对应的通告对象。
- `VDMAnalysis.request` 保存已观察到的前序请求。观察到请求时，响应须匹配命令编号和 SVID 才能更新发现缓存。仅捕获 ACK 时，`request` 为空，仍可记录 ACK 本身证实的字段。
- 终止页到达后发布 SVID 列表，保留各页的原始结果。Soft Reset 保留已完成的发现记录并丢弃对应 SOP 的未完成分页。Hard Reset 和断开清理全部。Cable Reset 清理线缆发现。Data Reset Complete 清理线缆发现及旧 Mode 事件。观察到 DR_Swap 后紧接 Accept 时，使旧 SOP 角色缓存失效。
- 每个 SOP 默认保留最近 128 条 Mode 事件。Enter/Exit 响应与 Attention 命令保持独立的观测结果，Alternate Mode 状态判定属于后续工作。
- M6 可继续在同一捕获入口扩展 Extended Message 与分块重组。后续实机回归可扩充完整身份 ACK、SVID 多页和 Mode 进入、退出样本。
