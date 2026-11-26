# DRPD 第二阶段最终验收报告

| 项目 | 结果 |
| --- | --- |
| 验收日期 | 2026-11-26，北京时间 |
| 分支 | `feature/usb-pd-decoder` |
| 验收版本 | USB-PD 第二阶段 M7，上位机版本 `0.3.1` |
| M6 对比基线 | `2ecbd84473ff2223013f11aec737594cbd50e252` |
| 规范基线 | USB PD Revision 3.2 Version 1.1（2024-10） |
| 实机 DUT | 酷态科 10 号充电器 Mini，DRPD 复刻板 `COM15` |
| 软件验收 | 全量 159 项、纯 Python 114 项、完整压力 7 项均通过 |

## 阶段交付

| 计划项 | 结果与证据 |
| --- | --- |
| M7-01 协议支持矩阵 | 完成真实、构造、部分支持和实机未测的对应说明。[支持矩阵](USB_PD_PROTOCOL_SUPPORT_MATRIX.md) |
| M7-02 全链路回归 | CDC 到普通报文、PDO/RDO、VDM/VDO、Extended 和 EPR 的混合回放通过。[测试覆盖](M7_TEST_COVERAGE.md) |
| M7-03 样本补充 | 新增 48 条真实 CDC 帧与独立构造清单。已复跑 M6 三条真实扩展帧。[DUT 捕获索引](../tests/fixtures/usb_pd_m7_cuktech10mini_real.json) |
| M7-04 稳定性 | 完成 100,000 帧混合回放、100,000 组随机输入、10,000 次完整重组、10,000 组异常分块和 1,000 次复位/断开循环 |
| M7-05 性能 | 同环境复测 76,000 帧基准，另测单类、并发 SOP 及超时场景。[性能报告](M7_PERFORMANCE_REPORT.md) |
| M7-06 接口冻结 | 保留原始记录与诊断，验证公开字段和结果确定性。通过 Python 3.11 语法检查，协议测试未加载 PySide6 |
| M7-07 第二阶段验收 | 完成报告、基线、版本与发布记录。[M7 基线](M7_BASELINE.md) |

M0–M3 的 SOP、Header、分类和 CRC，M4 的能力和请求关联，M5 的 VDM/VDO，以及 M6 的分块与 EPR 路径均已纳入回归。 [M0–M3 验收报告](../DRPD_第二阶段验收报告.md) · [M4 验收报告](../DRPD_第二阶段_M4_验收报告.md) · [M5 验收报告](../DRPD_第二阶段_M5_验收报告.md) · [M6 验收报告](../DRPD_第二阶段_M6_验收报告.md)

## 酷态科 10 号充电器 Mini 实机记录

2026-11-26 20:58:09–20:58:14，固件 `1.0.0-beta.1`，捕获周期 10 ns。DUT 型号由现场接线确认。DRPD 在采集前后均为 `PE_SNK_READY`，采集后恢复捕获开关至 `OFF`。10 个只读查询窗口共保存 48 条原始 CDC 帧。

| 项目 | 观测和回放结果 |
| --- | --- |
| Source Capabilities | 5 个 Fixed PDO 为 5、9、12、15 V 各 3 A 和 20 V／5 A。2 个 PPS APDO 为 5–11 V／5 A、5–20 V／5 A |
| Request 与控制流 | `0x1144B12C` 选择第 1 个 PDO，工作和最大工作电流字段均为 3 A。随后捕获 Accept 与 PS_RDY |
| Extended 三条正向证据 | Source_Capabilities_Extended 为 25 B，Status 为 7 B，Get_Manufacturer_Info 请求为 2 B。三条均为 Chunk 0，Manufacturer Info 的对端返回为 `Not_Supported` |
| Revision、Source_Info | 真实数据对象分别保留为 `0x31180000`、`0x80787878`，分类和 CRC 通过 |
| Identity 与 SVIDs | Identity ACK 的 VID 为 `0x2B01`，缺少 DFP VDO。Discover SVIDs 通告 `0x2717` |
| Modes | 查询 `0x2717` 后收到 SVID `0xFF01`、VDO `0x00000405`。关联诊断为 `vdm_discovery_response_mismatch`，发现缓存未接收该响应 |
| Security_Request | `GET_DIGESTS` 实机发送的帧声明 Unchunked 和 4 B Data Size，却携带 2 个 Data Object 及多余字节。原始采集回放给出 `invalid_unchunked_header` 和 `extended_length`，对端返回 `Not_Supported` |

47 条结构正常的帧通过解析器 CRC 核验。异常 Security_Request 仍可从原始字节独立重算 CRC，解析器因帧长与声明不符将 CRC 状态保留为不可用，重组器拒绝将该帧发布为完整消息。 [实机样本索引](../tests/fixtures/usb_pd_m7_cuktech10mini_real.json) · [原始 CDC 块](../tests/fixtures/usb_pd_m7_cuktech10mini_blocks.txt)

DRPD 的 EPR 配置为 `ON`，EPR PDO 缓存计数为 `0`，实机记录未出现 EPR Source Capabilities。合规 Unchunked、多块 Extended、反向 Request Chunk、SPR AVS／EPR 请求、多 SOP 同时分块及分块期间复位由构造样本验证。5 V／3 A 为线上请求参数。

## 回归发现与修复

构造回放复现了 SVID 列表发布缺陷。已收到第一页时，中间 ACK 若带有 CRC 正确但格式无效的续页，旧逻辑仍可能用后续终止页发布截短列表。修复后，该轮分页标记为中断，末页回放给出 `vdm_context_missing`，上一份完整列表继续可读。测试覆盖终止页重传和下一轮发现恢复。

完整压力包含 100,000 条普通与扩展混合帧、100,000 条固定种子异常输入、190,000 条分块与请求帧形成的 10,000 次完整重组、10,000 组乱序/重复/冲突分块，以及 1,000 次 Reset/Disconnect 周期。结束时重组活动数和来源字节计数均为零。详细执行入口见 [测试覆盖清单](M7_TEST_COVERAGE.md)。

## 发布记录与第三阶段衔接

第二阶段最终验收提交使用主题 `Complete USB PD phase-two regression and verification`。M6 单独保留为父基线，最终提交记录代码修复、回归工具、样本与验收文档。可从仓库根目录以以下命令获取报告对应的提交。

```powershell
git log -1 --format='%H %s' -- 'host_app/docs/DRPD_第二阶段最终验收报告.md'
```

第三阶段可直接消费冻结的捕获、PDO/RDO、VDM/VDO、Extended 和重组结果模型。协议支持边界与接口表见 [USB-PD 协议支持矩阵](USB_PD_PROTOCOL_SUPPORT_MATRIX.md)。
