# STM32F411 电子负载上位机

基于 PySide6、Qt Serial Port 和 pyqtgraph 的桌面上位机，直接兼容本仓库
固件当前的 USB CDC ASCII 命令协议。

## 已实现功能

- 自动枚举串口，并优先显示 `Electronic Load CDC`/`0483:5740` 设备。
- 使用 `*IDN?` 完成设备身份校验，避免误连普通串口。
- 10 Hz 查询电压、电流、功率和左右散热器温度。
- 查询运行状态、锁存故障、恒流设定值和负载输入状态。
- 设置 0～2.5 A 总恒流值，支持 A 路、B 路或 A+B 双路输出；双路模式将总电流均分。
  固件 0.3.6 保留线性 DAC 环路，快速电流 AWD 仅作 2.6 A 安全切除；
  需要硬件栅极钳位（2N7002 跨 C3）才能消除使能尖峰。
- 安全切换环路时先关闭负载、确认 OFF、将双路 DAC 归零，再切换模式；切换后保持 OFF。
- 设置并读回风扇 0～100% PWM 占空比；带载时固件保证至少 30%。
- 顶部工具栏使用分层下拉菜单；通过“DAC 工具”打开独立子窗口，查看两路 DAC
  最近成功写入的设定电压；负载关闭时可单独设置 0～2.5 V，固件 0.3.6
  及以上在带载时可直写所选环路，双路电压合计不超过 0.5 V
  （需要固件 0.2.0 或更高版本）。
  DAC 工具显示的设定电压随电流变化（0.2 V/A）；带载直写进入手动模式，
  “应用电流”恢复自动控制，关闭负载则归零。
- 「保护 → 设置保护阈值」读取并修改设备的过压、过流、过功率和过温阈值，
  支持恢复默认值。需要固件 0.3.7 或更新版本，关闭负载后才可修改。
  当前未安装温度传感器的板卡只显示过温阈值。阈值由 MCU 执行，断电后恢复默认。
- 常规设置命令后读取 `SYST:ERR?`，再读回实际值。保护命令直接返回设备确认的阈值。
- 实时电气参数和温度曲线，默认显示最近 60 秒。
- “曲线工具”下拉菜单控制 CSV 曲线数据记录和曲线清空，并提供可滚动的原始通信日志。
- 串口断开、命令超时、响应格式错误提示。

上位机只负责操作和显示，过流、过压、过功率、过温等安全保护仍由 MCU
固件负责，不能用上位机逻辑替代硬件和固件保护。

实时电压、电流和功率来自 INA226；快速模拟电流通道仅用于固件保护。DAC8552
没有输出回读 ADC，因此工具栏中的两路 DAC 电压是固件跟踪的写入设定值，不是
物理电压实测值。固件 0.3.6 在带载时限制所选通道与合计电压，保留过流保护。

## 环境

- Python 3.11 或更新版本
- Windows 10/11；Qt Serial Port 同时支持 Linux 和 macOS
- 电子负载通过 USB CDC 连接电脑

## 安装与运行

