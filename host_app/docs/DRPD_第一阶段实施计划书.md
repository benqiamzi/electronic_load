# 电子负载与 USB-PD 综合测试平台

## 第一阶段实施计划书：DRPD 通信层与捕获记录解析

  ------------------------------------------------------------------------------------
  文档属性                            内容
  ----------------------------------- ------------------------------------------------
  项目名称                            电子负载与 USB-PD 综合测试平台

  阶段                                第一阶段：DRPD 通信层与捕获记录解析

  版本                                V1.0

  上位机技术栈                        Python、PySide6

  硬件接口                            USB CDC

  协议基线                            DRPD 原版 SCPI、definite-length Binary
                                      Block、CaptureRecord

  阶段目标                            独立完成 DRPD
                                      数据收发和捕获记录解析，不影响现有电子负载功能
  ------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 1. 项目背景与目标

### 1.1 项目背景

现有上位机已经具备电子负载设备的串口通信、SCPI
命令队列、测量数据读取和图形界面。下一步计划接入基于 DRPD 开源项目复刻的
USB-PD 分析硬件。

本阶段采用 DRPD 原版固件的数据格式，不设计新的私有数据帧。上位机通过 USB
CDC 收发原始字节，处理原版 SCPI 命令、文本响应、二进制块和捕获记录。

### 1.2 本阶段目标

1.  建立独立的 DRPD USB CDC 原始字节传输模块。
2.  实现原版 SCPI 文本命令和文本响应处理。
3.  实现 `#<N><length><payload><LF>` 二进制块解析。
4.  实现 CaptureRecord 小端数据结构解析。
5.  实现捕获控制、捕获数量查询和捕获记录读取。
6.  建立独立单元测试及真实硬件联调流程。
7.  为下一阶段 USB-PD 消息解析提供稳定、完整的捕获数据接口。

### 1.3 阶段完成后的能力

上位机应能够连接 DRPD
复刻板、查询捕获周期和队列数量、读取捕获记录，并正确解析时间戳、解码结果、SOP、脉宽数组和解码数据。程序应能识别
Hard
Reset、固件事件和解码失败记录，并在超时、断连或异常数据情况下稳定运行。

------------------------------------------------------------------------

## 2. 协议依据与关键前置条件

### 2.1 原版 SCPI 命令

以下命令来自项目提供的《DrPD_USB数据格式.md》。

  功能           SCPI 命令                 响应
  -------------- ------------------------- ---------------------------------
  开启捕获       `BUS:CC:CAP:EN ON`        写命令
  关闭捕获       `BUS:CC:CAP:EN OFF`       写命令
  查询捕获周期   `BUS:CC:CAP:CYCLETIME?`   纳秒数文本
  查询捕获数量   `BUS:CC:CAP:COUNT?`       十进制文本
  读取队首记录   `BUS:CC:CAP:DATA?`        二进制块
  空队列读取     `BUS:CC:CAP:DATA?`        资料记载为 `-200`，需在实机确认

捕获周期必须从设备查询，不得将默认示例值 10 ns 写死在程序中。

### 2.2 USB CDC 路由验证：第一项阻塞任务

**重要：** 用户提供的原版数据格式资料明确说明了 USBTMC 和 WinUSB 两种
USB 传输封装，没有明确记载 USB CDC 的 SCPI 路由。因此，本计划将"CDC
直接承载原版 SCPI 字节流"作为目标方案，但必须先检查复刻固件。

目标约定如下：

-   主机通过 CDC 发送 ASCII SCPI 命令，以 LF 结束。
-   固件将 CDC 收到的命令交给原版 SCPI Interpreter。
-   文本查询返回原版 SCPI 文本响应。
-   捕获查询直接返回原版 definite-length binary block。
-   二进制块后保留 LF 终止符。
-   不增加 WinUSB 的 `WU` 12 字节帧头。
-   不增加私有 Tag、私有长度头或额外数据封装。
-   CaptureRecord 的内部字段、偏移和含义保持原版定义。

