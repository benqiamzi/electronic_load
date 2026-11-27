# 电子负载与 USB-PD 综合测试平台

## 第二阶段实施计划书：USB-PD 协议解析引擎

  文档属性       内容
  -------------- ----------------------------------------------------
  项目名称       电子负载与 USB-PD 综合测试平台
  阶段           第二阶段：USB-PD 协议解析引擎设计与实现
  版本           V1.0
  编制依据       《电子负载与 USB-PD 综合测试平台第一阶段验收报告》
  技术栈         Python、PySide6
  输入           第一阶段 `DrpdDevice` / `CaptureClient`
  核心数据类型   `CaptureRecord`、`FirmwareEvent`
  阶段定位       独立、可离线测试的 USB-PD 协议解析模块

------------------------------------------------------------------------

## 1. 项目背景与阶段目标

### 1.1 第一阶段成果

第一阶段已完成 DRPD USB CDC 通信、原版 SCPI
事务、捕获记录解析及双实机联调，验收结论为通过。验收环境包括 RP2350 DRPD
复刻板和 STM32F411 `EL-F411` 电子负载，两台设备通过独立 USB CDC
链路接入同一 Qt 进程。

已验收的软件版本为 `feature/drpd-transport`，提交 `1c201a9`；DRPD 固件为
`1.0.0-beta.1`，CDC 路由提交 `70b78e5`，CC 选路提交
`0d1aee3`。第一阶段上位机 45 项测试和 DRPD 固件 12 项主机端测试通过。

第二阶段不重复实现 USB CDC、SCPI、Binary Block 和 CaptureRecord
解析，直接使用第一阶段已验收的数据接口。

### 1.2 第二阶段目标

建立独立于串口和 GUI 的 USB-PD 协议解析引擎：

1.  SOP 有序集识别和分类。
2.  PD Header 位域解析。
3.  主机侧 CRC32 计算和校验。
4.  控制消息与数据消息分类。
5.  PDO、RDO、VDO 结构解析。
6.  Extended Message 头部解析和分块重组。
7.  短包、未知类型、解码失败和异常数据的保留与诊断。
8.  以第一阶段真实捕获样本建立可重复的协议回归测试。

### 1.3 阶段交付后的能力

将捕获记录转换为结构化 `PDMessageResult` 或独立事件结果，提供 SOP
类型、PD Header 字段、消息类型、消息 ID、角色、对象数量、CRC
状态、PDO/RDO/VDO 字段、Extended Message
分块状态及诊断信息，并始终保留原始数据。

本阶段以解析引擎和测试为交付重点，不以完整协议分析 GUI 为交付目标。

------------------------------------------------------------------------

## 2. 输入契约与第一阶段接口复用

### 2.1 唯一数据入口

从第一阶段 `DrpdDevice` 获取：

``` python
device.capture
```

通过以下接口消费记录：

``` python
capture.capture_received
capture.fetch_next_capture(callback=...)
```

输入类型：

``` python
CaptureRecord | FirmwareEvent
```

队列为空时，单条读取回调收到 `None`。捕获启停和轮询继续由第一阶段
`CaptureClient` 管理。

第二阶段不得直接读取串口、重复解析 SCPI Binary Block，或复制
CaptureRecord 解析逻辑。

### 2.2 CaptureRecord 字段约定

  -------------------------------------------------------------------------------
  字段                    第二阶段用途            约束
  ----------------------- ----------------------- -------------------------------
  `start_timestamp_us`    报文开始时间、排序      DRPD 设备侧时间，单位 µs

  `end_timestamp_us`      报文结束时间            DRPD 设备侧时间，单位 µs

  `sop_bytes`             SOP 识别                保留原始 4 字节

  `decode_result`         固件解码状态            保留原始值，包括未知值

  `decoded_data`          Header、正文和 CRC 解析 完整普通报文通常含 Header 和
                                                  CRC；失败记录可能只有部分字节

  `pulse_widths`          后续波形分析            本阶段不重做 BMC 解码

  `cycle_time_ns`         脉宽计数换算            使用设备查询到的实际周期

  `pulse_widths_ns`       时序诊断参考            由第一阶段提供

  `raw_payload`           原始记录追溯            不得丢弃或覆盖

  `is_hard_reset`         Hard Reset 分支         使用第一阶段已验证属性
  -------------------------------------------------------------------------------

### 2.3 FirmwareEvent 字段约定

`FirmwareEvent` 是独立记录类型，不是 PD 报文。可使用
`timestamp_us`、`event_type`、`event_text`、`event_text_bytes`、`text_encoding_valid`
和 `raw_payload`。事件应输出为独立事件结果，不得尝试将事件文本解释为 PD
Header。

