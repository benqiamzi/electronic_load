# 电子负载与 USB-PD 综合测试平台

# 第二阶段 M5：VDM/VDO 解析模块实施计划书

  项目       内容
  ---------- --------------------------------------------
  项目名称   电子负载与 USB-PD 综合测试平台
  开发阶段   第二阶段 M5
  阶段名称   USB-PD VDM/VDO 解析模块
  开发分支   `feature/usb-pd-decoder`
  前置阶段   M0--M4
  前置验收   M4-01 至 M4-10 全部通过
  规范基线   USB PD Revision 3.2 Version 1.1（2024-10）
  开发语言   Python 3.11+
  开发框架   纯 Python 协议解析，不依赖 PySide6
  测试框架   `unittest`

------------------------------------------------------------------------

## 1. 开发背景

### 1.1 M4 阶段完成情况

根据《DRPD 第二阶段 M4 验收报告》，M4-01 至 M4-10 全部通过。

当前上位机已经具备：

-   SOP、有序集和 PD Header 解析。
-   主机侧 CRC32 计算与校验。
-   控制消息和数据消息分类。
-   Fixed、Variable、Battery、PPS PDO 解析。
-   RDO 字段解析及 PDO 位置关联。
-   `PDSessionContext` 会话上下文管理。
-   Soft Reset、Hard Reset、Cable Reset 和断开清理。
-   原始 `CaptureRecord`、正文、Data Object 和 CRC 独立保留。
-   纯 Python 协议测试和上位机全量回归。

M4 验收报告记录的回归结果为全量 86 项测试通过，其中纯 Python 环境执行 41
项协议测试。

因此，M5 应在现有协议解析框架上增量开发，不应重写已经验收的
PDO、RDO、CRC 和基础消息解析功能。

### 1.2 M5 开发必要性

当前解析器已经能够识别 `Vendor_Defined` 数据消息，但尚未完成 VDM/VDO
的语义解释。

USB-PD 的 Vendor Defined Message（VDM）用于设备身份发现、SVID
发现、模式发现和进入/退出模式等交互。

如果只保留原始 32 位 Data Object，程序只能显示原始数值，无法直接解释：

-   当前 VDM 属于哪个 SVID。
-   当前消息是 Structured VDM 还是 Unstructured VDM。
-   当前执行的是哪一种 VDM 命令。
-   对端返回的是 ACK、NAK 还是 BUSY。
-   Discover Identity、Discover SVIDs 和 Discover Modes 的返回内容。
-   VDO 对象属于通用字段还是厂商/模式专用字段。

M5 的目标是将 Vendor_Defined 消息从原始 Data Object 提升为结构化 VDM/VDO
解析结果。

------------------------------------------------------------------------

## 2. 阶段开发目标

### 2.1 VDM Header 解析

实现 VDM Header 的通用解析：

-   SVID。
-   VDM Type。
-   Structured VDM Version。
-   Object Position。
-   Command Type。
-   Command。
-   Reserved Bits。
-   原始 Header 数值。

区分：

-   Structured VDM。
-   Unstructured VDM。

Unstructured VDM 的厂商自定义字段不得强行套用 Structured VDM
的位域定义。

### 2.2 标准 Structured VDM 命令识别

首批支持以下标准命令：

    Command 名称                说明
  --------- ------------------- --------------------------
          1 Discover Identity   发现设备身份
          2 Discover SVIDs      发现支持的 SVID
          3 Discover Modes      发现指定 SVID 支持的模式
          4 Enter Mode          进入指定模式
          5 Exit Mode           退出指定模式
          6 Attention           模式状态通知

Command Type 需要区分：

-   Initiator。
-   ACK。
-   NAK。
-   BUSY。

命令编号、字段布局、版本适用性和保留位规则必须根据 USB-PD 3.2 Version
1.1 规范核对，不得仅依据第三方实现猜测。

### 2.3 VDO 解析

实现 VDO 的通用数据模型，并根据消息类型、SVID、Command 和 Object
Position 决定是否可以进一步解释字段。

首批处理：

