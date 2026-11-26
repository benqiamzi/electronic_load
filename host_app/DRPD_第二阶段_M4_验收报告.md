# DRPD 第二阶段 M4 验收报告

| 项目 | 结果 |
| --- | --- |
| 验收日期 | 2026-11-26 |
| 开发分支 | `feature/usb-pd-decoder` |
| M0–M3 基线 | `21ae872` |
| 规范 | USB PD Revision 3.2 Version 1.1（2024-10）§6.4.1、§6.4.2、§6.8 |
| 验收结论 | M4-01 至 M4-10 全部通过 |
| 验证方式 | DRPD 原始 CDC 实机样本离线回放、人工构造协议样本、上位机全量回归 |

PDO 位域和换算依据规范表 6.8–6.22，RDO 依据表 6.23–6.25 及 §6.4.2，交叉核对了已有 DRPD Python 的 `power.py` 与 `request.py`。 [USB-IF 规范版本说明](https://usb.org/euconformity)

## 实机证据

2026-11-25 的 DRPD `COM15` 捕获日志中保存了同一轮协商的两条记录。该次捕获使用固件 `1.0.0-beta.1` 和 10 ns 捕获周期。本次验收从已有日志提取 Request 原始 SCPI 块，并与既有 Source_Capabilities 样本一起经二进制块、捕获记录、报文解析和会话关联接口回放。 [原始能力样本索引](tests/fixtures/usb_pd_real.json) · [原始 Request 样本](tests/fixtures/usb_pd_request_real.json)

| 报文 | 捕获起始时间（µs） | Header | 主机计算与报文 CRC | 结果 |
| --- | ---: | --- | --- | --- |
| `Source_Capabilities` | 32,788,569 | `0x77A1` | `0x34737FBF` | 7 个 PDO 全部解析通过 |
| `Request` | 32,798,265 | `0x1482` | `0xA7070B60` | RDO `0x1144B12C` 指向第 1 个 PDO |

| 位置 | 原始 PDO | 类型 | 电压或范围 | 最大电流 | PPS Power Limited |
| ---: | --- | --- | ---: | ---: | --- |
| 1 | `0x0A01912C` | Fixed | 5 V | 3 A | — |
| 2 | `0x0002D12C` | Fixed | 9 V | 3 A | — |
| 3 | `0x0003C12C` | Fixed | 12 V | 3 A | — |
| 4 | `0x0004B12C` | Fixed | 15 V | 3 A | — |
| 5 | `0x000641F4` | Fixed | 20 V | 5 A | — |
| 6 | `0xC8DC3264` | PPS | 5–11 V | 5 A | 置位 |
| 7 | `0xC9903264` | PPS | 5–20 V | 5 A | 置位 |

真实 Request 的工作电流和最大工作电流均为 3000 mA，所选 Fixed PDO 的额定电压为 5000 mV。`rdo.operating_voltage_mv` 对 Fixed 请求为空，电压从关联的 PDO 读取。该样本只验证请求读取和对象关联，供电合同状态和物理输出需要其他数据验证。

## 验收清单

| 编号 | 验收项 | 证据 | 结果 |
| --- | --- | --- | --- |
| M4-01 | 实机 PDO 解析 | 同一原始 CDC 块的 7 个 PDO 逐项断言 | 通过 |
| M4-02 | PDO 类型识别 | Source/Sink Fixed、Variable、Battery、PPS，AVS 能力字段及未知 APDO 诊断 | 通过 |
| M4-03 | 物理量换算 | 50 mV、100 mV、10 mA、50 mA、250 mW 及 PPS 请求的 20 mV 步长 | 通过 |
| M4-04 | RDO 字段 | 真实 Fixed 请求，以及标记为 synthetic 的 Fixed、Variable、Battery、PPS 请求 | 通过 |
| M4-05 | 对象关联 | 真实位置 1 及人工构造的能力更新、越界位置、未知对象保留 | 通过 |
| M4-06 | 合法性检查 | 位置 0 / 8–15、未通告位置、保留位、请求电流/功率/电压越界、错误 PDO 来源 | 通过 |
| M4-07 | 上下文管理 | 能力缓存更新、CRC 或固件失败隔离、SOP 隔离、Soft/Hard/Cable Reset、断开清理 | 通过 |
| M4-08 | 原始数据保留 | `CaptureRecord`、正文、原始对象和 CRC 独立可读，语义失败时仍可检查报文 | 通过 |
| M4-09 | 原有功能回归 | 全量 86 项测试通过 | 通过 |
| M4-10 | 纯 Python 运行 | `python -S` 环境执行 41 项协议测试，校验 `sys.modules` 中无 `PySide6` | 通过 |

合成测试覆盖了现场样本没有出现的 Variable、Battery、PPS 请求，以及复位、非法位域和超限场景。完整测试可从 `host_app` 目录运行。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests
'test_usb_pd.py', 'test_pdo.py', 'test_rdo.py', 'test_pd_session.py' | ForEach-Object {
    python -S -m unittest discover -s tests -p $_
}
```

## 接口和上下文规则

- `parse_capture(record)` 解析单条捕获。`PDMessageResult.pdos` 和 `.rdo` 分别携带能力和请求语义，基础字段及解析状态供现有调用者继续使用。
- `PDSessionContext.consume(result)` 返回 `PDSessionAnalysis`。主机 CRC 通过且基础解析有效的 `Source_Capabilities` 按 SOP 更新缓存。无效或未知 PDO 仍占用原始位置。Request 在该 SOP 的缓存内按一基位置关联，结果放在 `analysis.rdo`。
- 捕获到有效 Soft Reset 时，仅使对应 SOP 的旧能力快照失效，等待再次通告。Hard Reset 清空所有快照。Cable Reset 清理 SOP′/SOP″ 的记录并保留 SOP 电源能力。断开或丢失捕获连续性时，由调用者执行 `disconnect()` 或 `reset()`。
- PD 2.0 的 GiveBack 请求按旧版最低工作值解释。PD 3.x 报文 Header 无法区分 3.0、3.1 与 3.2。旧设备的最大工作值与工作值不等时，在其余条件通过的前提下输出 `legacy_maximum` 诊断，并保留字段。

## 后续阶段输入

M5 可继续在基础报文模型上增加 VDM/VDO 字段。SPR AVS 和 EPR AVS 已有能力字段解码，完整请求解释及 EPR 能力消息需要 M6 的 Extended Message 支持。M7 可利用同一回放入口扩充真实请求类型和性能验收样本。第三阶段界面可直接读取 `PDOInfo`、`RDOInfo`、`ParseDiagnostic` 和原始报文数据，并在设备断开事件中清理会话。