### 2.4 时间基准约束

第一阶段报告明确：DRPD
时间戳是设备侧时间，电子负载测量数据需要单独建立时间基准。因此本阶段只使用
DRPD
设备侧时间戳进行报文排序和设备内时间差计算，不实现跨设备时钟同步，也不将上位机接收时间伪装成硬件采样时间。

------------------------------------------------------------------------

## 3. 实机基准样本与测试数据策略

### 3.1 真实 Source_Capabilities 样本

第一阶段验收报告提供的真实完整捕获记录：

  字段                             实测值
  ----------------------- ---------------
  SCPI 块头                      `#41428`
  CaptureRecord Payload        1428 bytes
  SOP                       `18 18 18 11`
  固件解码结果                        `0`
  脉宽计数数量                        681
  解码数据长度                   34 bytes
  起始时间戳                  32788569 µs
  结束时间戳                  32789980 µs

34 字节 `decoded_data` 由 2 字节 PD Header、28 字节消息正文和 4 字节 CRC
组成。报告记录：28 字节消息正文与同次 `SINK:INQ:RESP?`
返回的数据逐字节一致。

实机解码数据：

``` text
a1 77 2c 91 01 0a 2c d1 02 00 2c c1 03 00 2c b1 04 00
f4 41 06 00 64 32 dc c8 64 32 90 c9 bf 7f 73 34
```

这条样本是 Header、正文长度和 PDO 拆分的首要回归基准。

### 3.2 已提交 CDC 样本

第一阶段仓库中的 `tests/fixtures/drpd_cdc_blocks.hex` 保留三条真实完整
SCPI 块：

  样本                        块长度 用途
  --------------------- ------------ ----------------------------
  固件事件                 152 bytes 验证事件不进入 PD 报文解析
  Hard Reset               288 bytes 验证特殊有序集处理
  Source_Capabilities     1428 bytes 验证普通完整 PD 报文解析

第二阶段应从这些块提取 CaptureRecord，再让解析器测试与串口 Transport
解耦。

**样本注意：** 第一阶段早期计划中的 1020 字节示例是使用真实 PD
报文字节和字段规格重建的测试数据，其时间戳和脉宽为构造数据。第二阶段实机回归以
1428 字节实测记录为准，不得将 1020 字节构造样本标记为实机测量结果。

### 3.3 样本扩充清单

  类别       样本                     用途
  ---------- ------------------------ -----------------------------------
  数据消息   Source_Capabilities      Header、对象数量、PDO
  请求消息   Request                  RDO 与 PDO 关联
  控制消息   Accept、PS_RDY、Reject   控制消息分类
  查询消息   Get_Source_Cap           控制消息识别
  复位       Hard Reset、Soft_Reset   特殊有序集与控制消息区分
  厂商消息   VDM                      SVID、Structured/Unstructured VDM
  扩展消息   完整分块消息             Extended Header 与重组
  错误消息   单字节损坏样本           CRC 校验
  边界样本   短包、截断包、未知类型   异常诊断

没有真实样本的类别可先使用人工构造数据进行单元测试，但必须标记为
`synthetic fixture`，不能作为实机验收证据。

------------------------------------------------------------------------

## 4. 第二阶段软件架构

### 4.1 建议目录

``` text
host_app/
└── electronic_load_gui/
    ├── protocols/
    │   └── usb_pd/
    │       ├── __init__.py
    │       ├── models.py
    │       ├── parser.py
    │       ├── sop.py
    │       ├── header.py
    │       ├── crc.py
    │       ├── message_types.py
    │       ├── control_message.py
    │       ├── data_message.py
    │       ├── pdo.py
    │       ├── rdo.py
    │       ├── vdo.py
    │       ├── extended.py
    │       ├── diagnostics.py
    │       └── reassembly.py
    └── tests/
        └── usb_pd/
            ├── test_sop.py
            ├── test_header.py
            ├── test_crc.py
            ├── test_message_types.py
            ├── test_control_message.py
            ├── test_data_message.py
            ├── test_pdo.py
            ├── test_rdo.py
            ├── test_vdo.py
            ├── test_extended.py
            ├── test_reassembly.py
            ├── test_parser.py
            └── fixtures/
```

若仓库已有统一 `tests/`
组织方式，应沿用现有约定；上述路径表达逻辑分层，不要求为目录形式搬迁原测试。