-   Discover Identity 响应中的标准身份 VDO。
-   Discover SVIDs 响应中的 SVID 列表。
-   Discover Modes 响应中的 Mode VDO 列表。
-   Enter Mode、Exit Mode 和 Attention 的 VDO 原始数据。
-   Unstructured VDM 的厂商自定义载荷。

### 2.4 厂商扩展解码接口

建立可扩展的 VDO 解码器注册机制。

要求：

-   通用 VDM Header 解析不依赖厂商代码。
-   厂商解码器按 SVID 注册。
-   模式相关解码器可以进一步按 Object Position 或 Mode 关联。
-   未知 SVID 不报致命错误。
-   未注册解码器时仍完整保留原始 VDO。
-   厂商私有字段不得错误标记为 USB-PD 标准字段。

### 2.5 会话发现信息关联

在不破坏现有 `PDSessionContext` 的前提下，建立轻量级 VDM
发现上下文，用于关联：

``` text
Discover Identity
       |
       v
Discover SVIDs
       |
       v
Discover Modes
       |
       v
Enter Mode / Exit Mode / Attention
```

本阶段只维护可由已捕获报文直接证明的发现信息，不实现完整 Alternate Mode
状态机，也不推断未捕获的协商过程。

------------------------------------------------------------------------

## 3. 本阶段范围与边界

### 3.1 本阶段必须完成

-   Structured / Unstructured VDM 识别。
-   VDM Header 位域解析。
-   SVID、Command、Command Type 解析。
-   标准 Discover 命令识别。
-   Discover Identity、SVIDs、Modes 响应的基础 VDO 解析。
-   VDO 原始数据保留。
-   厂商解码器注册接口。
-   VDM 发现上下文及基础关联。
-   自动化测试和回归验收。

### 3.2 本阶段不要求完成

  ---------------------------------------------------------------------------
  功能                    后续安排                 原因
  ----------------------- ------------------------ --------------------------
  DisplayPort Alt Mode    有对应需求和样本后扩展   属于特定 SVID/Mode
  全字段解析                                       的专用解码

  Thunderbolt/USB4        后续扩展                 需要对应规范和实机样本
  厂商或模式专用字段                               

  任意厂商 Unstructured   按需扩展                 厂商载荷没有统一解释方式
  VDM 语义                                         

  完整 Alternate Mode     后续独立规划             超出通用 VDM 字段解析范围
  状态机                                           

  EPR 能力消息完整解析    M6                       依赖 Extended Message

  SPR AVS/EPR AVS         M6                       依赖相关扩展消息及上下文
  完整请求解释                                     

  PDO/RDO 重新实现        不需要                   M4 已验收通过
  ---------------------------------------------------------------------------

### 3.3 实机样本原则

M4 验收报告提供了真实 Source_Capabilities 和 Request
样本，但没有在报告中提供 VDM 实机捕获证据。

因此：

1.  开发初期可以使用人工构造的 VDM 样本进行单元测试。
2.  所有构造样本必须标记为 `synthetic`。
3.  如果重新捕获到真实 VDM，应保存原始 CDC 块和 CaptureRecord。
4.  真实样本与构造样本分别建立测试索引。
5.  不得将人工构造样本写成实机验收证据。
6.  若目标设备没有产生 VDM，M5
    可以先完成通用解析和构造样本测试，但报告必须明确实机覆盖范围。

------------------------------------------------------------------------

## 4. 软件架构规划

建议在现有目录中增量增加模块：

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
        ├── pdo.py
        ├── rdo.py
        ├── session.py
        │
        ├── vdm.py
        ├── vdo.py
        ├── vdm_context.py
        └── vdo_decoders/
            ├── __init__.py
            └── base.py
```

如果仓库已有相近的模型或解码器注册机制，应优先复用，避免重复建立框架。

### 4.1 `vdm.py`：VDM Header 和命令解析

负责：

-   识别 Vendor_Defined 数据消息。
-   检查 Data Object 数量。
-   提取第一个 Data Object 作为 VDM Header。
-   区分 Structured / Unstructured VDM。
-   解析 SVID。
-   解析 Structured VDM Version。
-   解析 Object Position。
-   解析 Command Type 和 Command。
-   根据规范检查保留位。
-   保留后续 VDO 对象。

建议接口：

``` python
def decode_vdm(
    data_objects: tuple[int, ...],
    *,
    sop: str,
    revision: int,
):
    ...
