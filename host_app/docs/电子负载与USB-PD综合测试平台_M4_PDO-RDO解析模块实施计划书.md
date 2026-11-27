# 电子负载与 USB-PD 综合测试平台

# 第二阶段 M4：PDO/RDO 解析模块实施计划书

  项目           内容
  -------------- --------------------------------------------
  项目名称       电子负载与 USB-PD 综合测试平台
  开发阶段       第二阶段 M4
  阶段名称       PDO/RDO 解析模块
  开发分支       `feature/usb-pd-decoder`
  上一阶段基线   M0--M3 基础解析
  规范基线       USB PD Revision 3.2 Version 1.1（2024-10）
  开发语言       Python 3.11+
  开发框架       纯 Python 协议解析，不依赖 PySide6
  测试框架       `unittest`

------------------------------------------------------------------------

## 1. 开发背景

目前上位机已经完成 USB-PD 基础协议解析，能够识别 SOP、解析 Header、验证
CRC32，并对控制消息和普通数据消息进行分类。

现有解析入口：

``` python
electronic_load_gui.protocols.usb_pd.parse_capture(record)
```

目前已经能够将普通数据消息拆分为原始 32 位 Data Object：

``` python
PDMessageResult.data_objects
```

但尚未完成 PDO/RDO 的语义解析。

当前主要缺少：

1.  Fixed、Variable、Battery、Augmented PDO 类型识别。
2.  PDO 电压、电流、功率等参数换算。
3.  Request Data Object 字段解析。
4.  RDO 与此前 Source_Capabilities 中 PDO 的关联。
5.  PDO/RDO 数据完整性及合法性检查。

因此，本阶段目标是在不破坏 M0--M3 接口的前提下，建立 PDO/RDO
解析与上下文关联机制。

## 2. 阶段开发目标

### 2.1 PDO 解析

支持 USB-PD 数据对象中的主要供电能力类型：

-   Fixed Supply PDO
-   Variable Supply PDO
-   Battery Supply PDO
-   Augmented PDO
    -   PPS APDO
    -   AVS APDO

按照 Source_Capabilities 和 Sink_Capabilities
的消息方向选择对应字段定义。

对于暂不支持的子类型、保留位或不适用字段，保留原始数值并给出诊断，不得猜测解析。

### 2.2 RDO 解析

实现 Request Data Object 的结构化解析：

-   Object Position
-   Operating Current / Operating Power
-   Maximum Operating Current / Power
-   GiveBack
-   Capability Mismatch
-   USB Communications Capable
-   No USB Suspend
-   Reserved Bits

根据所选 PDO 类型决定 RDO 的具体解释方式。

### 2.3 协议上下文关联

新增 `PDSessionContext`，负责维护此前接收到的
Source_Capabilities，并将后续 Request 与对应 PDO 关联。

注意：保持 `parse_capture()`
无状态，不将会话管理逻辑直接写入基础解析器。

### 2.4 最终交付目标

完成后应能够：

1.  解析真实 Source_Capabilities 中的七个 PDO。
2.  显示每个 PDO 的供电类型、电压、电流或功率。
3.  解析 Request 中的 RDO。
4.  根据 Object Position 找到对应 PDO。
5.  检查请求参数是否超出供电能力。
6.  在缺少上下文时明确报告无法关联，而不是错误地判定报文无效。

------------------------------------------------------------------------

## 3. 软件架构规划

建议在现有目录下扩展：

``` text
electronic_load_gui/
└── protocols/
    └── usb_pd/
        ├── __init__.py
        ├── parser.py
        ├── models.py
        ├── diagnostics.py
        ├── header.py
        ├── sop.py
        ├── crc.py
        ├── message_types.py
        │
        ├── pdo.py
        ├── rdo.py
        └── session.py
```

### 3.1 `pdo.py`：PDO 解析模块

负责 PDO 类型识别和字段解析。

建议接口：

``` python
def decode_pdo(
    raw: int,
    *,
    direction: str,
    revision: int,
):
    ...
```