### 4.2 模块职责

  模块                   职责
  ---------------------- ---------------------------------------------
  `models.py`            定义解析结果、Header、Data Object、诊断对象
  `parser.py`            统一入口和解析流程编排
  `sop.py`               SOP、SOP'、SOP'' 等有序集识别
  `header.py`            PD Header 位域解析
  `crc.py`               主机侧 CRC32 计算和比较
  `message_types.py`     按 SOP、PD Revision 和消息类型分类
  `control_message.py`   控制消息语义解析
  `data_message.py`      数据消息和对象数量校验
  `pdo.py`               PDO 类型及能力字段解析
  `rdo.py`               RDO 字段解析及关联 PDO
  `vdo.py`               VDM、SVID 和 VDO 字段解析
  `extended.py`          Extended Header 和扩展消息字段
  `reassembly.py`        分块扩展消息重组
  `diagnostics.py`       错误码、警告和原始数据诊断

### 4.3 处理流水线

``` text
CaptureRecord / FirmwareEvent
              │
              ▼
          输入分流
        ┌─────┴──────┐
        │            │
 FirmwareEvent  CaptureRecord
        │            │
        ▼            ▼
   事件结果      固件解码状态检查
                     │
             ┌───────┴────────┐
             │                │
        Hard Reset       普通捕获记录
             │                │
             ▼                ▼
       特殊结果对象        SOP 识别
                              │
                              ▼
                         PD Header
                              │
                              ▼
                         长度与边界检查
                              │
                              ▼
                         CRC32 校验
                              │
                              ▼
                         消息类型分类
                              │
                    ┌─────────┴─────────┐
                    │                   │
                Control             Data/Extended
                    │                   │
                    ▼                   ▼
             控制消息解析         PDO/RDO/VDO
                                        │
                                        ▼
                                  Extended 重组
                    │                   │
                    └─────────┬─────────┘
                              ▼
                       PDMessageResult
```

### 4.4 解析器设计原则

1.  纯 Python，不依赖 PySide6、串口和 GUI。
2.  不修改第一阶段 `CaptureRecord` 和原始字节。
3.  每个结果均可关联原始 CaptureRecord。
4.  短包、CRC 错误、未知类型和部分数据都返回诊断结果。
5.  Header 成功不代表正文一定合法，各层独立报告状态。
6.  根据 PD Header 规范版本解释字段，避免混用不同版本定义。
7.  未支持字段保留原始数值和字节，标记 `unsupported` 或 `unknown`。
8.  不发送 SCPI 命令，不控制 DRPD 或电子负载。

------------------------------------------------------------------------

## 5. 核心功能实施方案

### 5.1 SOP 有序集识别

输入为 `record.sop_bytes` 和 `record.is_hard_reset`。

工作内容：

1.  建立原版 SOP 四字节有序集映射表。
2.  支持识别 SOP、SOP'、SOP'' 及项目实际捕获格式中出现的其他有序集。
3.  Hard Reset 优先使用第一阶段已验证的 `is_hard_reset` 属性。
4.  区分普通 PD 消息、Hard Reset 和未知有序集。
5.  保留原始 SOP 字节。

映射表必须依据 DRPD 原版解码定义和 USB-PD
规范核对，并使用实机样本验证。不能只根据报文正文猜测 SOP 类型。

建议输出：

``` python
@dataclass(frozen=True)
class SopInfo:
    raw_bytes: bytes
    name: str
    supported: bool
    is_hard_reset: bool
```

验收：真实 Source_Capabilities 识别正确；Hard Reset
进入特殊分支；未知组合保留原值且不崩溃。

### 5.2 PD Header 解析

解析完整普通报文的前两个字节。位域定义以目标 USB-PD 规范版本为依据。

建议字段：

-   Message Type
-   Data Role
-   Specification Revision
-   Power Role
-   Message ID
-   Number of Data Objects
-   Extended Message 标志

实施要求：

1.  明确 Header 两字节的位序和字节序。
2.  使用位掩码和移位解析，不依赖平台本机字节序。
3.  区分不同 SOP 类别下适用的角色字段。
4.  对保留位和不支持规范版本给出诊断。
5.  检查对象数量与实际正文长度是否一致。
6.  同时保留原始 Header 整数和原始两字节。

建议输出：

``` python
@dataclass(frozen=True)
class PDHeader:
    raw_bytes: bytes
    raw_value: int
    message_type: int
    data_role: int | None
    spec_revision: int
    power_role: int | None
    message_id: int
    num_data_objects: int
    extended: bool
```

验收：真实 Source_Capabilities Header 可解析；对象数量与正文长度匹配；短
Header 返回诊断而不是未处理异常。

### 5.3 CRC32 主机侧校验

第一阶段 `decode_result` 是 DRPD 固件解码结果。第二阶段新增主机 CRC32
结果，二者独立保存：

``` python
firmware_decode_result: int
crc_received: int | None
crc_calculated: int | None
crc_valid: bool | None
```

处理流程：

