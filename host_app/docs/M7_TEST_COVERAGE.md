# M7 测试覆盖清单

| 计划编号 | 工程入口 | 验证点 |
| --- | --- | --- |
| T-M7-INT-01–03 | `test_protocol_replay.py`、`test_protocol_integration.py` | 真实控制消息、7 个 PDO、5 V / 3 A Request、Accept 与 PS_RDY；构造回放核对所选 PDO |
| T-M7-INT-04–05 | `test_protocol_integration.py`、`test_protocol_stress.py` | Soft/Hard/Cable Reset 的清理差异，角色切换、断开与多地址隔离 |
| T-M7-INT-06–09 | `test_protocol_replay.py`、`test_protocol_integration.py`、`test_vdm_context.py` | 真实 Identity、SVIDs、Modes 和错配诊断；结构化和非结构化 VDM、完整 Identity、模式位置和厂商字段 |
| T-M7-INT-10–14 | `test_protocol_integration.py`、`test_extended.py`、`test_epr.py` | 单帧与多块、反向请求、EPR Source Capabilities、EPR Fixed/AVS、SPR AVS |
| T-M7-INT-15–16 | `test_protocol_integration.py`、`test_protocol_compatibility.py` | 三种独立会话、原始 CDC 块重编码一致、结果确定性和只读字段 |
| T-M7-ST-01–04 | `test_protocol_stress.py`、`test_extended.py`、`test_usb_pd.py` | 空输入、固定种子随机帧、短帧、CRC 和未知消息类型 |
| T-M7-ST-05–08 | `test_protocol_stress.py`、`test_reassembly.py`、`test_extended_context.py` | 晚到、冲突、乱序、重复、缺块、多 SOP 流和异常 SVID 续页 |
| T-M7-ST-09–12 | `test_protocol_stress.py`、`test_extended_context.py`、`test_vdo.py` | 活动数/来源字节上限、复位、断开、解码器异常隔离 |
| T-M7-PERF-01–07 | `protocol_benchmark.py`、`test_protocol_performance.py` | M6 等价基准、普通 PD、VDM、单块以及多 SOP 并发重组、超时后的状态和内存 |

## 测试样本索引

| 阶段 | 来源 | 索引与覆盖 |
| --- | --- | --- |
| M0–M3 | real | 固件事件、Hard Reset、Source Capabilities、CRC。[样本索引](../tests/fixtures/usb_pd_real.json) |
| M4 | real | Source Capabilities 和真实 Fixed Request 的同轮关联。[Request 索引](../tests/fixtures/usb_pd_request_real.json) |
| M5 | real | Identity、SVIDs、Modes、SVID 错配。[Identity 索引](../tests/fixtures/usb_pd_vdm_real.json) · [发现索引](../tests/fixtures/usb_pd_vdm_discovery_real.json) |
| M5 | synthetic | 完整 Identity、模式、SVID 与非结构化 VDM。[构造索引](../tests/fixtures/usb_pd_vdm_synthetic.json) |
| M6 | real | 三条单块 Extended Message，原始 CDC 块和 CRC。[样本索引](../tests/fixtures/usb_pd_extended_real.json) |
| M6 | synthetic | Unchunked 大小边界、两块及多块、Request Chunk、EPR/AVS。[构造索引](../tests/fixtures/usb_pd_extended_synthetic.json) |
| M7 | real | CUKTECH 10 Mini 的 48 条原始 CDC 帧，10 个查询窗口，包含格式异常的 Security_Request。[样本索引](../tests/fixtures/usb_pd_m7_cuktech10mini_real.json) · [原始 CDC 块](../tests/fixtures/usb_pd_m7_cuktech10mini_blocks.txt) |
| M7 | synthetic | 普通、PDO/RDO、VDM、Extended、复位和 EPR 请求进入同一个 CDC 回放链。[构造索引](../tests/fixtures/usb_pd_m7_synthetic.json) |

压力帧由 `test_protocol_stress.py` 构造，固定随机种子 `0x7632`。快速回归与完整压力执行相同断言，使用 `M7_FULL_STRESS=1` 启用 100,000 普通混合帧、100,000 随机帧、10,000 次完整重组、10,000 组异常分块和 1,000 次断开/复位循环。