必须检查：

1.  固件 CDC 接收路径是否接入原版 SCPI Interpreter。
2.  文本响应是否经过 CDC 正确发送。
3.  二进制响应是否以原始字节发送，而非作为字符串处理。
4.  发送路径是否自动添加、删除或转义字节。
5.  Payload 中包含 `0x0A`、`0x0D`、`0x00` 时是否仍保持原样。

如果固件当前只有 USBTMC/WinUSB 路由，则需要先增加一个薄的 CDC
传输适配层。适配层只负责字节收发和 SCPI
路由，不修改原版命令语义、二进制块格式和 CaptureRecord 序列化方式。

在这项验证通过前，不应假设仅修改上位机就能完成 CDC 通信。

### 2.3 与现有上位机的兼容约束

现有电子负载模块保持不变：

-   保留现有 `SerialTransport`、`ProtocolClient` 和
    `ElectronicLoadDevice`。
-   DRPD 使用独立 Transport、ProtocolClient 和捕获客户端。
-   不把 DRPD 二进制数据交给现有按 CR/LF 拆分的串口接收逻辑。
-   不共享两台设备的串口接收缓冲区、请求队列或响应解析器。
-   本阶段不重构 MainWindow，不改变电子负载原有功能。

现有电子负载串口接收逻辑面向文本行，不能直接用于 DRPD 二进制块接收。DRPD
必须采用原始 `bytes` 接收方式。

------------------------------------------------------------------------

## 3. 本阶段范围

### 3.1 本阶段包含

  编号    工作项                 内容
  ------- ---------------------- -----------------------------------
  S1-01   CDC 路由验证           确认固件 CDC 支持原版 SCPI 字节流
  S1-02   Raw CDC Transport      串口打开、关闭、原始字节收发
  S1-03   SCPI Protocol Client   请求队列、文本和二进制响应分发
  S1-04   Binary Block Parser    增量解析 definite-length block
  S1-05   CaptureRecord Parser   原版捕获记录小端解析
  S1-06   Capture Client         捕获控制、数量查询、记录读取
  S1-07   自动化测试             单元测试和异常输入测试
  S1-08   硬件联调               使用 DRPD 复刻板验证真实收发

### 3.2 本阶段不包含

以下内容放到后续阶段：

-   PD Header、PDO、RDO、VDO 语义解析。
-   PD CRC32 业务校验及错误展示。
-   PD 消息类型和协商状态机。
-   BMC/4b5b 软件解码。
-   脉宽时钟质量分析和波形可视化。
-   综合测试 GUI、自动化测试流程。
-   两个设备的时钟同步。
-   SQLite 测试会话、历史回放和报告生成。

本阶段必须保留完整的原始 PD 数据、脉宽数组和解码结果，不能因为暂时不做
PD 语义解析而丢弃字段。

------------------------------------------------------------------------

## 4. 原版数据格式规范

### 4.1 SCPI Binary Block

原版捕获响应格式：

``` text
#<N><十进制数据长度><Payload><LF>
```

例如 Payload 为 1020 字节：

``` text
#41020
[1020 字节二进制 Payload]
0A
```

接收步骤：

1.  读取并验证 `#`。
2.  读取一个 ASCII 数字，得到长度字段位数 N。
3.  精确读取 N 个 ASCII 数字。
4.  将长度字段转换为 Payload 字节数。
5.  精确读取指定长度的 Payload。
6.  读取并验证末尾 LF。
7.  将 Payload 交给 CaptureRecord Parser。

**禁止使用 `readLine()` 读取整个二进制响应。** Payload 本身可能包含
LF、CR、NUL 或任意字节值。

第一版只支持资料定义的 definite-length block（N 为 1～9）。遇到 `#0`
不定长块应明确报告不支持，不得猜测结束位置。

### 4.2 CaptureRecord 数据区