1.  判断记录是否为完整普通 PD 报文。
2.  检查 Header 和正文长度。
3.  将末尾 CRC 与待校验内容分离。
4.  按目标 USB-PD 规范参数计算 CRC32。
5.  按已确认的字节序解释接收 CRC。
6.  比较计算值和接收值。
7.  分别保存计算值、接收值和比较结果。

开发前必须将 CRC
多项式、初始值、输入/输出反射、最终异或、计算范围和传输字节顺序写入代码注释及测试说明。具体参数以
USB-PD 规范和 DRPD 原版实现交叉核对，不得直接假定通用 CRC32
库的默认参数适用。

测试：真实完整报文与独立参考核对；单字节损坏样本验证错误检测；短包不越界；固件失败记录不伪装成
CRC 通过。

### 5.4 控制消息解析

按 Header 消息类型、SOP 上下文和规范版本识别控制消息。

首批建议覆盖：

-   GoodCRC
-   Accept
-   Reject
-   PS_RDY
-   Get_Source_Cap
-   Get_Sink_Cap
-   Soft_Reset
-   DR_SWAP
-   PR_SWAP
-   VCONN_SWAP
-   WAIT
-   NOT_SUPPORTED（按版本适用性处理）

实施要求：

1.  建立消息类型映射表。
2.  对零数据对象控制消息检查实际长度。
3.  区分 Hard Reset（有序集事件）与 Soft_Reset（PD 控制消息）。
4.  按规范版本处理消息差异。
5.  未支持消息保留类型编号和原始字节。

首批验收至少覆盖 Accept、PS_RDY、Reject、Get_Source_Cap 和
Soft_Reset；其他消息在样本齐备后扩展。

### 5.5 数据消息解析

根据 Header 中的数据对象数量检查正文长度，再按 32-bit Data Object 拆分：

``` text
data_object_bytes = num_data_objects * 4
```

长度不匹配时报告错误，不得越界解析。

首批数据消息：

-   Source_Capabilities
-   Request
-   Sink_Capabilities
-   Vendor_Defined

其他消息按实机样本和目标规范版本扩展。

### 5.6 PDO 解析

Source_Capabilities 是首要实现目标。

需要支持并明确标记：

-   Fixed Supply PDO
-   Battery PDO
-   Variable Supply PDO
-   Augmented PDO（先按实际支持子类型逐步实现，例如 PPS；AVS/EPR
    能力按目标规范版本和样本另行验证）

每个 PDO 解析结果至少包含原始 32-bit 值、PDO
类型、电压字段、电流或功率字段、适用能力标志及保留位/未知字段诊断。

注意：

-   先识别 PDO 类型，再按对应位域解释。
-   不允许将所有 PDO 都按 Fixed PDO 解析。
-   单位应明确，例如 mV、mA、mW。
-   原始 32-bit 值必须保留。
-   超出支持范围的类型标记 `unsupported`，不得猜测数值。

首个验收样本使用真实 28 字节 Source_Capabilities 正文。先完成 Header
与四字节 PDO 对象拆分，再将每个 PDO
字段与规范计算和独立参考结果核对。第一阶段报告没有给出四个 PDO
的完整解码期望值，因此期望值应在开发阶段根据真实字节推导、复核并写入
fixture，不得沿用早期构造示例的 PDO 数值。

### 5.7 RDO 解析

RDO 必须结合其请求的 PDO 类型解释，不能脱离 Source_Capabilities
上下文只按固定结构解析。

首批工作：

1.  解析 Request Data Object 原始 32-bit 值。
2.  根据当前协商上下文或关联的 Source_Capabilities 确定被请求 PDO。
3.  解析适用的 Fixed/Variable、Battery、PPS 等 RDO 字段。
4.  检查对象位置是否超出已知 PDO 数量。
5.  保留原始值及无法关联时的诊断。

缺少 Source_Capabilities 上下文时，仍输出原始 RDO 字段，但将依赖 PDO
的解释标记为 `context_missing`，不能猜测供电能力。

### 5.8 VDO 与 VDM 解析

VDO 结构取决于消息类型、SVID、Structured/Unstructured VDM 和规范版本。

首批实现：

1.  识别 Vendor_Defined 数据消息。
2.  解析 VDM Header。
3.  识别 SVID。
4.  区分 Structured VDM 与 Unstructured VDM。
5.  对已支持 Structured VDM 解析命令类型、对象位置和版本相关字段。
6.  对未知 SVID 或未支持命令保留原始 VDO。

第二阶段不要求覆盖所有厂商私有
VDO。厂商字段应采用可扩展解码器，不应写死在通用 Header 解析器中。

### 5.9 Extended Message 与分块重组

分为单条记录解析和跨记录重组两个层次。

**单条记录解析：**