主要功能：

-   判断 PDO 类型。
-   根据类型选择字段布局。
-   进行电压、电流、功率换算。
-   检查保留位和非法组合。
-   保留原始 32 位数据。

建议使用独立数据模型，例如：

``` python
@dataclass(frozen=True, slots=True)
class PDOInfo:
    index: int
    raw: int
    supply_type: str
    voltage_min_mv: int | None
    voltage_max_mv: int | None
    current_max_ma: int | None
    power_max_mw: int | None
    diagnostics: tuple
```

具体实现时可以使用 FixedPDO、BatteryPDO、VariablePDO、PPSPDO
等专用数据模型，避免不同类型字段混用。

所有内部物理量优先使用整数单位：

-   电压：mV
-   电流：mA
-   功率：mW

协议层不要使用浮点数进行关键换算。

### 3.2 `rdo.py`：RDO 解析模块

负责 RDO 字段解析。

建议接口：

``` python
def decode_rdo(
    raw: int,
    selected_pdo=None,
):
    ...
```

需要区分：

-   Fixed / Variable RDO
-   Battery RDO
-   PPS RDO

解析 Object
Position、电流、电压、功率请求字段及相关能力标志，并检查保留位。

建议输出结构：

``` python
@dataclass(frozen=True, slots=True)
class RDOInfo:
    raw: int
    object_position: int
    request_type: str | None
    operating_current_ma: int | None
    operating_power_mw: int | None
    operating_voltage_mv: int | None
    diagnostics: tuple
```

具体字段应按不同 RDO 类型分别扩展。RDO 字段布局不能仅根据 RDO
原始数值猜测，必须结合其选择的 PDO 类型。

### 3.3 `session.py`：PD 会话上下文

新增协议会话管理：

``` python
class PDSessionContext:
    def consume(self, result):
        ...
```

负责：

1.  接收已解析的 `PDMessageResult`。
2.  缓存 Source_Capabilities。
3.  维护对应 PDO 列表。
4.  接收 Request。
5.  根据 Object Position 关联 PDO。
6.  检查请求参数与 PDO 能力范围。
7.  管理 Soft Reset、Hard Reset、Cable Reset
    和断开事件对应的上下文生命周期。

建议按 SOP 分离协议上下文，防止 SOP、SOP'、SOP'' 的数据互相污染。

Hard Reset、Cable Reset 和 Soft Reset
必须分别制定状态处理规则，不应简单地统一清空全部缓存。

当前阶段不实现完整的 PD 电源协商状态机，也不根据单条 Request
直接认定供电合同已经建立。

------------------------------------------------------------------------

## 4. 具体实施任务

### M4.0：接口设计与基础测试准备

主要任务：

-   确定 PDO/RDO 数据模型。
-   确定 PDO 解码接口。
-   确定 RDO 解码接口。
-   确定 `PDSessionContext` 的输入和输出。
-   明确 PD 3.2 规范中的字段定义及单位。
-   为现有 Cable Reset 补充完整 `parse_capture()` 分支测试。

验收标准：

-   不破坏现有 M0--M3 接口。
-   原始 Data Object 保持可访问。
-   解析结果保留原始 `CaptureRecord`。
-   基础模型能够表达不支持、无效和无法关联三种不同情况。

### M4.1：PDO 解析实现

建议实现顺序：

1.  Fixed Supply PDO。
2.  Variable Supply PDO。
3.  Battery Supply PDO。
4.  PPS APDO。
5.  AVS APDO 的字段识别与规范范围处理。

首先以真实 Source_Capabilities 样本作为核心测试对象。

当前真实样本：

``` text
0x0A01912C
0x0002D12C
0x0003C12C
0x0004B12C
0x000641F4
0xC8DC3264
0xC9903264
```

根据字段初步解码，前五个对象预期为：

  PDO   供电类型     电压   最大电流
  ----- ---------- ------ ----------
  1     Fixed         5 V        3 A
  2     Fixed         9 V        3 A
  3     Fixed        12 V        3 A
  4     Fixed        15 V        3 A
  5     Fixed        20 V        5 A