所有偏移均相对于 Payload 起点，多字节整数均为小端序。

       偏移    长度 类型          字段
  --------- ------- ------------- ---------------------------
          0       8 uint64        起始时间戳，µs
          8       8 uint64        结束时间戳，µs
         16       4 uint32        解码结果或事件标记
         20       4 byte\[4\]     SOP 四个 5-bit 有序集符号
         24       4 uint32        脉宽条目数 N
         28   2 × N uint16\[N\]   脉宽数组
    28 + 2N       4 uint32        解码数据长度 M
    32 + 2N       M uint8\[M\]    解码数据

总长度：

``` text
payload_length = 32 + 2 * N + M
```

解析器必须验证固定字段、脉宽数组、M 字段和解码数据均在 Payload
边界内，最终计算长度必须与实际 Payload 长度一致。不得根据不可信的 N/M
无限制分配内存。

### 4.3 解码结果枚举

            数值 原版含义                                本阶段处理
  -------------- --------------------------------------- ----------------------
             `0` 解码成功                                保留并标记成功
             `1` Invalid K-code                          保留失败记录
             `2` CRC 错误                                保留失败记录
             `3` 解码超时                                保留失败记录
             `4` Runt Pulse；原版前端命名为 INCOMPLETE   保留原始数值
             `5` Incomplete                              保留原始数值
    `0xFFFFFFFF` 固件事件                                按事件结构解析
            其他 未知或未来扩展值                        保留原始数值，不丢弃

### 4.4 特殊记录

**Hard Reset**

-   `result = 0`
-   SOP 为 `07 07 07 19`
-   `M = 0`
-   只有复位有序集，没有 PD Header 和 CRC。

应识别为特殊捕获记录，不得因 `M = 0` 将其判定为普通空数据错误。

**固件事件**

-   起始时间戳和结束时间戳相同。
-   SOP 四字节全零。
-   `N = 0`。
-   `result = 0xFFFFFFFF`。
-   数据区前四字节为 `uint32` 事件编号。
-   剩余字节为 UTF-8 事件文本。

事件文本应同时保留原始字节。若 UTF-8 解码失败，不得丢弃事件记录。

**解码失败记录**

解码失败的记录可能只包含部分数据。即使 M 非零，也不能强制将其视为完整 PD
报文。本阶段只保留原始数据和解码结果。

### 4.5 原版实测样本

提供的 Source_Capabilities 样本：

  字段                          值
  ---------------- ---------------
  SOP                `18 18 18 11`
  N                            483
  M                             22
  Payload 总长度        1020 bytes

22 字节数据由 2 字节 PD Header、4 个 PDO（16 字节）和 4 字节 CRC32
组成。该样本用于验证二进制块长度、字段偏移、字节顺序和原始数据完整性。PDO
语义解析留到后续阶段。

------------------------------------------------------------------------

## 5. 软件架构与目录规划

### 5.1 建议目录

``` text
host_app/
└── electronic_load_gui/
    ├── devices/
    │   └── drpd/
    │       ├── __init__.py
    │       ├── transport.py
    │       ├── protocol_client.py
    │       ├── binary_block.py
    │       ├── capture_record.py
    │       └── capture_client.py
    │
    └── tests/
        ├── test_drpd_transport.py
        ├── test_drpd_protocol_client.py
        ├── test_drpd_binary_block.py
        ├── test_drpd_capture_record.py
        └── test_drpd_capture_client.py
```

若现有仓库测试目录位于其他位置，应遵循当前仓库约定，不必为 DRPD
另建一套测试组织方式。

### 5.2 模块职责

  ----------------------------------------------------------------------------------------
  文件                    职责                                     不负责
  ----------------------- ---------------------------------------- -----------------------
  `transport.py`          CDC 串口打开、关闭、原始字节收发         SCPI 语义、记录解析

  `protocol_client.py`    请求队列、文本响应、请求超时、响应分发   PD 消息解码

  `binary_block.py`       `#N + Length + Payload + LF` 增量解析    PD 字段解释

  `capture_record.py`     CaptureRecord 小端解析、特殊记录识别     PDO/RDO 语义解析

  `capture_client.py`     捕获控制、周期查询、队列读取             GUI 展示和数据库
  ----------------------------------------------------------------------------------------