-   识别 Header 的 Extended 标志。
-   解析 Extended Header。
-   提取扩展数据长度。
-   识别分块标志、Chunk Number 和请求分块字段（按规范版本适用性）。
-   校验当前捕获数据是否满足分块声明长度。

**分块重组：**

-   根据 SOP
    上下文、消息方向/角色、消息类型及规范规定的关联信息建立重组上下文。
-   按 Chunk Number 组织分块。
-   检测缺块、重复块、乱序块和截断块。
-   设置最大重组长度和上下文清理策略。
-   无法完成重组时输出部分数据和诊断，不得静默丢弃。
-   新会话、Soft_Reset 或相关协议状态变化时，按规范清理或重置上下文。

第二阶段先明确支持范围，不以"支持所有 USB-PD Extended
Message"作为无边界承诺。首个交付范围以可取得的实机样本和目标规范版本为准。

------------------------------------------------------------------------

## 6. 统一解析结果模型

### 6.1 设计目标

解析结果同时表达原始捕获记录、固件解码状态、主机解析状态、CRC
状态、消息语义、结构化数据对象和诊断信息。

### 6.2 建议模型

``` python
@dataclass(frozen=True)
class ParseDiagnostic:
    code: str
    severity: str
    message: str
    offset: int | None = None


@dataclass(frozen=True)
class PDMessageResult:
    capture_record: CaptureRecord

    sop_name: str | None
    header: PDHeader | None

    message_category: str
    message_name: str | None

    firmware_decode_result: int
    crc_received: int | None
    crc_calculated: int | None
    crc_valid: bool | None

    data_objects: tuple
    extended_message: object | None

    parse_status: str
    diagnostics: tuple[ParseDiagnostic, ...]

    raw_decoded_data: bytes
```

顶层可返回：

``` python
PDMessageResult | HardResetResult | FirmwareEventResult | ParseFailureResult
```

也可以使用含 `kind` 字段的统一结果模型，但事件、Hard Reset
和普通报文语义必须清晰，不互相伪装。

### 6.3 状态字段约定

  状态                含义
  ------------------- ------------------------------------
  `valid`             当前解析层成功
  `invalid`           已确认违反长度、位域或校验规则
  `partial`           数据不完整，但保留可解析部分
  `unsupported`       格式合法，但当前解析器未实现该类型
  `unknown`           无法识别的类型或枚举
  `context_missing`   解释当前字段需要前序消息上下文

不要用单一 `valid`
布尔值代表所有解析层。Header、CRC、正文和对象解码应分别保留状态。

------------------------------------------------------------------------

## 7. 详细实施步骤与里程碑

### M0：样本整理与协议规则冻结

任务：

1.  从 `tests/fixtures/drpd_cdc_blocks.hex` 提取三条真实 CaptureRecord。
2.  固化真实 Source_Capabilities 的 `decoded_data`。
3.  固化 Hard Reset 和 FirmwareEvent。
4.  记录样本来源、固件版本、捕获日期和 real/synthetic 属性。
5.  明确目标 USB-PD 规范版本。
6.  核对 SOP 映射、Header 位域和 CRC32 参数。
7.  建立测试样本清单。

交付物：实机样本索引、Source_Capabilities 期望结果表、SOP/Header/CRC
规则核对记录。

验收：实机样本可脱离串口独立加载；实机与构造样本有明确标识；Header 和
CRC 规则有规范及测试依据。

### M1：SOP 与 PD Header

任务：实现 `sop.py`、`header.py`、Hard Reset 特殊分支、未知 SOP 和短
Header 诊断，并使用真实 Source_Capabilities 验证。

验收：SOP 分类和 Header 字段正确；对象数量与正文长度匹配；Hard Reset
不进入普通 Header 解析；未知和短包不导致异常。

### M2：CRC32 主机校验

任务：实现 `crc.py`，固化 CRC
参数、字节序和计算范围；用真实完整报文核对；构造单字节损坏样本；分离主机
CRC 与固件 `decode_result`。

验收：真实样本与独立参考一致；单字节损坏能检测；短包不越界；失败记录不被错误标记为
CRC 通过。

### M3：消息分类与控制/数据消息

任务：建立消息类型表、规范版本判断、控制消息解析、数据消息长度校验、未知类型处理和上下文关联接口。

验收：首批控制消息正确分类；Source_Capabilities、Request、VDM
进入正确分支；对象数量与长度不符时有诊断；未知类型保留原始数据。

### M4：PDO 与 RDO

任务：实现 PDO 类型识别；实现 Fixed、Battery、Variable 和目标版本适用的
PPS；评估 AVS/EPR；实现 RDO 解析和 PDO
上下文关联；增加单位换算与原始值保留。