在本目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
python run.py
```

也可以在安装后执行：

```powershell
electronic-load-host
```

## 在 VS Code 中运行

1. 使用 VS Code 打开仓库根目录。
2. 根据工作区提示安装推荐的 Python 和 Python Debugger 扩展。
3. 打开“运行和调试”，选择 `PySide6: 运行电子负载上位机`。
4. 按 `F5`。首次运行会自动创建 `host_app/.venv` 并安装依赖，后续直接启动。

也可以从“终端 → 运行任务”执行 `PySide6: 运行上位机` 或
`PySide6: 运行单元测试`。工作区默认解释器已配置为
`host_app/.venv/Scripts/python.exe`。

## 使用流程

1. 用 USB 连接电子负载，点击“刷新”。
2. 选择显示为 `Electronic Load CDC` 的串口并连接。
3. 确认实时测量值和设备状态正常。
4. 输入小电流值并点击“应用电流”，再打开负载。
5. 需要保存数据时点击“开始记录 CSV”。
6. 异常时点击“紧急关闭”；该按钮发送 `INP OFF`，不能替代物理急停。

程序连接或退出时不会自动改变电子负载输出状态，避免意外改变正在运行的测试。

## USB PD 测试工作区

1. 从窗口左上角的下拉菜单选择“USB PD 测试”。在“设备连接”选择 DRPD 的 USB CDC 端口并连接。电子负载和 DRPD 各使用自己的端口。
2. 在“实时捕获”开始采集。若设备已就绪，可以发送一次源能力查询以产生报文。切回电子负载时采集继续，状态栏仍显示 DRPD 的连接与捕获状态。
3. 选择报文查看原始字节、协议字段和诊断。左侧导航提供 PDO/RDO、VDM/VDO、扩展消息与 EPR，以及诊断定位。筛选和清空显示只影响表格。
4. 停止采集并排空设备队列后，可保存原始捕获为 `.drpd`，也可导出 CSV、解析 JSON 或 Markdown 诊断报告。采集进行时保存的是请求时已落盘的快照。
5. 在“离线回放”打开 `.drpd` 或第二阶段真实样本的原始 JSON，按时间顺序播放、暂停或逐帧查看。

界面继承电子负载上位机的 Fusion 主题。工作区和上次打开的 USB PD 页面会在下次启动时恢复，串口须手动连接。

- [工作区界面和操作规则](docs/phase3/P3_WORKSPACE_DESIGN.md)
- [第三阶段验收报告](docs/phase3/DRPD_第三阶段验收报告.md)

## 测试

协议解析和 CSV 记录测试不需要连接硬件：

```powershell
python -m unittest discover -s tests -v
```

## DRPD 第一阶段

DRPD 使用独立的 `DrpdDevice`。它在 Qt 事件循环中管理 USB CDC 串口、SCPI
请求队列和捕获客户端。现有电子负载窗口和通信模块继续使用原有入口。

- `device.transport.open(port, baud_rate=115200)` 打开串口并设置 DTR。关闭时清理串口缓冲。
- `device.protocol` 提供 `command`、`query_text` 和 `query_binary`。同一串口只允许一项
  查询在途。发生超时、响应错位或帧格式错误时，当前请求和排队请求都结束，重开串口后再发命令。
- `device.capture` 提供启停捕获、查询周期和数量、单条读取、限量排空和定时轮询。
  `capture_received` 返回 `CaptureRecord` 或 `FirmwareEvent`。`CaptureRecord`
  保留完整的原始载荷、SOP、脉宽计数和解码数据。`pulse_widths_ns` 使用设备返回的周期转换。
  `FirmwareEvent` 保留事件编号和原始文本字节，并通过 `text_encoding_valid` 标记无效 UTF-8。
  空队列读取以 `None` 完成，周期缓存随断开清理。
- 默认单条载荷上限为 `32 + 2 × 5600 + 262 = 11494` 字节，由当前 DRPD 固件的
  脉宽和解码缓冲区配置推得。可通过 `DrpdDevice(max_payload_bytes=...)` 调整。

使用独立探针做实机联调。在 `host_app` 目录执行，按枚举结果替换 `COM15`。

```powershell
New-Item -ItemType Directory -Force ../tmp | Out-Null
python -m electronic_load_gui.devices.drpd --list
python -m electronic_load_gui.devices.drpd COM15 --wire-log ../tmp/drpd-cdc-identity.jsonl
python -m electronic_load_gui.devices.drpd COM15 --capture-seconds 10 --verify-empty --wire-log ../tmp/drpd-cdc-live.jsonl
```

普通探针读取身份、捕获周期和队列数量。`--capture-seconds` 期间接入 USB-PD 电源及被测设备，
探针会启用捕获、分批读取并恢复原先的捕获开关。队列排空后，`--verify-empty` 会实际发送一次
`BUS:CC:CAP:DATA?`，核对错误响应。`--wire-log` 将精确的串口收发字节逐片记录为十六进制，
文件会以新建方式打开。

实机验收还应关闭并重开串口，比较记录边界和内部 `0A`、`0D`、`00` 字节。
当前电子负载可做电压采样验收。接入两台设备和已知参考电压后，可在同一 Qt 进程中验证
DRPD 捕获与电子负载的电压读数。命令中的端口、参考电压和允许误差按实际接线修改。

```powershell
python tests/drpd_dual_hardware.py COM15 COM7 --voltage 5 --tolerance 0.05
```

脚本在电子负载侧读取设备身份、测量和状态。在 DRPD 侧启用捕获，若设备已进入
`PE_SNK_READY`，则发出一次 `GET_SOURCE_CAP` 查询产生 PD 通信。验收要求收到至少两条成功的
PD 捕获记录，其中一条含解码数据，以及三次落在参考电压允许误差内的电压读数。

### CDC 路由与联调记录（2026-11-25）

复刻板为 RP2350，CDC 枚举为 `COM15`（`2E8A:000A`）。原应用的 CDC 可以打开，发送
`2a 49 44 4e 3f 0a`（`*IDN?` 加 LF）后未收到响应。源码原有 SCPI 入口为 USBTMC 和
WinUSB。固件提交 `70b78e5` 在 TinyUSB 任务中收取 CDC 命令并调用同一 SCPI 解释器。
文本响应直接返回 CDC，二进制响应复用固件捕获序列化输出。`BUS:CC:CAP:DATA?` 在 CDC
空队列返回 `2d 32 30 30 0a`。先校验了 2 MiB 闪存备份，再写入并读回校验应用镜像。
联调镜像使用复刻板配置 `CC_OUT_HIGH=19`、`CC_OUT_LOW=20`、`HW_REVISION_DETECT=0`、`SYNC=2`。
固件提交 `0d1aee3` 增加 `DRPD_DUT_CC1_SELECT_LEVEL`，复刻板构建时设为 `0`。
参考板构建默认沿用 GPIO 高电平选择 DUT CC1 的逻辑。

| 验证项 | 结果 |
| --- | --- |
| CDC 文本与捕获控制 | 实机回读身份、捕获开关、10 ns 周期和队列数量 |
| 连续二进制捕获 | 两轮共 323 条，含 50 条 Hard Reset 和 273 条固件事件，二进制块长度和内部字段长度逐条核对。复刻板 CC 极性配置验证及最终排空共读回 10 条普通 PD 报文和 1 条固件事件 |
| 特殊字节与空队列 | 实机载荷含 `00`、`0A`、`0D`，两轮均读到 `-200` |
| 断开与重连 | BOOTSEL 重启使实际 CDC 端口移除，Qt 触发断开清理。应用重启后同一设备重新连接，读回同一身份和周期 |
| 超时恢复 | 实机将计数查询限时 1 ms，触发超时并取消排队查询。重开串口后重新读回 10 ns 周期 |
| 双实机电压采样 | DRPD `COM15` 与电子负载 `COM18` 同时运行。以 6.2 V 为参考，按 ±0.10 V 的联调判据核对，3 次读数落在 6.1825–6.1850 V，同期获取 11 条成功的 PD 捕获记录 |
| 电子负载恒流控制 | 按当前板卡能力完成第一阶段电压采样验收。恒流控制留待后续单独验收 |
| `Source_Capabilities` | GPIO16 极性匹配后实机进入 `PE_SNK_READY`。经 `GET_SOURCE_CAP` 捕获的记录为 1428 字节，含 681 个脉宽计数和 34 字节解码数据。捕获记录的 28 字节消息正文与固件 inquiry 响应一致 |
| 1020 字节示例 | 按计划书附属资料的真实报文字节和字段规格重建。时间戳和脉宽值使用测试数据 |

三条完整的 CDC 原始块保存在 [实机测试样本](tests/fixtures/drpd_cdc_blocks.hex)，涵盖固件事件、
Hard Reset 和 `Source_Capabilities`。本次联调的完整串口日志保存在 `tmp/drpd-cdc-before.jsonl`、
`tmp/drpd-cdc-live.jsonl`、`tmp/drpd-cdc-live-extended.jsonl`、`tmp/drpd-cdc-source-cap.jsonl` 和
`tmp/drpd-cdc-final-empty.jsonl`。双实机电压验收结果保存在 `tmp/drpd-dual-voltage-6p2.jsonl`。

## USB-PD 第二阶段协议基线

协议解析以 USB PD Revision 3.2 Version 1.1（2024-10）为基准。按表 5.1、5.5–5.9、
5.11–5.12 校对 4b5b 有序集，按表 6.1 和 §6.2.1.1 校对 Header，按 §5.6.2 和表 5.10
校对 CRC。交叉核对使用 DRPD Python 的 `message/sop.py`、`header.py` 和 `bmc_sequence.py`，
以及固件的 `lib/proto/pd_sop.cpp` 和 `lib/phy/bmc_encoded_message.cpp`。
[USB-IF 规范版本说明](https://usb.org/euconformity)

- 对有序集优先匹配全部四项。普通 SOP 有唯一的三项匹配时可识别，并保留原字节和匹配项数。
  多候选保留为未知。Hard Reset 以第一阶段 `CaptureRecord.is_hard_reset` 为准。
- Header 使用小端序，位域按 `15 / 14:12 / 11:9 / 8 / 7:6 / 5 / 4:0` 分别读取扩展标志、
  对象数、消息 ID、功率角色或 Cable Plug、规范版本、数据角色或保留位、消息类型。
  Header 线上 `10b` 表示 3.x。普通消息按对象数检查正文长度。
- CRC 使用多项式 `0x04C11DB7`（反射 `0xEDB88320`），初始值和最终异或均为
  `0xFFFFFFFF`，输入和输出均反射。计算范围是 Header 和整个消息正文，接收 CRC 按小端解释。
  测试使用按位参考计算核对实机样本及损坏副本。

[实机样本索引](tests/fixtures/usb_pd_real.json) 引用三个原始 SCPI 块，并标注捕获日期、固件版本及来源。
实机 `Source_Capabilities` 的 Header 为 `0x77A1`，消息 ID 为 3，携带 7 个 PDO。
发送端为 Source / DFP，主机 CRC 基准为 `0x34737FBF`。用来补齐失败或保留位的人工构造输入在测试中标注为 synthetic。

使用 `electronic_load_gui.protocols.usb_pd.parse_capture(record)` 离线解析第一阶段的
`CaptureRecord` 或 `FirmwareEvent`。结果持有原捕获记录，分别记录 Header、正文、消息类型和 CRC 状态。
控制消息提供类型名称，普通数据消息提供正文与小端拆分得到的原始 32 位对象。

### PDO/RDO 语义解析

- `PDMessageResult.pdos` 按报文顺序提供 Source 和 Sink 的 Fixed、Variable、Battery、PPS 及 AVS 能力字段。
  字段使用整数 mV、mA 和 mW。SPR AVS 请求可关联普通能力通告，EPR 请求使用独立的 EPR 能力快照。
- `PDMessageResult.rdo` 提供 Request 对象位置、通用标志和诊断。缺少前序能力时，RDO 状态为
  `context_missing`，报文自身的 `parse_status` 和 `crc_valid` 仍反映基础解析结果。
- 每条捕获链路使用一个 `PDSessionContext`。按捕获顺序调用 `consume()`，从 `analysis.rdo`
  读取与 Source PDO 关联后的 Fixed、Variable、Battery 或 PPS 请求及越界诊断。
  设备断开时调用 `disconnect()`，捕获中断时可调用 `reset()`。

```python
from electronic_load_gui.protocols.usb_pd import PDSessionContext, parse_capture