后两个对象预期为 PPS APDO：

  PDO   电压范围     最大电流
  ----- ---------- ----------
  6     5--11 V           5 A
  7     5--20 V           5 A

以上数值必须在编码时按照 USB-PD
规范表格独立复核，并固化为测试断言。若规范核对结果与初步解码不一致，以规范及真实报文为准，修订预期值并记录依据。

验收标准：

-   七个 PDO 全部成功识别。
-   供电类型判断正确。
-   电压、电流及功率单位换算正确。
-   原始 32 位数值完整保留。
-   非法保留位和未知类型产生诊断。
-   Source 和 Sink 的字段解释不混淆。

### M4.2：RDO 解析实现

主要任务：

-   实现 Fixed/Variable RDO。
-   实现 Battery RDO。
-   实现 PPS RDO。
-   解析 Object Position。
-   解析电流、电压、功率请求字段。
-   检查保留位。
-   检查请求对象数量。

测试使用人工构造的 RDO 数据。

需要覆盖：

1.  正常请求。
2.  Object Position 为 0。
3.  Object Position 超出 PDO 数量。
4.  请求电流超过 PDO 上限。
5.  请求电压超出 PPS 范围。
6.  Reserved Bits 非零。
7.  RDO 与所选 PDO 类型不匹配。
8.  缺少前序 Source_Capabilities。

验收标准：

-   各类型 RDO 字段正确解析。
-   非法请求能够识别。
-   缺少上下文时返回未关联状态。
-   不因缺少 PDO 上下文而丢失原始 RDO。

### M4.3：`PDSessionContext` 实现

建立有状态的协议上下文。

数据流：

``` text
Source_Capabilities
        |
        v
    PDO 解码
        |
        v
   缓存 PDO 列表
        |
        v
      Request
        |
        v
    RDO 解码
        |
        v
   Object Position
        |
        v
    关联目标 PDO
        |
        v
   请求参数合法性检查
```

需要特别测试：

-   多次 Source_Capabilities 更新。
-   Request 对象位置关联。
-   缺失前序能力消息。
-   不同 SOP 的数据隔离。
-   Hard Reset 后的状态处理。
-   Cable Reset 不错误清除 SOP 电源协商上下文。
-   设备断开后清除整个会话。

验收标准：

-   正确关联前序 PDO。
-   新能力消息能够更新缓存。
-   上下文不存在时明确报告原因。
-   不发生跨 SOP 错误关联。
-   纯 Python 环境能够独立运行。

### M4.4：基础解析入口集成

在完成独立模块后，扩展现有解析结果。

保持：

``` python
parse_capture(record)
```

继续负责单条报文解析。

建议在 `PDMessageResult` 中增加可选的语义解析结果，或者使用独立的
`PDSessionAnalysis` 结果包装会话关联信息。

不应删除或替换：

``` python
result.data_objects
result.body
result.header
result.crc_valid
```

保证第三阶段可以继续使用已有字段。

### M4.5：自动化测试与文档

新增测试文件：

``` text
tests/
├── test_usb_pd.py
├── test_pdo.py
├── test_rdo.py
└── test_pd_session.py
```

要求：

-   全量测试通过。
-   PDO 各类型测试通过。
-   RDO 各类型测试通过。
-   Session 上下文测试通过。
-   真实样本回放通过。
-   不依赖 Qt 环境。
-   更新 README 中的协议能力说明。
-   编写 M4 阶段验收报告。

------------------------------------------------------------------------

## 5. 开发优先级

  优先级   任务                             重要程度
  -------- -------------------------------- ---------------------------
  P0       PDO 基础类型识别                 必须
  P0       七个实机 PDO 解析                必须
  P0       Fixed/Variable/Battery/PPS RDO   必须
  P0       PDO/RDO 上下文关联               必须
  P1       Sink PDO 解码                    纳入完整验收
  P1       保留位与异常数据诊断             必须
  P1       AVS/EPR 扩展接口                 预留；完整关联依赖后续 M6
  P2       完整 PD 协商状态机               不属于本阶段
  P2       PDO/RDO GUI 展示                 交由第三阶段

