# STM32F411 电子负载上位机

基于 PySide6、Qt Serial Port 和 pyqtgraph 的桌面上位机，直接兼容本仓库
固件当前的 USB CDC ASCII 命令协议。

## 已实现功能

- 自动枚举串口，并优先显示 `Electronic Load CDC`/`0483:5740` 设备。
- 使用 `*IDN?` 完成设备身份校验，避免误连普通串口。
- 10 Hz 查询电压、电流、功率和左右散热器温度。
- 查询运行状态、锁存故障、恒流设定值和负载输入状态。
- 设置 0～5 A 恒流值，控制负载 ON/OFF，清除故障和设备复位。
- 设置命令后读取 `SYST:ERR?`，再读回实际值确认控制结果。
- 实时电气参数和温度曲线，默认显示最近 60 秒。
- CSV 采集记录和可滚动的原始通信日志。
- 串口断开、命令超时、响应格式错误提示。

上位机只负责操作和显示，过流、过压、过功率、过温等安全保护仍由 MCU
固件负责，不能用上位机逻辑替代硬件和固件保护。

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
- 所有请求严格串行处理，默认响应超时为 700 ms。

由于当前固件的设置命令成功时没有响应，上位机使用“发送设置 → 查询错误队列 →
读回设置”的方式确认操作结果。如果将来固件统一返回 `OK`/`ERR`，可以进一步简化
协议层。