session = PDSessionContext()
for record in captured_records:
    analysis = session.consume(parse_capture(record))
    if analysis.rdo is not None:
        print(analysis.rdo.object_position, analysis.rdo.status, analysis.rdo.selected_pdo)
```

回放覆盖同一轮实机捕获的七个 Source PDO 和随后发送的 Request。位域依据规范表 6.8–6.25。
样本和验收结果见 [M4 验收报告](DRPD_第二阶段_M4_验收报告.md)。

### VDM/VDO 语义解析

- `PDMessageResult.vdm` 提供 Structured/Unstructured VDM 类型、SVID、命令、响应类型和原始 VDO。
  Discover Identity 解码 ID Header、Cert Stat 和 Product，按产品类型标注后续 VDO。
  Discover SVIDs 读取高半字优先的 SVID 对，Discover Modes 保留按一基位置排列的 Mode VDO。
- `VDMContext` 按 SOP 和 SOP 响应端数据角色关联 Identity、SVIDs、Modes 及 Mode 事件。
  支持 SVID 分页与重试识别。会话关联状态在 `analysis.status`，单帧语义状态在 `result.vdm.status`。
- 捕获中存在前序发现请求时，可从 `analysis.request` 回溯该帧。命令或 SVID 错配的响应保留原始字，
  并给出 `vdm_discovery_response_mismatch`，该响应不会写入发现缓存。
- 可为 `parse_capture(record, vdo_registry=registry)` 传入 `VDORegistry`，按 SVID 注册自定义解码器，
  也可指定 `command` 和 `position`。解码器的返回值放在 `VDOInfo.vendor_fields`，原始字与标准字段始终可读。

```python
from electronic_load_gui.protocols.usb_pd import VDMContext, parse_capture