验收：真实 Source_Capabilities Header 和四字节对象拆分正确；支持的 PDO
字段与规范及独立参考一致；Request/RDO 字段正确；缺少上下文时明确报告。

### M5：VDO/VDM

任务：实现 Vendor_Defined 识别、VDM
Header、SVID、Structured/Unstructured 分类及首批通用 Structured VDM
字段。

验收：已标注样本可正确识别；Header、SVID
和命令字段正确；未知厂商字段不会导致数据丢失。

### M6：Extended Message 与分块重组

任务：实现 Extended
Header、扩展长度和分块字段；实现分块缓存、重组上下文、异常诊断和资源上限。

验收：支持范围内的扩展消息可解析和重组；缺块、重复块、截断和超长输入均可诊断；无法重组时保留部分数据。

### M7：统一入口、回归与性能基线

任务：实现 `parser.py` 统一入口；连接 CaptureRecord、FirmwareEvent
和结果模型；加入实机回归；执行全量测试；记录离线解析耗时和内存基线。

验收：解析器不依赖真实串口；实机样本结果稳定可重复；未知数据不会导致未处理异常；第一阶段通信和双设备回归继续通过。

------------------------------------------------------------------------

## 8. 自动化测试计划

### 8.1 SOP 与 Header

  编号       测试内容                          预期结果
  ---------- --------------------------------- ------------------------
  T-SOP-01   真实 Source_Capabilities SOP      类型正确
  T-SOP-02   真实 Hard Reset                   进入特殊分支
  T-SOP-03   未知 SOP                          保留原值并标记 unknown
  T-SOP-04   未知/不完整输入                   返回诊断
  T-HDR-01   真实 Source_Capabilities Header   位域正确
  T-HDR-02   不同 Message ID                   字段正确
  T-HDR-03   不同对象数量                      字段正确
  T-HDR-04   保留位异常                        给出诊断
  T-HDR-05   正文长度与对象数量不符            报告长度错误

### 8.2 CRC

  编号       测试内容                  预期结果
  ---------- ------------------------- --------------------
  T-CRC-01   真实完整报文              与独立参考一致
  T-CRC-02   单字节损坏                CRC 不匹配
  T-CRC-03   CRC 字段缺失              不越界
  T-CRC-04   失败记录部分数据          CRC 标记为不可判定
  T-CRC-05   固件结果与主机 CRC 不同   两项状态独立保留

### 8.3 控制与数据消息

  编号       测试内容              预期结果
  ---------- --------------------- --------------------
  T-MSG-01   Accept                控制消息分类正确
  T-MSG-02   PS_RDY                控制消息分类正确
  T-MSG-03   Reject                控制消息分类正确
  T-MSG-04   Get_Source_Cap        控制消息分类正确
  T-MSG-05   Soft_Reset            控制消息分类正确
  T-MSG-06   Source_Capabilities   数据消息分类正确
  T-MSG-07   Request               数据消息分类正确
  T-MSG-08   未知消息类型          保留类型和原始数据

### 8.4 PDO/RDO/VDO

  编号       测试内容                   预期结果
  ---------- -------------------------- -----------------------------
  T-PDO-01   真实 Source_Capabilities   Header 和对象拆分正确
  T-PDO-02   Fixed PDO                  字段和单位正确
  T-PDO-03   Battery PDO                字段和单位正确
  T-PDO-04   Variable PDO               字段和单位正确
  T-PDO-05   PPS PDO                    支持范围内字段正确
  T-PDO-06   未支持 PDO                 标记 unsupported 并保留原值
  T-RDO-01   Request 样本               原始字段正确
  T-RDO-02   RDO 关联已知 PDO           请求能力解释正确
  T-RDO-03   缺少前序上下文             标记 context_missing
  T-VDO-01   Structured VDM             Header 和 SVID 正确
  T-VDO-02   Unstructured VDM           类型识别正确
  T-VDO-03   未知 SVID                  保留原始 VDO

### 8.5 Extended Message

  编号       测试内容          预期结果
  ---------- ----------------- ----------------------
  T-EXT-01   Extended Header   字段正确
  T-EXT-02   单块消息          长度正确
  T-EXT-03   多块完整消息      重组正确
  T-EXT-04   缺少中间块        报告缺块
  T-EXT-05   重复块            报告重复，不重复拼接
  T-EXT-06   乱序块            按规范处理或报告
  T-EXT-07   截断数据          保留部分数据并报告
  T-EXT-08   超过最大长度      拒绝继续扩展
  T-EXT-09   上下文重置        清理对应状态

