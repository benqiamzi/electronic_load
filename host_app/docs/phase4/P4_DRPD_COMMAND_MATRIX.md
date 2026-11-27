# P4.0 DRPD 命令能力矩阵

复刻固件源码基线为 `0d1aee34a266faaba199fe53c415dce5849201bc`，项目版本 `1.0.0-beta.1`。本地另有 VBUS 比例和引脚改动，板载 `*IDN?` 返回同一版本字符串，具体烧录提交无法由版本字符串判定。2026-11-27 在 COM15 使用项目现有 CDC 客户端逐项回读。表中“源码”表示命令已定义，写入、动作和边界值仍待验证。

固件证据位于 `lib/app/scpi.yaml` 及同目录的 `app_scpi_analog_monitor.cpp`、`app_scpi_bus.cpp`、`app_scpi_vbus.cpp`、`app_scpi_sink.cpp`、`app_scpi_trigger.cpp`。上游功能参考固定到 [T76-org/drpd 53341f4](https://github.com/T76-org/drpd/tree/53341f4adcf958ce069ebf55816cf04fb02ed84c)。

## 设备与捕获

| 命令 | 参数与返回 | 复刻板证据 |
| --- | --- | --- |
| `*IDN?` | 无参数。厂商、产品、序列号、版本 | Dr.PD，1.0.0-beta.1 |
| `BUS:CC:ROLE?` | 无参数。角色、Attach 状态、Source 端口/通道、Sink 端口/通道。端口 DUT/USDS，通道 CC1/CC2 | `SINK,ATTACHED,DUT,CC1,USDS,CC1` |
| `BUS:CC:ROLE:STAT?` | 无参数。UNATTACHED、SOURCE_FOUND、ATTACHED | ATTACHED |
| `BUS:CC:CAP:CYCLETIME?` | 无参数。捕获周期 ns | 10 ns |
| `BUS:CC:CAP:EN?` / `BUS:CC:CAP:EN` | 查询 ON/OFF。写入参数 ON/OFF | 本轮查询 OFF，第三阶段实测开关及读回 |
| `BUS:CC:CAP:COUNT?` | 无参数。设备队列当前记录数 | 本轮空队列为 0，第三阶段观察到峰值 10 |
| `BUS:CC:CAP:DATA?` | 无参数。读取下一条原有二进制记录，空队列返回 `-200`。记录含设备 µs 时间戳、SOP、脉宽和解码字节，或固件事件 | 第三阶段原始捕获及回放已验证 |
| `SYST:ERR?` | 无参数。读取并移除最早一条 SCPI 错误 | 源码，按需读取 |
| 捕获溢出/漏捕总数查询 | 当前 SCPI 命令表无此项。本地源码的捕获环形缓冲配置为 250 条 | 不可用 |

## 模拟测量与 VBUS 保护

| 命令 | 参数与返回 | 复刻板证据 |
| --- | --- | --- |
| `MEAS:ALL?` | 无参数。13 列依次为设备采样时间 µs、VBUS V、IBUS A、DUT CC1/CC2 V、USDS CC1/CC2 V、ADC 参考 V、地参考 V、电流参考 V、累计时间 µs、电荷 mAh、能量 mWh。累计量为绝对值计数。 | `4974734490,5.11,0.00,1.72,0.01,0.01,0.01,2.95,0.01,1.63,4974731430,6,34` |
| `MEAS:ACC?` | 无参数。累计时间 µs、电荷 mAh、能量 mWh | `4974734483,6,34` |
| `MEAS:ACC:RESET` | 无参数。重新开始计时并清零电荷和能量 | 源码 |
| `MEAS:VOLT:VBUS?` / `MEAS:CURR:VBUS?` | 无参数。经校准的 V / A | 5.11 V / 0.00 A |
| `MEAS:CURR:VBUS:RAW?` | 无参数。未校准的 A | 0.00 A |
| `MEAS:VOLT:CC:DUT1?` / `DUT2?` / `USDS1?` / `USDS2?` | 同一 `MEAS:VOLT:CC:` 前缀。无参数。分别返回一路 V | 1.72 / 0.02 / 0.04 / 0.01 V，查询时刻各异 |
| `BUS:VBUS:STAT?` | 无参数。ENABLED、DISABLED、OVP 或 OCP，随后是最近 OVP、OCP 时间戳 µs，无事件为 NONE | `ENABLED,NONE,NONE` |
| `BUS:VBUS:OVPT?` / `BUS:VBUS:OVPT` | 查询 V。设置 0–60 V | 48 V，设置见源码 |
| `BUS:VBUS:OCPT?` / `BUS:VBUS:OCPT` | 查询 A。设置 0–6 A | 5 A，设置见源码 |
| `BUS:VBUS:RESET` | 无参数。复位 VBUS 故障 | 源码 |

## Trigger 与外部 Sync

| 命令 | 参数与返回 | 复刻板证据 |
| --- | --- | --- |
| `TRIG:STAT?` / `TRIG:RESET` | 无参数。状态 IDLE、ARMED、TRIGGERED。Reset 重置控制器 | IDLE，复位见源码 |
| `TRIG:EV:TYPE?` / `TRIG:EV:TYPE` | 查询或设置枚举。OFF、PREAMBLE_START、SOP_START、HEADER_START、DATA_START、MESSAGE_COMPLETE、HARD_RESET_RECEIVED、INVALID_KCODE、CRC_ERROR、TIMEOUT_ERROR、RUNT_PULSE_ERROR、ANY_ERROR | OFF，设置见源码 |
| `TRIG:EV:THRESH?` / `TRIG:EV:THRESH` | 查询或设置 uint32 次数。主机应在发送前校验整数和范围 | 1，设置见源码 |
| `TRIG:EV:SEND?` / `TRIG:EV:SEND` | 查询或设置 ANY、SOURCE、SINK、CABLE。切入 DATA_START 后才有可用于过滤的报文头 | ANY，设置见源码 |
| `TRIG:EV:MSGTYPE:FILT?` / `TRIG:EV:MSGTYPE:FILT` / `TRIG:EV:MSGTYPE:FILT:CLEAR` | 查询空格分隔列表，空行代表无过滤。设置 `slot,CONTROL:n` 或 `slot,DATA:n`，slot 0–7，n 0–31，槽间禁止重复。CLEAR 无参数 | 空行，设置与清除见源码 |
| `TRIG:EV:AUTOREPEAT?` / `TRIG:EV:AUTOREPEAT` | 查询或设置 ON/OFF | OFF，设置见源码 |
| `TRIG:EV:COUNT?` | 无参数。自上次复位起统计的事件次数 | 0 |
| `TRIG:SYNC:MODE?` / `TRIG:SYNC:MODE` | 查询或设置 PULSE_HIGH、PULSE_LOW、TOGGLE、PULL_DOWN | PULSE_HIGH，输出电平和设置验收待测 |
| `TRIG:SYNC:PULSE?` / `TRIG:SYNC:PULSE` | 查询或设置 uint32 µs。脉冲模式使用该值，物理有效范围需台架验证 | 1000 µs，实际脉宽待测 |

## Sink

| 命令 | 参数与返回 | 复刻板证据 |
| --- | --- | --- |
| `SINK:STATUS?` / `SINK:STATUS:ERROR?` | 无参数。策略引擎状态和错误码 | PE_SNK_READY / 0 |
| `SINK:STATUS:PDO?` | 无参数。协商类型及其字段，FIXED 为类型、V、A | `FIXED,5.000000,3.000000` |
| `SINK:STATUS:VOLTAGE?` / `SINK:STATUS:CURRENT?` | 无参数。协商值 mV / mA | 5000 mV / 3000 mA |
| `SINK:PDO:COUNT?` / `SINK:PDO? index` | 返回合并的 Source PDO 数量。索引从 0 开始。类型决定字段，单位 V/A/W，部分响应有尾逗号 | 7 条，索引 1 返回 `FIXED,9.000000,3.000000,` |
| `SINK:PDO index,voltage_mv,current_ma` | 0 基索引，电压 mV，电流 mA。0 mA 让固件请求最大可用电流。实际范围由当前 PDO 和 Sink 状态决定 | 源码，主动请求待硬件条件确认 |
| `SINK:REQUEST:STATUS?` | 无参数。结果、索引、电压 mV、电流 mA。读回须与本次请求及协议完成事件关联 | `ACCEPTED,0,5000,3000` 为已有状态 |
| `SINK:EPR:EN?` / `SINK:CAP:EPR:COUNT?` | 无参数。EPR 配置 ON/OFF 和 Sink EPR 能力槽计数。Source 能力以 `SINK:PDO?` 与捕获为准 | ON / 0 |

互相独立的模拟读数可跨采样时刻变化。`MEAS:ALL?` 使用用于诊断的设备时间戳及模拟快照，源码对 VBUS 和 IBUS 另取当前校准值，不能据此推导各通道严格同步采样。测量值和 Sink 协商值分别存储。