```

接口签名以现有 `PDMessageResult` 和 `PDHeader`
模型为准，避免重复传递已有字段。

### 4.2 `vdo.py`：VDO 通用解析

负责：

-   定义通用 VDO 结果模型。
-   按 VDM 命令解释后续对象。
-   解析 Discover Identity 响应中的标准身份字段。
-   解析 Discover SVIDs 返回的 SVID 列表。
-   解析 Discover Modes 返回的 Mode VDO 原始对象列表。
-   为厂商专用 VDO 提供解码入口。

建议模型：

``` python
@dataclass(frozen=True, slots=True)
class VDOInfo:
    index: int
    raw: int
    category: str
    decoded_fields: object | None
    diagnostics: tuple
```

注意：不同 VDO 的结构与语义取决于 SVID、命令、模式及规范版本。不能把所有
VDO 当成同一种结构解析。

### 4.3 `vdo_decoders/`：扩展解码器

建立通用注册接口：

``` python
class VDODecoder:
    def decode(self, raw: int, context):
        ...
```

注册表示意：

``` python
class VDORegistry:
    def register(self, svid: int, decoder):
        ...

    def get(self, svid: int):
        ...
```

实际实现应考虑：

-   一个 SVID 可能有多个 Mode。
-   同一 SVID 下不同命令的 VDO 结构可能不同。
-   解码器需要获得必要的 SOP、Command、Object Position
    和规范版本上下文。
-   未注册的 SVID 必须返回原始 VDO，而不是抛出未处理异常。

本阶段只建立扩展接口，不要求实现所有厂商专用解码器。

### 4.4 `vdm_context.py`：VDM 发现上下文

负责维护已经捕获并成功解析的发现信息：

-   已发现的 Identity 信息。
-   已发现的 SVID 列表。
-   各 SVID 对应的 Mode VDO。
-   已捕获的 Enter Mode / Exit Mode / Attention 事件。
-   上下文诊断和数据来源。

建议独立于 `PDSessionContext`，避免把 PDO/RDO 电源协商上下文和 Alternate
Mode 发现上下文混在一起。

建议接口：

``` python
class VDMContext:
    def consume(self, result):
        ...

    def reset(self, sop=None):
        ...

    def disconnect(self):
        ...
```

上下文应按适用的 SOP 和 SVID 隔离。Reset、Cable Reset
和断开事件的清理规则必须依据规范及实际协议上下文确定，不能直接复制 PDO
缓存的清理逻辑。

------------------------------------------------------------------------

## 5. 统一数据模型设计

### 5.1 VDM 结果模型

建议建立：

``` python
@dataclass(frozen=True, slots=True)
class VDMInfo:
    raw_header: int
    svid: int
    vdm_type: str
    structured_version: int | None
    object_position: int | None
    command_type: str | None
    command: int | None
    command_name: str | None
    vdos: tuple
    diagnostics: tuple