### 5.3 数据流

``` text
USB CDC
   │
   ▼
DrpdTransport
   │ raw bytes
   ▼
DrpdProtocolClient
   ├── SCPI text response
   │
   └── binary response
          │
          ▼
    BinaryBlockParser
          │ Payload
          ▼
    CaptureRecordParser
          │
          ▼
    CaptureRecord / FirmwareEvent
          │
          ▼
    CaptureClient signals / callbacks
          │
          ▼
    后续 USB-PD 解码模块
```

### 5.4 与电子负载模块隔离

``` text
Application / Device Manager
       │
       ├── ElectronicLoadDevice
       │      ├── 原有 SerialTransport
       │      └── 原有 ProtocolClient
       │
       └── DRPDDevice（本阶段逐步建立）
              ├── DrpdTransport
              ├── DrpdProtocolClient
              └── CaptureClient
```

两套设备不共享串口接收缓冲区、响应解析器或请求队列。

------------------------------------------------------------------------

## 6. 模块接口设计

### 6.1 DrpdTransport

基于现有 PySide6 `QSerialPort` 技术栈实现，建议接口：

``` python
class DrpdTransport(QObject):
    opened = Signal(str)
    closed = Signal()
    bytes_received = Signal(bytes)
    error_occurred = Signal(str)

    def available_ports(self) -> list:
        ...

    def open(self, port_name: str, baud_rate: int = 115200) -> bool:
        ...

    def close(self) -> None:
        ...

    def write_bytes(self, data: bytes) -> bool:
        ...

    @property
    def is_open(self) -> bool:
        ...
```

实施要求：

-   接收回调只读取原始字节，不做 ASCII 解码和换行拆分。
-   Payload 中出现 `0x0A` 或 `0x0D` 时不得分割。
-   写入接口接收 `bytes`，SCPI 命令由上层编码为 ASCII 并追加 LF。
-   关闭或异常断开时清空未完成接收数据。
-   连接错误、资源错误和设备移除应向上层发出信号。
-   日志只记录长度和有限长度的十六进制预览，不将大块二进制完整转为字符串。
-   CDC 波特率应可配置。USB CDC 不等同于传统 UART
    波特率，默认值以固件和驱动联调结果为准。

### 6.2 DrpdProtocolClient

建议支持：

``` python
command(command: str, ...)
query_text(command: str, callback, ...)
query_binary(command: str, callback, ...)
clear()
```

请求对象至少包含命令、响应类型、成功回调、错误回调、超时时间和可选去重键。

**请求串行化原则：** 原版 CDC/SCPI 字节流没有 WinUSB
Tag，因此同一设备任意时刻只允许一个未完成的查询事务。请求队列必须保证响应与当前请求一一对应。

实施要求：

-   `command()` 不等待普通文本响应。
-   `query_text()` 使用文本行解析。
-   `query_binary()` 使用 BinaryBlockParser。
-   捕获队列为空时的 `-200`
    应作为设备错误响应处理，不能一直等待二进制块。
-   超时后清理当前事务并进入明确恢复流程。
-   设备断开后，当前请求和排队请求均须结束并通知调用方。
-   不得将前一事务的迟到数据误分配给下一事务。

### 6.3 BinaryBlockParser

建议实现为不依赖 Qt 的纯 Python 增量解析器：

``` python
class BinaryBlockParser:
    def feed(self, data: bytes) -> list[bytes]:
        ...

    def reset(self) -> None:
        ...
```

解析状态：

``` text
WAIT_MARKER
    │ '#'
    ▼
READ_LENGTH_DIGITS
    │ N
    ▼
READ_PAYLOAD_LENGTH
    │ Length
    ▼
READ_PAYLOAD
    │ 精确 Length 字节
    ▼
READ_TERMINATOR
    │ LF
    ▼
COMPLETE
```