context = VDMContext()
for record in captured_records:
    result = parse_capture(record)
    analysis = context.consume(result)
    if getattr(result, "vdm", None) is not None:
        print(result.vdm.command_name, result.vdm.status, analysis.mode)
```

每条捕获链路使用独立的 `VDMContext`，设备断开时调用 `disconnect()`，捕获中断时可调用 `reset()`。
DisplayPort 等模式专用字段可通过注册表扩展。GUI 展示按后续里程碑交付。
真实 Identity、SVIDs 和 Modes 回放结果见 [M5 验收报告](DRPD_第二阶段_M5_验收报告.md)。

### Extended Message 与 EPR

- `PDMessageResult.extended_message` 提供单帧 Extended Header、有效数据、填充及结构诊断。未知类型仍可回溯原始字节，CRC 状态由基础解析器独立计算。
- `ExtendedMessageReassembler` 按 SOP、类型和发送端缓存分块。`analysis.message` 提供重组状态、已收与缺失块、有效载荷及来源。`analysis.interrupted` 保留超时、复位或传输替换时留下的部分消息。
- 完整 EPR Source Capabilities 可传入 `PDSessionContext.consume_extended()`。后续 `EPR_Request` 依据通告的位置、回显 PDO 和电压电流范围解释。其他 Extended Message 已支持通用结构和载荷回溯，具体字段可按需求扩展。

```python
from electronic_load_gui.protocols.usb_pd import (
    ExtendedMessageReassembler, PDSessionContext, parse_capture,
)