### 8.6 统一入口与回归

  编号          测试内容                 预期结果
  ------------- ------------------------ ------------------------------
  T-PARSER-01   输入真实 CaptureRecord   返回结构化结果
  T-PARSER-02   输入 FirmwareEvent       返回事件，不进入 Header 解析
  T-PARSER-03   输入 Hard Reset          返回特殊结果
  T-PARSER-04   输入固件失败记录         保留数据和固件状态
  T-PARSER-05   输入未知类型             不崩溃，保留原始字节
  T-PARSER-06   重复解析同一记录         结果确定一致
  T-PARSER-07   全量现有测试             第一阶段功能不回归

------------------------------------------------------------------------

## 9. 进度安排

以下为单人开发建议排期，前提是第一阶段接口保持稳定，且规范与样本资料能够及时取得。

  ----------------------------------------------------------------------------------------
  里程碑           工作内容                                预计时间 交付结果
  ---------------- -------------------------- --------------------- ----------------------
  M0               样本整理、规范版本和 CRC               0.5～1 天 样本集、协议核对表
                   规则确认                                         

  M1               SOP 与 PD Header                            1 天 基础解析模块

  M2               CRC32 主机校验                         0.5～1 天 CRC 模块和测试

  M3               控制/数据消息分类                           1 天 消息分类模块

  M4               PDO/RDO                                1.5～2 天 电源能力对象解析

  M5               VDO/VDM                                     1 天 厂商消息基础解析

  M6               Extended Message                         1～2 天 扩展消息和重组

  M7               统一入口、回归和性能基线                    1 天 可独立使用的解析引擎
  ----------------------------------------------------------------------------------------

建议总计约 **7～10 个工作日**。若缺少 Request、VDM 或 Extended Message
实机样本，应将样本采集和期望结果核对单独计入工期，不得以未经验证的构造结果替代实机验收。

建议开发分支：

``` text
feature/usb-pd-decoder
```

每个里程碑完成后提交代码、更新测试和协议字段说明，并确认原有测试通过后再继续。

------------------------------------------------------------------------

## 10. 阶段范围边界与后续规划

第一阶段验收报告指出，以下工作需要分别规划和测量，不应混入协议解析引擎验收。

### 10.1 本阶段包含

-   SOP、Header、CRC32。
-   控制消息和数据消息。
-   PDO、RDO、VDO。
-   Extended Message 解析与分块重组。
-   原始数据保留、异常诊断和离线回归测试。

### 10.2 后续独立阶段

  ---------------------------------------------------------------------------------------------------------
  后续工作                   建议阶段                原因
  -------------------------- ----------------------- ------------------------------------------------------
  PD 报文列表和消息详情 UI   第三阶段                依赖稳定的 PDMessageResult

  波形展示与脉宽分析         第三/四阶段             需独立确定显示和分析需求

  DRPD                       独立阶段                需要建立并验证时间基准
  与电子负载跨设备时钟同步                           

  SQLite 持久化和历史回放    独立阶段                属于数据管理和会话设计

  大负载吞吐与捕获队列积压   独立性能阶段            需定义流量、队列深度、丢失率和测量方法

  电子负载恒流控制实机验收   独立硬件验收            第一阶段只通过当前板卡电压采样验收，恒流控制尚未验收

  自动化 USB-PD 测试流程     后续综合测试阶段        依赖消息解析和设备控制能力
  ---------------------------------------------------------------------------------------------------------

### 10.3 与电子负载恒流控制的关系

第一阶段报告的验收结论仅覆盖当前板卡的电压采样能力，恒流控制留待后续单独验收。因此第二阶段不把电子负载恒流控制列为
PD 解析引擎的通过条件，也不宣称双实机电压采样结果已经证明恒流控制合格。

------------------------------------------------------------------------

## 11. 风险分析与处理措施

  ----------------------------------------------------------------------------------------
  风险                    影响                    处理措施
  ----------------------- ----------------------- ----------------------------------------
  SOP 映射错误            报文分类错误            依据 DRPD 原版定义、USB-PD
                                                  规范和实机样本交叉核对

  Header 位域或字节序错误 后续消息解释错误        单独建立位域测试和已知样本期望值

  CRC 参数不匹配          正常报文被误判          固化参数，用真实报文和独立参考交叉验证

  固件结果与主机 CRC 混淆 诊断不可信              两套状态独立保存

  PDO 类型混合解析        电压、电流或功率错误    先识别 PDO 类型，再解释位域

  RDO 缺少前序 PDO 上下文 请求能力解释错误        保留原始 RDO，标记 context_missing

  VDO 厂商差异            未知字段解析错误        通用解析与厂商扩展解码分离

  Extended 分块丢失或重复 重组错误                建立重组状态、序号和异常诊断

  失败记录被丢弃          诊断信息丢失            保留原始 CaptureRecord

  构造样本替代实机样本    验收结论不可靠          fixture 明确标记 real/synthetic

  解析器依赖 Qt 或串口    无法离线回归            纯 Python 模块，仅依赖数据模型
  ----------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 12. 阶段验收标准