必须处理：非法起始符、非法 N、非数字长度、头部不完整、Payload 不完整、LF
缺失、超长 Payload、设备断开和设备错误文本。

最大 Payload
长度应可配置，具体上限根据固件捕获记录最大尺寸确定，不将未经验证的值当成协议事实。

### 6.4 CaptureRecordParser

建议实现为纯 Python 解析器：

``` python
class CaptureRecordParser:
    def parse(self, payload: bytes, cycle_time_ns: float):
        ...
```

建议数据模型：

``` python
@dataclass(frozen=True)
class CaptureRecord:
    start_timestamp_us: int
    end_timestamp_us: int
    decode_result: int
    sop_bytes: bytes
    pulse_count: int
    pulse_widths: tuple[int, ...]
    data_length: int
    decoded_data: bytes
    raw_payload: bytes
    cycle_time_ns: float
```

固件事件单独建模：

``` python
@dataclass(frozen=True)
class FirmwareEvent:
    timestamp_us: int
    event_type: int
    event_text: str
    event_text_bytes: bytes
    raw_payload: bytes
```

解析器返回 `CaptureRecord | FirmwareEvent`。

实施要求：

-   所有整数使用明确的小端解析。
-   保存完整 `raw_payload`。
-   保存完整 `decoded_data`，不提前剥离 Header 或 CRC。
-   保存原始 `decode_result` 数值。
-   对未知枚举值保持兼容。
-   识别 Hard Reset 和固件事件。
-   解码失败的部分数据必须保留。
-   不强制将 `decoded_data` 解析为 PD 报文。

### 6.5 CaptureClient

建议提供：

``` python
start_capture()
stop_capture()
get_cycle_time()
get_capture_count()
fetch_next_capture()
drain_capture_queue()
```

对应原版命令：

-   `start_capture()`：`BUS:CC:CAP:EN ON`
-   `stop_capture()`：`BUS:CC:CAP:EN OFF`
-   `get_cycle_time()`：`BUS:CC:CAP:CYCLETIME?`
-   `get_capture_count()`：`BUS:CC:CAP:COUNT?`
-   `fetch_next_capture()`：`BUS:CC:CAP:DATA?`
-   `drain_capture_queue()`：按队列数量读取现有记录，直到队列排空或达到单轮处理上限。

建议提供
`capture_received`、`capture_count_changed`、`capture_state_changed` 和
`error_occurred`
信号。轮询间隔、单轮最大读取数量和超时均应可配置。不得在 GUI
主线程执行阻塞式循环读取。

------------------------------------------------------------------------

## 7. 详细实施步骤与里程碑

### M0：CDC 路由与协议验证

**目标：确认 CDC 固件路径支持原版 SCPI 字节流。**

任务：

1.  检查固件 CDC 接收入口。
2.  检查 SCPI 命令输入路由。
3.  检查文本响应输出路由。
4.  检查二进制响应输出路由。
5.  使用串口终端或临时测试程序发送已知 SCPI 查询。
6.  使用捕获查询验证二进制块是否逐字节一致。

交付物：CDC
路由验证记录、设备端口信息、文本收发日志、二进制响应原始十六进制记录。

验收：CDC 能接收原版 SCPI 命令，返回原版文本响应和原版二进制块；Payload
未被字符串处理或其他封装修改。

若未通过，暂停上位机后续集成，先完成固件 CDC 适配。

### M1：实现 DrpdTransport

任务：

1.  新建 `devices/drpd/transport.py`。
2.  实现串口枚举、打开、关闭和状态管理。
3.  实现原始字节发送和接收。
4.  实现错误处理、断连清理和调试日志。

验收：能连接 DRPD；任意字节序列可完整收发；接收数据不按 CR/LF
分割；分片数据可交给上层；断连后状态和缓冲区正确。

### M2：实现 BinaryBlockParser

任务：

1.  新建 `devices/drpd/binary_block.py`。
2.  实现增量解析状态机。
3.  实现长度字段解析和 Payload 精确读取。
4.  实现 LF 终止符校验。
5.  实现长度上限和异常处理。