reassembler = ExtendedMessageReassembler()
power_session = PDSessionContext()
for record in captured_records:
    frame = parse_capture(record)
    power = power_session.consume(frame)
    extended = reassembler.consume(frame)
    if extended is not None:
        power_session.consume_extended(extended)
```

每条捕获链路使用各自的重组器和会话。断开时调用两者的 `disconnect()`。离线回放结束后可用 `expire(timestamp_us)` 取出超过保留时限的部分传输。实机帧、边界和性能数据见 [M6 验收报告](DRPD_第二阶段_M6_验收报告.md)。

### 第二阶段发布与回归

协议公共模型与诊断代码按 M7 冻结，第三阶段界面可以直接读取解析结果。实机、构造和语义支持范围见 [协议支持矩阵](docs/USB_PD_PROTOCOL_SUPPORT_MATRIX.md) 与 [第二阶段最终验收报告](docs/DRPD_第二阶段最终验收报告.md)。

从 `host_app` 目录运行全量回归。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m unittest discover -s tests
```

以下命令运行纯 Python 协议回归与完整压力。实际捕获和构造样本可统一离线回放。

```powershell
'usb_pd', 'pdo', 'rdo', 'pd_session', 'vdm', 'vdo', 'vdm_context', 'extended',
'reassembly', 'extended_context', 'epr', 'protocol_*' | ForEach-Object {
    python -S -m unittest discover -s tests -p "test_$_.py"
    if ($LASTEXITCODE -ne 0) { throw "Protocol test group failed: $_" }
}
$env:M7_FULL_STRESS = '1'
python -S -m unittest discover -s tests -p test_protocol_stress.py -v
$m7StressExit = $LASTEXITCODE
Remove-Item Env:M7_FULL_STRESS
if ($m7StressExit -ne 0) { throw 'Full M7 stress test failed.' }
```

独立运行 `python -S tests/protocol_benchmark.py`，可复跑 M6 等价负载和 M7 补充场景。测试索引与实测口径见 [M7 测试覆盖清单](docs/M7_TEST_COVERAGE.md) 和 [M7 性能报告](docs/M7_PERFORMANCE_REPORT.md)。

## 打包 Windows 程序

```powershell
python -m pip install -e ".[dev]"
pyinstaller --noconfirm --windowed --name ElectronicLoadHost --collect-all pyqtgraph run.py
```

输出位于 `dist\ElectronicLoadHost`。首次发布前应在没有安装 Python 的电脑上测试
串口枚举、连接、曲线和 CSV 保存功能。

## 当前通信调度

- `MEAS:ALL?`：每 100 ms，返回五个逗号分隔数值。
- `STAT?`：每 500 ms，返回状态、故障和设定电流。
- `INP?`：跟随状态查询，用于同步负载开关按钮。
- `SOUR:CHAN?`：固件 0.3.0 及以上每 500 ms 返回 A、B 或 BOTH。
- `FAN:DUTY?`：固件 0.3.0 及以上每 500 ms 返回风扇实际设定占空比。
- `DIAG:DAC:VOLT?`：固件 0.2.0 及以上每 500 ms 返回两路 DAC 设定电压。
- `DIAG:DAC:VOLT <channel>,<V>`：负载关闭时设置 0～2.5 V；带载时总和上限 0.5 V。
- `DIAG:DAC:MODE?`：读取自动或手动 DAC 控制状态（固件 0.3.6 及以上）。
- 所有请求严格串行处理，默认响应超时为 700 ms。

由于当前固件的设置命令成功时没有响应，上位机使用“发送设置 → 查询错误队列 →
读回设置”的方式确认操作结果。如果将来固件统一返回 `OK`/`ERR`，可以进一步简化
协议层。