```

字段要求：

-   Unstructured VDM 的 Structured 专属字段使用 `None`。
-   原始 Header 始终保留。
-   未知 Command 保留原始编号。
-   未知 SVID 保留原始编号。
-   VDO 解码失败不影响原始对象读取。

### 5.2 PDMessageResult 集成

现有 `PDMessageResult` 已经包含 PDO/RDO 等结果。

建议增加可选字段：

``` python
vdm: VDMInfo | None
```

集成原则：

1.  不删除 `data_objects`。
2.  不删除原始 `body`。
3.  不修改已有 PDO/RDO 字段语义。
4.  非 Vendor_Defined 消息的 `vdm` 为 `None`。
5.  Vendor_Defined 解析失败时仍保留原始数据和诊断。
6.  未知 SVID、未知 Command 和未知 VDO 不应导致整条报文丢失。

### 5.3 诊断信息

复用现有 `ParseDiagnostic`。

建议覆盖：

-   `vdm_missing_header`
-   `vdm_unknown_type`
-   `vdm_unknown_svid`
-   `vdm_unknown_command`
-   `vdm_invalid_object_position`
-   `vdm_reserved_bits_nonzero`
-   `vdo_unexpected_count`
-   `vdo_truncated`
-   `vdo_decoder_unavailable`
-   `vdo_decoder_error`
-   `vdm_context_missing`

诊断代码应遵循仓库已有命名规则；如果已有同义代码，应复用而不是重复创建。

------------------------------------------------------------------------

## 6. 具体实施任务与里程碑

### M5.0：协议规则与样本准备

任务：

1.  核对 USB-PD 3.2 Version 1.1 中 VDM Header 字段。
2.  核对 Structured VDM Version 的定义。
3.  核对 Command Type 和标准 Command 编号。
4.  核对 Discover Identity 响应结构。
5.  核对 Discover SVIDs 的 SVID 编码和终止规则。
6.  核对 Discover Modes 的 Mode VDO 组织方式。
7.  明确不同 SOP 下的适用性。
8.  建立 synthetic VDM fixture。
9.  如果可行，采集真实 VDM 原始 CDC 样本。

交付物：

-   VDM 位域核对表。
-   标准命令表。
-   VDO 结构说明。
-   测试样本索引。
-   real/synthetic 标记。

验收：

-   所有位域有规范依据。
-   样本来源明确。
-   不把未知厂商字段解释成标准字段。

### M5.1：VDM Header 解析

任务：

1.  从 Vendor_Defined Data Message 中提取 Data Object。
2.  检查至少包含一个 VDM Header。
3.  解析 SVID。
4.  解析 Structured / Unstructured 类型。
5.  解析 Structured VDM Version。
6.  解析 Object Position。
7.  解析 Command Type。
8.  解析 Command。
9.  检查保留位和非法字段组合。
10. 保留全部原始 VDO。

测试：

-   Structured VDM。
-   Unstructured VDM。
-   不同 SVID。
-   不同 Object Position。
-   Initiator、ACK、NAK、BUSY。
-   未知 Command。
-   空 Data Object。
-   未知类型和异常保留位。

验收：

-   Header 位域与规范一致。
-   Structured/Unstructured 分类正确。
-   未知字段不丢失。
-   非法输入有诊断且不崩溃。

### M5.2：标准 Structured VDM 命令解析

任务：

1.  建立标准 Command 映射。
2.  建立 Command Type 映射。
3.  识别 Discover Identity。
4.  识别 Discover SVIDs。
5.  识别 Discover Modes。
6.  识别 Enter Mode。
7.  识别 Exit Mode。
8.  识别 Attention。
9.  检查命令与 Object Position 的适用关系。
10. 对 ACK、NAK、BUSY 的语义进行区分。

验收：

-   标准命令编号和名称映射正确。
-   ACK/NAK/BUSY 分类正确。
-   未知命令保留编号。
-   不把 NAK/BUSY 误认为成功发现结果。

### M5.3：标准 VDO 解析

任务：

**Discover Identity**

-   解析响应中的标准身份 VDO。
-   识别 ID Header、Cert Stat、Product 等标准对象。
-   根据规范版本和身份类型处理可选对象。
-   对缺失、额外或顺序异常的对象给出诊断。
-   不支持的身份字段保留原始值。

**Discover SVIDs**

-   解析每个 VDO 中承载的 SVID。
-   按规范规定的字节顺序提取 SVID。
-   识别终止标记。
-   检查重复项和异常结束情况。
-   保留原始 VDO 列表。

**Discover Modes**

-   关联当前 SVID。
-   保存各 Mode VDO。
-   记录 Mode 数量和 Object Position。
-   未注册专用解码器时保留原始 Mode VDO。

**Enter Mode / Exit Mode / Attention**

-   解析通用命令字段。
-   保留命令相关 VDO。
-   仅对规范明确规定的通用字段做语义解释。
-   不猜测厂商私有含义。

验收：

-   标准 Identity 字段解析正确。
-   SVID 列表顺序正确。
-   Mode VDO 与对应 SVID 关联正确。
-   缺失或异常对象有诊断。
-   原始数据可完整回溯。

### M5.4：厂商扩展解码接口

任务：

1.  建立 VDODecoder 基类或协议接口。
2.  建立 SVID 注册表。
3.  设计 SVID、Command、Object Position 和规范版本上下文。
4.  支持未注册 SVID 的原始数据回退。
5.  捕获解码器异常并转成诊断。
6.  建立一个 synthetic 示例解码器验证扩展接口。

验收：

-   可以注册和调用示例解码器。
-   不同 SVID 的解码器互不干扰。
-   未注册 SVID 不影响通用解析。
-   解码器异常不会使整个解析流程崩溃。
-   厂商字段与标准字段明确区分。

### M5.5：VDMContext 实现

任务：

1.  接收已解析的 VDM 结果。
2.  缓存有效 Discover Identity 响应。
3.  缓存有效 Discover SVIDs 响应。
4.  缓存各 SVID 的 Discover Modes 响应。
5.  记录 Enter Mode、Exit Mode 和 Attention。
6.  按 SOP 和 SVID 隔离上下文。
7.  处理重复发现和能力更新。
8.  处理 Reset、Cable Reset 和断开。
9.  缺少前序发现信息时给出诊断。

验收：

-   Discover Identity 信息可以查询。
-   SVID 列表可以查询。
-   Mode 列表能够关联到正确 SVID。
-   不同 SOP 的发现信息不会串扰。
-   断开后上下文能够清理。
-   不把单条 Enter Mode 消息直接认定为完整模式协商成功。

### M5.6：统一解析入口集成

任务：

1.  在现有 Vendor_Defined 分支调用 VDM 解析。
2.  将结果写入 `PDMessageResult.vdm`。
3.  保留已有 `data_objects`、`body` 和原始 CaptureRecord。
4.  复用 `ParseDiagnostic`。
5.  保持 `parse_capture(record)` 无状态。
6.  将有状态的发现关联交给 `VDMContext`。
7.  确认 PDO/RDO 解析不受影响。

验收：

-   原有调用者不需要重写。
-   非 Vendor_Defined 消息解析结果不变。
-   Vendor_Defined 消息可以获得结构化 VDM 结果。
-   解析失败时原始报文仍可检查。
-   纯 Python 环境能够运行。

### M5.7：自动化测试与阶段验收

新增测试建议：

``` text
tests/
├── test_usb_pd.py
├── test_pdo.py
├── test_rdo.py
├── test_pd_session.py
├── test_vdm.py
├── test_vdo.py
└── test_vdm_context.py
```

测试要求：

-   VDM Header 位域测试。
-   Structured / Unstructured 测试。
-   标准 Command 测试。
-   ACK / NAK / BUSY 测试。
-   Discover Identity 测试。
-   Discover SVIDs 测试。
-   Discover Modes 测试。
-   未知 SVID / Command 测试。
-   VDO 数量异常测试。
-   厂商解码器注册测试。
-   VDMContext 更新和清理测试。
-   原始数据保留测试。
-   M0--M4 全量回归测试。

------------------------------------------------------------------------

## 7. 自动化测试用例规划

  编号       测试内容                       预期结果
  ---------- ------------------------------ -----------------------------
  T-VDM-01   Structured VDM Header          位域解析正确
  T-VDM-02   Unstructured VDM Header        只解析通用字段
  T-VDM-03   不同 SVID                      SVID 原值正确
  T-VDM-04   不同 Structured VDM Version    版本字段正确
  T-VDM-05   Object Position                位置字段正确
  T-VDM-06   Initiator / ACK / NAK / BUSY   类型分类正确
  T-VDM-07   未知 Command                   保留编号并诊断
  T-VDM-08   缺失 VDM Header                返回诊断
  T-VDM-09   Reserved Bits 异常             返回诊断
  T-VDO-01   Discover Identity              标准身份对象解析正确
  T-VDO-02   Discover SVIDs                 SVID 列表正确
  T-VDO-03   Discover SVIDs 终止标记        终止规则正确
  T-VDO-04   Discover Modes                 Mode VDO 列表正确
  T-VDO-05   Enter Mode                     命令及位置正确
  T-VDO-06   Exit Mode                      命令及位置正确
  T-VDO-07   Attention                      命令及载荷保留正确
  T-VDO-08   未知 SVID                      原始 VDO 完整保留
  T-VDO-09   VDO 数量异常                   有诊断，不越界
  T-VDO-10   厂商解码器异常                 捕获异常并返回诊断
  T-CTX-01   Identity 缓存                  查询结果正确
  T-CTX-02   SVID 缓存                      列表更新正确
  T-CTX-03   Modes 关联                     关联到正确 SVID
  T-CTX-04   不同 SOP                       上下文隔离
  T-CTX-05   重复发现                       更新策略正确
  T-CTX-06   Reset / Disconnect             按规则清理
  T-CTX-07   缺少前序消息                   返回 context_missing
  T-REG-01   M0--M4 全量测试                全部通过
  T-REG-02   纯 Python 测试                 无 PySide6 依赖
  T-REG-03   原始数据回溯                   CaptureRecord 和 VDO 不丢失

测试样本必须区分真实捕获和 synthetic fixture。没有实机 VDM
记录时，应在验收报告中明确说明。

------------------------------------------------------------------------

## 8. 开发优先级

  优先级   任务                                说明
  -------- ----------------------------------- --------------------
  P0       VDM Header 解析                     M5 核心基础
  P0       Structured / Unstructured 分类      必须
  P0       Command / Command Type              必须
  P0       Discover Identity / SVIDs / Modes   标准命令首批支持
  P0       VDO 原始数据保留                    必须
  P1       VDMContext                          完成发现信息关联
  P1       VDODecoder 注册机制                 完成扩展接口
  P1       异常诊断和边界测试                  必须
  P2       DisplayPort Alt Mode 专用解码       有样本和需求后扩展
  P2       其他厂商私有 VDO                    按需扩展
  P2       完整 Alternate Mode 状态机          独立规划

------------------------------------------------------------------------

## 9. 预计开发周期

按单人开发估计：

  里程碑   工作内容                预计时间
  -------- -------------------- -----------
  M5.0     规范核对和样本准备     0.5--1 天
  M5.1     VDM Header 解析             1 天
  M5.2     标准命令解析           0.5--1 天
  M5.3     标准 VDO 解析          1--1.5 天
  M5.4     厂商扩展解码接口       0.5--1 天
  M5.5     VDMContext             0.5--1 天
  M5.6     统一入口集成              0.5 天
  M5.7     自动化测试和验收            1 天

预计总计约 **5.5--8 个工作日**。如果需要采集真实 VDM/Alternate Mode
样本，额外预留硬件捕获和样本核对时间。

------------------------------------------------------------------------

## 10. 阶段验收标准

M5 完成必须同时满足：

### 10.1 VDM 基础解析

-   [ ] Structured VDM Header 解析正确。
-   [ ] Unstructured VDM 分类正确。
-   [ ] SVID 解析正确。
-   [ ] Structured VDM Version 解析正确。
-   [ ] Object Position 解析正确。
-   [ ] Command Type 解析正确。
-   [ ] Command 解析正确。
-   [ ] 未知命令和保留位异常有诊断。

### 10.2 标准 VDO 解析

-   [ ] Discover Identity 响应可以解析。
-   [ ] Discover SVIDs 响应可以解析。
-   [ ] Discover Modes 响应可以解析。
-   [ ] Enter Mode / Exit Mode / Attention 可以识别。
-   [ ] VDO 数量异常可以诊断。
-   [ ] 未知 VDO 完整保留。

### 10.3 扩展能力

-   [ ] VDODecoder 注册机制可用。
-   [ ] 未注册 SVID 可以安全回退。
-   [ ] 解码器异常不会导致解析器崩溃。
-   [ ] VDMContext 可以关联发现结果。
-   [ ] 不同 SOP 的上下文隔离正确。
-   [ ] Reset 和断开清理符合约定。

### 10.4 回归和稳定性

-   [ ] M0--M4 原有全量测试继续通过。
-   [ ] 新增 VDM/VDO 测试全部通过。
-   [ ] 纯 Python 环境测试通过。
-   [ ] 原始 CaptureRecord 和 Data Object 保留。
-   [ ] real/synthetic 样本标记明确。
-   [ ] README 和支持范围说明已更新。
-   [ ] 完成 M5 验收报告。

------------------------------------------------------------------------

## 11. 交付物

  编号    交付物                  内容
  ------- ----------------------- --------------------------------
  D5-01   `vdm.py`                VDM Header 和命令解析
  D5-02   `vdo.py`                通用 VDO 解析
  D5-03   `vdm_context.py`        VDM 发现上下文
  D5-04   `vdo_decoders/`         厂商扩展解码接口
  D5-05   `models.py`             VDM/VDO 结果模型
  D5-06   `parser.py`             Vendor_Defined 解析集成
  D5-07   `test_vdm.py`           VDM 测试
  D5-08   `test_vdo.py`           VDO 测试
  D5-09   `test_vdm_context.py`   上下文测试
  D5-10   VDM 测试样本集          real/synthetic 分类
  D5-11   README 更新             支持范围、限制和使用方式
  D5-12   M5 验收报告             功能、测试、实机证据和遗留问题

------------------------------------------------------------------------

## 12. 开发约束

1.  不重写 M0--M4 已验收的 SOP、Header、CRC、PDO、RDO 和
    PDSessionContext。
2.  不改变 DRPD 原版固件数据帧格式。
3.  不将 VDM/VDO 解析与 PySide6 GUI 耦合。
4.  不丢弃原始 VDO、Data Object 或 CaptureRecord。
5.  不将未知 SVID 或厂商私有字段解释为标准字段。
6.  所有位域和单位必须以 USB-PD 3.2 Version 1.1 规范为依据。
7.  新增功能必须配套自动化测试。
8.  synthetic fixture 不得作为实机验收证据。
9.  未取得对应样本和规范依据时，不宣称支持某个专用 Alternate Mode。
10. 保持 M0--M4 全量回归通过。

------------------------------------------------------------------------

## 13. 后续阶段衔接

M5 完成后，第二阶段后续工作建议如下：

### M6：Extended Message 与分块重组

重点包括：

-   Extended Header。
-   Extended Data Message。
-   Chunked / Unchunked 消息。
-   Chunk Number 和分块请求字段。
-   分块缓存与重组。
-   缺块、重复块、乱序和截断诊断。
-   EPR 能力消息及相关 AVS 请求解释所需的扩展上下文。

M4 报告已经明确：SPR AVS 和 EPR AVS
的能力字段已有解码基础，但完整请求解释及 EPR 能力消息需要 M6 的 Extended
Message 支持。

### M7：完整协议回归与性能验收

重点包括：

-   扩充真实 Request 和 VDM 类型样本。
-   建立更完整的实机回放集合。
-   验证长时间捕获和大量报文解析。
-   记录解析吞吐、耗时、内存和异常输入表现。
-   验证不同协议上下文之间的数据隔离。
-   完成第二阶段最终验收报告。

### 第三阶段：协议分析 GUI

M4 报告指出，第三阶段界面可以直接读取：

-   `PDOInfo`
-   `RDOInfo`
-   `ParseDiagnostic`
-   原始报文数据

M5 完成后再增加：

-   VDM 命令列表和详情。
-   SVID 展示。
-   Identity 信息展示。
-   Discover Modes 结果展示。
-   VDO 原始值和解码字段。
-   未知厂商数据查看。

界面可以提前开发现有 PDO/RDO 内容，不必等待 M5、M6、M7 全部完成。

------------------------------------------------------------------------

## 14. 本阶段最终目标

让上位机从"能够解析 USB-PD
供电能力和请求"，进一步升级为"能够识别设备身份、发现 SVID 和
Mode，并解释标准 VDM/VDO 交互"。

**实施顺序建议：先完成 VDM Header 和标准命令解析，再完成
Identity/SVIDs/Modes 的 VDO 解析，随后增加厂商扩展接口和
VDMContext，最后完成统一入口集成及全量回归。**