验收：能解析 `#41020`；Payload 中含 `0x0A`、`0x0D`、`0x00`
时不截断；任意位置分片输入均能正确解析；不完整数据不会提前成功。

### M3：实现 DrpdProtocolClient

任务：

1.  定义 SCPI 请求对象。
2.  实现单请求在途的串行队列。
3.  实现文本响应解析。
4.  实现二进制块响应解析。
5.  实现命令超时、错误回调和断连清理。
6.  实现 `-200` 设备错误识别。

验收：连续查询不发生响应错配；文本和二进制响应走不同解析路径；超时、断连和设备错误有明确结果；迟到数据不会误分配给下一事务。

### M4：实现 CaptureRecordParser

任务：

1.  定义 CaptureRecord 和 FirmwareEvent。
2.  解析时间戳、解码结果和 SOP。
3.  解析 N 和脉宽数组。
4.  解析 M 和解码数据。
5.  识别固件事件和 Hard Reset。
6.  保留失败记录及原始 Payload。

验收：正确解析文档中的 1020
字节样本；N、M、字段偏移和字节顺序正确；事件文本和事件编号正确；Hard
Reset 不被误判为空记录；非法长度被拒绝。

### M5：实现 CaptureClient

任务：

1.  实现开启和关闭捕获。
2.  实现捕获周期查询。
3.  实现队列数量查询。
4.  实现读取单条记录。
5.  实现批量排空和单轮处理上限。
6.  将记录通过信号或回调交给上层。

验收：按原版命令工作；捕获周期来自设备查询；多条记录可连续读取；队列为空时正确结束；读取过程不阻塞
GUI 主线程。

### M6：真实硬件联调与回归

任务：

1.  连接 DRPD 复刻板。
2.  验证文本命令和捕获周期。
3.  验证捕获数量。
4.  开启捕获并产生实际 PD 通信。
5.  连续读取多条记录。
6.  验证断连、重连和异常响应。
7.  同时连接电子负载，验证原有功能。

验收：捕获数据与固件端数据一致；多条记录连续接收；Payload 不因 LF
截断；电子负载原有连接、测量和控制功能正常。

------------------------------------------------------------------------

## 8. 测试计划

### 8.1 Transport 测试

  编号      测试内容                   预期结果
  --------- -------------------------- ------------------
  T-TR-01   打开有效串口               状态变为已连接
  T-TR-02   打开不存在的串口           返回明确错误
  T-TR-03   发送 ASCII 命令            字节内容正确
  T-TR-04   接收包含 LF 的二进制数据   原样交付，不拆行
  T-TR-05   接收包含 CR 的二进制数据   原样交付，不拆行
  T-TR-06   分多次接收同一数据         上层可正确拼接
  T-TR-07   设备拔出                   触发断连和清理
  T-TR-08   重新连接                   可以重新通信

### 8.2 Binary Block 测试

  编号      测试内容                    预期结果
  --------- --------------------------- --------------------
  T-BB-01   解析 `#41020` 头            长度为 1020
  T-BB-02   Payload 一次性到达          返回完整 Payload
  T-BB-03   头部分次到达                正确等待
  T-BB-04   Payload 分片到达            精确累计长度
  T-BB-05   Payload 含 `0x0A`           不提前结束
  T-BB-06   Payload 含 `0x0D`、`0x00`   数据不变
  T-BB-07   Payload 不完整              不返回成功
  T-BB-08   末尾不是 LF                 报告格式错误
  T-BB-09   N 非法                      报告格式错误
  T-BB-10   Length 非法                 报告格式错误
  T-BB-11   Payload 超过上限            拒绝并清理状态
  T-BB-12   收到 `-200`                 事务层识别设备错误