------------------------------------------------------------------------

## 6. 阶段验收标准

M4 完成必须同时满足：

  编号    验收项目        通过条件
  ------- --------------- --------------------------------
  M4-01   实机 PDO 解析   七个对象全部正确解析
  M4-02   PDO 类型识别    Fixed、Variable、Battery、APDO
  M4-03   物理量换算      电压、电流、功率单位正确
  M4-04   RDO 解析        对应 RDO 字段正确
  M4-05   PDO/RDO 关联    Object Position 对应正确
  M4-06   合法性检查      超范围请求能够诊断
  M4-07   上下文管理      更新、复位和断开处理正确
  M4-08   数据完整性      原始数据始终保留
  M4-09   回归测试        原有测试全部通过
  M4-10   独立运行        不依赖 PySide6

特别说明：

当前实机样本只包含 Source_Capabilities，不包含真实 Request/RDO。因此，M4
阶段首先使用标记为 `synthetic` 的人工构造 RDO
样本进行验证；如能重新捕获真实
Request，应增加真实样本回归，不能将人工样本描述为实机验收证据。

------------------------------------------------------------------------

## 7. 预计开发周期

按单人开发估计：

  阶段                    预计工作量
  --------------------- ------------
  M4.0 接口和测试设计         0.5 天
  M4.1 PDO 解析            1--1.5 天
  M4.2 RDO 解析            1--1.5 天
  M4.3 Session 上下文      1--1.5 天
  M4.4 接口集成               0.5 天
  M4.5 测试及验收报告      0.5--1 天

预计总计：4.5--7 个工作日。具体取决于 AVS/EPR 边界和规范核对工作量。

------------------------------------------------------------------------

## 8. 交付物

1.  `pdo.py`：PDO 解析模块。
2.  `rdo.py`：RDO 解析模块。
3.  `session.py`：`PDSessionContext`。
4.  `models.py`：新增结构化 PDO/RDO 数据模型。
5.  `parser.py`：统一解析入口集成。
6.  `test_pdo.py`：PDO 测试。
7.  `test_rdo.py`：RDO 测试。
8.  `test_pd_session.py`：上下文测试。
9.  更新后的 README。
10. 《DRPD 第二阶段 M4 验收报告》。

------------------------------------------------------------------------

## 9. 开发约束

1.  不重写已经验收的 SOP、Header、CRC 基础实现。
2.  不改变第一阶段 DRPD CDC 数据帧格式。
3.  不将协议解析与 Qt GUI 耦合。
4.  不丢弃原始 Data Object。
5.  不把无法关联的 RDO 误判为 CRC 或基础解析错误。
6.  所有单位换算必须以 USB PD 3.2 Version 1.1 规范为依据。
7.  新增功能必须有自动化测试。
8.  不将未验证的 AVS/EPR 功能标记为已支持。
9.  保持 M0--M3 全量回归通过。

------------------------------------------------------------------------

## 10. 后续阶段衔接

M4 完成后继续：

-   **M5：VDM/VDO 解析**。
-   **M6：Extended Message 解析与分块重组**。
-   **M7：完整协议回归、实机测试和性能验收**。
-   **第三阶段：** PD 报文列表、消息详情及实时捕获界面。

第三阶段 GUI 可以提前使用当前已有的解析接口开发，但完整 PDO/RDO
语义展示以 M4 验收通过为准。

------------------------------------------------------------------------

## 11. 本阶段最终目标

让上位机从"能够识别 USB-PD
数据对象"，升级为"能够解释供电能力、解析电源请求，并建立两者之间的关联"。

**开发顺序建议：先完成真实样本中的五个 Fixed PDO 和两个 PPS
APDO，再扩展其他 PDO 类型；随后实现
RDO，最后建立会话上下文并完成回归验收。**