### 12.1 输入与架构

-   [ ] 直接消费第一阶段 `CaptureRecord` 和 `FirmwareEvent`。
-   [ ] 不重复实现 CDC、SCPI、Binary Block 和 CaptureRecord 解析。
-   [ ] 解析器可脱离串口和 GUI 独立运行。
-   [ ] 原始捕获数据完整保留。

### 12.2 基础协议解析

-   [ ] SOP 类型识别正确。
-   [ ] Hard Reset 进入独立分支。
-   [ ] PD Header 位域解析正确。
-   [ ] 对象数量和正文长度校验正确。
-   [ ] 固件解码状态与主机解析状态独立保存。

### 12.3 CRC 与消息语义

-   [ ] CRC32 参数和字节序有明确依据。
-   [ ] 真实完整报文 CRC 通过独立参考验证。
-   [ ] 单字节损坏样本能检出 CRC 不匹配。
-   [ ] 控制消息和数据消息正确分类。
-   [ ] 未知类型保留原始数值和数据。

### 12.4 PDO/RDO/VDO

-   [ ] 真实 Source_Capabilities Header 与 PDO 拆分正确。
-   [ ] 已声明支持的 PDO 类型字段解析正确。
-   [ ] Request/RDO 解析正确。
-   [ ] RDO 缺少上下文时有明确诊断。
-   [ ] 已声明支持的 VDM/VDO 字段解析正确。
-   [ ] 未支持类型不产生猜测结果。

### 12.5 Extended Message

-   [ ] Extended Header 解析正确。
-   [ ] 支持范围内的分块重组正确。
-   [ ] 缺块、重复块、乱序和截断均可诊断。
-   [ ] 超长数据受到限制。
-   [ ] 无法重组时保留部分数据。

### 12.6 回归与稳定性

-   [ ] 第二阶段单元测试全部通过。
-   [ ] 第一阶段上位机原有 45 项测试继续通过，新增测试后全量测试通过。
-   [ ] 第一阶段 DRPD CDC 实机回归不受影响。
-   [ ] 真实样本与 synthetic fixture 明确区分。
-   [ ] 有离线解析耗时和内存使用基线记录。

------------------------------------------------------------------------

## 13. 最终交付物

  ------------------------------------------------------------------------------
  编号                    交付物                  内容
  ----------------------- ----------------------- ------------------------------
  D2-01                   协议规则核对记录        SOP、Header、CRC
                                                  参数和规范版本依据

  D2-02                   实机测试样本集          Source_Capabilities、Hard
                                                  Reset、FirmwareEvent 等

  D2-03                   基础解析模块            SOP、Header、消息分类

  D2-04                   CRC32 模块              主机侧 CRC 计算与校验

  D2-05                   PDO/RDO 模块            电源能力与请求对象解析

  D2-06                   VDO/VDM 模块            厂商定义消息基础解析

  D2-07                   Extended Message 模块   扩展头解析与分块重组

  D2-08                   统一解析结果模型        PDMessageResult 和诊断对象

  D2-09                   自动化测试              实机样本回归和 synthetic
                                                  边界测试

  D2-10                   性能基线                离线样本解析耗时和内存记录

  D2-11                   开发说明                模块接口、支持范围和已知限制

  D2-12                   阶段验收报告            功能、测试和遗留问题记录
  ------------------------------------------------------------------------------

------------------------------------------------------------------------

## 14. 后续阶段衔接

第二阶段完成后形成以下稳定数据链：

``` text
DRPD USB CDC
      │
      ▼
第一阶段 DrpdDevice / CaptureClient
      │
      ▼
CaptureRecord / FirmwareEvent
      │
      ▼
第二阶段 USB-PD Parser
      │
      ├── SOP / Hard Reset
      ├── PD Header
      ├── CRC32
      ├── Control Message
      ├── Data Message
      ├── PDO / RDO / VDO
      └── Extended Message
      │
      ▼
PDMessageResult / FirmwareEventResult
      │
      ├── 第三阶段：PD 报文列表和消息详情 UI
      ├── 后续阶段：波形与协议关联
      ├── 后续阶段：SQLite 会话记录和历史回放
      └── 后续阶段：USB-PD 自动化测试与报告
```

**第二阶段核心原则：以第一阶段真实捕获数据为依据，构建独立、可验证、可追溯的
USB-PD 解析引擎；不将尚未实现的
GUI、跨设备时间同步、持久化和电子负载恒流控制混入本阶段验收。**