### 8.3 CaptureRecord 测试

  编号      测试内容                        预期结果
  --------- ------------------------------- --------------------------
  T-CR-01   解析 Source_Capabilities 样本   N=483、M=22、总长度 1020
  T-CR-02   解析 uint64 时间戳              小端值正确
  T-CR-03   解析 SOP                        四字节顺序正确
  T-CR-04   解析 uint16 脉宽数组            数量和值正确
  T-CR-05   转换脉宽时间                    每项乘以实际 cycle time
  T-CR-06   解析解码成功记录                result=0
  T-CR-07   解析解码失败记录                保留部分 decoded_data
  T-CR-08   解析 Hard Reset                 正确识别 SOP 和 M=0
  T-CR-09   解析固件事件                    事件编号和文本正确
  T-CR-10   解析未知 result                 保留原始数值
  T-CR-11   N 越过 Payload 边界             拒绝记录
  T-CR-12   M 越过 Payload 边界             拒绝记录
  T-CR-13   Payload 长度不匹配              报告格式错误
  T-CR-14   UTF-8 文本非法                  保留原始字节并记录异常

### 8.4 ProtocolClient 测试

  编号      测试内容             预期结果
  --------- -------------------- ------------------------
  T-PC-01   连续提交多个查询     串行执行
  T-PC-02   文本查询响应         分配给当前请求
  T-PC-03   二进制查询响应       交给 BinaryBlockParser
  T-PC-04   无响应命令           不等待文本响应
  T-PC-05   请求超时             调用错误回调
  T-PC-06   设备断开             清理当前和排队请求
  T-PC-07   捕获队列为空         正确识别 `-200`
  T-PC-08   超时后收到迟到数据   不误分配给下一请求

### 8.5 真实硬件测试

至少覆盖：

1.  上电后 CDC 端口识别。
2.  原版 SCPI 文本命令收发。
3.  `BUS:CC:CAP:CYCLETIME?` 查询。
4.  `BUS:CC:CAP:COUNT?` 查询。
5.  开启捕获并产生真实 PD 通信。
6.  读取 `BUS:CC:CAP:DATA?`。
7.  连续读取多条捕获记录。
8.  捕获队列为空时读取。
9.  断开后重新连接。
10. 验证 Payload 特殊字节完整性。
11. 同时连接电子负载并执行原有测量和控制。

------------------------------------------------------------------------

## 9. 进度安排

以下为单人开发建议排期，实际工期取决于 CDC 固件路由是否已经实现。

  里程碑   工作内容                 预计时间 交付结果
  -------- --------------------- ----------- ------------------
  M0       CDC 路由与协议验证      0.5～1 天 CDC 验证记录
  M1       DrpdTransport           0.5～1 天 原始字节收发模块
  M2       BinaryBlockParser       0.5～1 天 二进制块解析器
  M3       DrpdProtocolClient           1 天 SCPI 请求队列
  M4       CaptureRecordParser     0.5～1 天 捕获记录解析器
  M5       CaptureClient           0.5～1 天 捕获控制与读取
  M6       测试和硬件联调            1～2 天 测试报告

建议总计约 4.5～7 个工作日。若固件尚未支持 CDC 到 SCPI
的路由，应另行评估固件适配时间。

每个里程碑完成后，应提交对应代码、补充单元测试、记录测试结果，并确认现有电子负载测试通过后再进入下一项。

建议开发分支：

``` text
feature/drpd-transport
```

每完成一个模块进行一次小范围提交，避免把通信、解析和 UI
改动混在同一个提交中。

------------------------------------------------------------------------

