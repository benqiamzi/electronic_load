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
python -m electronic_load_gui.devices.drpd --list
python -m electronic_load_gui.devices.drpd COM15 --wire-log ../tmp/drpd-cdc-identity.jsonl
python -m electronic_load_gui.devices.drpd COM15 --capture-seconds 10 --verify-empty --wire-log ../tmp/drpd-cdc-live.jsonl
```

普通探针读取身份、捕获周期和队列数量。`--capture-seconds` 期间接入 USB-PD 电源及被测设备，
探针会启用捕获、分批读取并恢复原先的捕获开关。队列排空后，`--verify-empty` 会实际发送一次
`BUS:CC:CAP:DATA?`，核对错误响应。`--wire-log` 将精确的串口收发字节逐片记录为十六进制，
文件会以新建方式打开。

实机验收还应关闭并重开串口，比较记录边界和内部 `0A`、`0D`、`00` 字节。同时接入电子负载时，
在原窗口确认身份、实时测量及低电流设定和输入状态读回。两台设备各自占用一个串口。

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