## 10. 风险分析与处理措施

  ---------------------------------------------------------------------------------
  风险                    影响                     处理措施
  ----------------------- ------------------------ --------------------------------
  固件未实现 CDC SCPI     上位机无法直接通信       先检查固件，必要时增加薄适配层
  路由                                             

  复用现有按行串口接收    二进制 Payload 被截断    DRPD 使用独立 raw bytes
                                                   Transport

  将二进制响应按 LF 结束  Payload 内 LF            按长度字段精确读取
                          导致提前结束             

  CDC 分片或粘连          解析不完整或错位         增量状态机和请求串行化

  响应没有 Tag            多请求响应错配           单设备单请求在途

  捕获队列为空            查询返回错误而非数据块   识别 `-200` 并结束读取

  N/M 字段异常            越界或内存异常           长度校验和 Payload 上限

  解码失败记录不完整      丢失诊断信息             完整保留原始字段

  设备拔出                请求永久挂起             断连时终止事务并清理状态

  捕获速率高于读取速率    队列积压                 监测数量、批量排空并记录积压

  影响电子负载功能        原项目回归失败           两套设备模块隔离并执行回归测试
  ---------------------------------------------------------------------------------

------------------------------------------------------------------------

## 11. 阶段验收标准

### 11.1 通信层

-   [ ] CDC 传输路由已经验证。
-   [ ] DRPD 串口可正常打开和关闭。
-   [ ] 原始字节收发正确。
-   [ ] 接收过程不按 LF/CR 拆分二进制数据。
-   [ ] 断开和重新连接处理正确。

### 11.2 SCPI 与二进制块

-   [ ] 能发送原版捕获控制命令。
-   [ ] 能查询捕获周期。
-   [ ] 能查询捕获数量。
-   [ ] 能读取原版 definite-length binary block。
-   [ ] 能正确解析 `#41020` 样本。
-   [ ] Payload 特殊字节不会导致截断。
-   [ ] 能正确处理 `-200` 和超时。

### 11.3 CaptureRecord

-   [ ] 能解析起始和结束时间戳。
-   [ ] 能解析解码结果和 SOP。
-   [ ] 能解析 N 和脉宽数组。
-   [ ] 能解析 M 和 decoded_data。
-   [ ] 能识别 Hard Reset。
-   [ ] 能识别固件事件。
-   [ ] 能保留解码失败记录。
-   [ ] 能拒绝长度不合法的数据。
-   [ ] 能保留完整 raw_payload。

### 11.4 稳定性与兼容性

-   [ ] 单元测试全部通过。
-   [ ] 真实硬件连续捕获测试通过。
-   [ ] 断连、超时和重连测试通过。
-   [ ] 现有电子负载连接、测量和控制功能通过回归测试。
-   [ ] DRPD 模块不依赖电子负载的串口接收解析逻辑。

------------------------------------------------------------------------

## 12. 阶段交付物

  编号   交付物                 内容
  ------ ---------------------- ----------------------------------
  D1     CDC 路由验证记录       固件 CDC 到 SCPI 的验证结果
  D2     DRPD Transport         原始 USB CDC 字节收发模块
  D3     SCPI Protocol Client   串行事务和响应管理
  D4     BinaryBlockParser      原版二进制块解析器
  D5     CaptureRecord Parser   原版捕获记录解析器
  D6     CaptureClient          捕获控制、查询和读取
  D7     自动化测试             通信、二进制块、记录和队列测试
  D8     硬件联调报告           实际捕获数据及异常测试结果
  D9     开发说明               模块接口、运行方式和后续接入说明

------------------------------------------------------------------------

## 13. 后续阶段衔接

第一阶段只负责将固件输出转换为可靠、结构化的捕获记录。第二阶段直接使用本阶段数据模型开展
USB-PD 协议解析，不重新实现 CDC 和二进制块读取。

``` text
CaptureRecord
    ├── start_timestamp_us
    ├── end_timestamp_us
    ├── decode_result
    ├── sop_bytes
    ├── pulse_widths
    ├── cycle_time_ns
    ├── decoded_data
    └── raw_payload
             │
             ▼
       USB-PD Decoder
             ├── SOP 解析
             ├── PD Header
             ├── CRC32
             ├── Control Message
             ├── Data Message
             ├── PDO / RDO / VDO
             └── Extended Message
```

之后再将解析结果接入 PD 报文列表、消息详情、波形关联、SQLite
测试记录和综合测试页面。

**第一阶段核心原则：先确保数据完整、格式正确、通信稳定，再开发上层协议分析。**
