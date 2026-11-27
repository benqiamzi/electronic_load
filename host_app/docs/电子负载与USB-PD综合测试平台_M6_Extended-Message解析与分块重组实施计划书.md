# 电子负载与 USB-PD 综合测试平台

# 第二阶段 M6：Extended Message 解析与分块重组实施计划书

  项目       内容
  ---------- --------------------------------------------
  项目名称   电子负载与 USB-PD 综合测试平台
  开发阶段   第二阶段 M6
  开发分支   `feature/usb-pd-decoder`
  前置阶段   M0--M5
  前置验收   M5 §10.1--§10.4 交付项通过
  规范基线   USB PD Revision 3.2 Version 1.1（2024-10）
  开发语言   Python 3.11+
  架构约束   纯 Python 协议解析，不依赖 PySide6
  测试框架   `unittest`

------------------------------------------------------------------------

## 1. 开发背景

### 1.1 M5 阶段成果

根据《DRPD 第二阶段 M5 验收报告》：

-   M5 §10.1--§10.4 交付项全部通过。
-   VDM Header、Structured/Unstructured VDM、标准命令及 VDO
    基础解析已完成。
-   Discover Identity、Discover SVIDs、Discover Modes
    已有实机捕获和回放证据。
-   `VDMContext` 已实现发现信息关联、请求/响应匹配、按 SOP
    和响应端隔离，以及复位清理。
-   厂商解码器注册和异常隔离已完成。
-   全量自动化测试 120 项通过，纯 Python 协议测试 75 项通过。

M5 报告也明确记录了实机覆盖边界：Discover Identity ACK 缺少规范要求的
DFP VDO；部分 Discover Modes 场景出现响应 SVID 错配或缺少前序 SVID
列表。程序保留了原始报文并输出诊断。完整 Identity ACK、多页 SVID、Mode
事件和厂商解码器路径由 synthetic fixture 覆盖。

这些边界应继续保留在回归测试中，不能把构造样本描述为实机证据。

### 1.2 M6 开发目标

在现有基础解析和 VDM/VDO 框架上增加 USB-PD Extended Message 处理能力：

1.  解析 Extended Header。
2.  区分 Unchunked、Chunked 和 Request Chunk。
3.  实现跨捕获记录的分块缓存、排序、校验和重组。
4.  诊断缺块、重复块、冲突、乱序、截断、长度不一致和超时。
5.  在通用扩展消息机制之上解析 EPR Source Capabilities。
6.  将 M4 已有 PDO/RDO、AVS/EPR 字段解析与 EPR 能力上下文衔接。

**本阶段不重写 M0--M5 已验收模块，而是在现有接口上增量扩展。**

------------------------------------------------------------------------

## 2. 阶段范围

### 2.1 必须完成

  编号    功能                      目标
  ------- ------------------------- --------------------------------
  M6-01   Extended Header           位域解析、长度和保留位检查
  M6-02   Unchunked Message         单帧扩展消息解析
  M6-03   Chunked Message           分块提取、缓存和重组
  M6-04   Request Chunk             请求分块识别和关联
  M6-05   重组上下文                生命周期、超时和资源上限
  M6-06   异常诊断                  缺块、重复、乱序、截断、冲突
  M6-07   EPR Source Capabilities   完整扩展载荷的能力对象解析
  M6-08   AVS/EPR 请求关联          与 M4 PDO/RDO 和会话上下文衔接
  M6-09   回归与性能                M0--M5 回归及内存/耗时基线

### 2.2 不纳入本阶段

-   完整 USB-PD 电源协商状态机。
-   所有 Extended Message 类型的完整语义解码。
-   完整 EPR 进入/退出状态机。
-   USB4、Thunderbolt 等专用模式协议。
-   GUI 波形、协议时间线和历史数据库。

### 2.3 结果状态约定

解析结果至少区分：

-   `supported`：当前实现和测试覆盖。
-   `partial`：已解析部分字段，但消息或上下文不完整。
-   `unsupported`：格式可识别，当前未实现语义解码。
-   `invalid`：违反已确认的协议约束。
-   `context_missing`：缺少前序能力或分块上下文。

不能因为 Extended Header 解析成功，就宣称该扩展消息的全部语义已支持。

------------------------------------------------------------------------

## 3. 协议规则核对

### 3.1 Extended Header

M6.0 必须以 USB-PD 3.2 Version 1.1 为准，核对 Extended Header
位域、保留位、消息长度、Chunked/Unchunked 规则和 Request Chunk 行为。

计划采用以下字段模型，最终以规范核对记录和测试向量为准：

  位      字段            说明
  ------- --------------- --------------------
  15      Chunked         是否为分块扩展消息
  14:11   Chunk Number    当前分块编号
  10      Request Chunk   是否请求指定分块
  9       Reserved        保留位
  8:0     Data Size       扩展消息数据总长度

实现要求：

1.  显式定义位掩码和移位常量。
2.  使用明确的字节序读取 Extended Header。
3.  保留原始 16 位 Header。
4.  对保留位非零给出诊断。
5.  校验 Data Size、Chunk Number、Chunked 和 Request Chunk 的组合。
6.  Request Chunk 不得被误当成普通数据分块。
7.  单个 Chunk 的载荷长度不得被误认为整个扩展消息长度。

### 3.2 Chunk 规则

M6.0 必须核对并记录：

-   单帧扩展数据的最大长度。
-   每个 Chunk 的有效数据长度。
-   最大扩展消息长度。
-   Chunk Number 的有效范围。
-   最后一个 Chunk 的有效长度和填充规则。
-   Request Chunk 的 Data Object 数量、方向和关联规则。

不要在代码中散落硬编码的 `26`、`260`
等数值。应将规范常量集中定义，附上规范依据，并通过边界测试证明适用条件。

### 3.3 分块关联键

分块重组不能只根据 Chunk Number 拼接。至少考虑：

-   SOP 类型。
-   Extended Message Type。
-   消息发送方向或发送端角色。
-   会话/复位代次。
-   Data Size。
-   Chunk Number。
-   Request Chunk 的反向请求关系。

PD Message ID
会随消息传输变化，不能未经规范核对就将其作为整个扩展传输的唯一关联键。

同一 SOP、消息类型和发送方向的分块应进入对应重组上下文；Request Chunk
应关联到反方向待发送的对应扩展消息。关联条件不足时返回
`context_missing`，不得猜测拼接对象。

------------------------------------------------------------------------

## 4. 软件架构规划

建议在现有 `electronic_load_gui/protocols/usb_pd/` 中增量增加：

``` text
usb_pd/
├── parser.py
├── models.py
├── diagnostics.py
├── pdo.py
├── rdo.py
├── session.py
├── vdm.py
├── vdo.py
├── vdm_context.py
├── extended.py
├── reassembly.py
├── extended_context.py
└── epr.py
```

如果仓库已有等价模块或命名约定，应优先复用。

### 4.1 `extended.py`：单帧扩展消息解析

职责：

-   检查 PD Header 的 Extended 标志。
-   读取并解析 Extended Header。
-   识别 Unchunked、Chunk Data 和 Request Chunk。
-   提取当前帧的扩展数据片段。
-   校验单帧长度、Data Size 和填充。
-   保留原始字节和诊断。

建议入口：

``` python
def decode_extended_message(result):
    ...
```

复用现有 `PDMessageResult` 的 SOP、Header、正文和 CRC
状态，不重复解析基础 PD Header。

### 4.2 `reassembly.py`：分块重组引擎

职责：

-   建立分块传输上下文。
-   按 Chunk Number 保存数据。
-   检查各 Chunk 的 Data Size 一致性。
-   处理乱序、重复和冲突。
-   检测缺失块。
-   判断消息是否完整。
-   按 Data Size 拼接 payload。
-   保留部分重组数据和来源记录。
-   对缓存数量和内存使用设置上限。

建议接口：

``` python
class ExtendedMessageReassembler:
    def consume(self, result):
        ...

    def expire(self, timestamp_us):
        ...

    def reset(self, sop=None):
        ...

    def disconnect(self):
        ...
```

`consume()` 应返回明确状态：

-   `pending`：等待后续 Chunk。
-   `complete`：完整重组。
-   `partial`：存在部分数据或捕获结束。
-   `invalid`：分块字段或长度冲突。
-   `context_missing`：缺少可关联的上下文。

### 4.3 `extended_context.py`：扩展消息上下文

负责：

-   按 SOP 隔离重组状态。
-   按消息类型和方向区分传输。
-   关联 Request Chunk。
-   管理会话代次。
-   管理超时和资源上限。
-   处理 Soft Reset、Hard Reset、Cable Reset、Data Reset Complete
    和设备断开。
-   保留重组失败诊断和已收到的数据。

生命周期规则应依据 USB-PD 规范和 M5 已建立的上下文规则核对，不能把所有
Reset 简单处理为相同动作。

### 4.4 `epr.py`：EPR 能力语义解析

在通用扩展消息解析和重组完成后，再解析 EPR 能力消息。

任务：

1.  核对 EPR Source Capabilities 的 Extended Message Type 和数据布局。
2.  检查完整重组 payload 的长度和对象边界。
3.  提取 PDO/Data Object。
4.  复用 M4 已有 PDO 解码器。
5.  区分 SPR 能力和 EPR 能力来源。
6.  将 EPR 能力上下文与现有 `PDSessionContext` 衔接。
7.  使用已通告的 EPR 能力解释相关 AVS/EPR 请求。
8.  对缺少能力上下文、能力更新或协商状态不完整的情况给出诊断。

不得在 `epr.py` 中复制 Fixed、PPS、AVS PDO 位域实现。必须复用 M4
已验收的 PDO/RDO 模型和解码器。

### 4.5 与现有解析器的关系

保持：

``` python
parse_capture(record)
```

作为单条 CaptureRecord 的基础入口。

建议数据流：

``` text
CaptureRecord
     |
     v
parse_capture(record)
     |
     v
PDMessageResult
     |
     +---- 普通 Control/Data
     |
     +---- VDM/VDO
     |
     +---- ExtendedMessageInfo
                  |
                  v
       ExtendedMessageReassembler
                  |
          +-------+-------+
          |               |
       pending         complete
                          |
                          v
                  EPR 语义解码
                          |
                          v
                 ExtendedAnalysis
```

架构约束：

-   `parse_capture()` 负责单帧，不直接维护跨帧缓存。
-   `ExtendedMessageReassembler` 负责跨帧重组。
-   `PDSessionContext` 继续管理 PDO/RDO 电源能力上下文。
-   `VDMContext` 继续管理 VDM 发现上下文。
-   扩展消息上下文不得与 VDM 或 PDO/RDO 缓存混成一个无边界对象。
-   原始 CaptureRecord、PD Header、CRC、Extended Header
    和分块字节必须可追溯。

------------------------------------------------------------------------

## 5. 数据模型设计

### 5.1 ExtendedHeader

``` python
@dataclass(frozen=True, slots=True)
class ExtendedHeader:
    raw: int
    data_size: int
    chunked: bool
    chunk_number: int
    request_chunk: bool
    reserved: int
```

### 5.2 ExtendedMessageInfo

``` python
@dataclass(frozen=True, slots=True)
class ExtendedMessageInfo:
    message_type: int
    header: ExtendedHeader
    chunk_payload: bytes
    parse_status: str
    diagnostics: tuple
    raw_body: bytes
```

该模型只表达单条 PD 帧中的扩展消息，不代表完整重组消息。

### 5.3 ReassembledExtendedMessage

``` python
@dataclass(frozen=True, slots=True)
class ReassembledExtendedMessage:
    sop: str
    message_type: int
    direction: str
    data_size: int
    payload: bytes
    received_chunks: tuple[int, ...]
    missing_chunks: tuple[int, ...]
    status: str
    diagnostics: tuple
```

完整消息的 `payload` 应按 Data Size 截取，不包含 Chunk 填充字节。

### 5.4 PDMessageResult 集成

建议增加可选字段：

``` python
extended_message: ExtendedMessageInfo | None
```

不得删除或改变现有字段：

``` python
result.header
result.body
result.data_objects
result.pdos
result.rdo
result.vdm
result.crc_valid
result.capture_record
```

跨帧重组结果通过独立的 `ExtendedAnalysis` 返回，不要让单条
`PDMessageResult` 隐式包含其他 CaptureRecord 的数据。

------------------------------------------------------------------------

## 6. 具体实施任务与里程碑

### M6.0：规范核对与样本准备

任务：

1.  核对 Extended Header 位域。
2.  核对 Chunked/Unchunked 规则。
3.  核对最大 Data Size 和单 Chunk 有效数据长度。
4.  核对 Chunk Number 范围。
5.  核对 Request Chunk 格式和方向关联。
6.  核对 Extended Message Type 映射。
7.  核对 EPR Source Capabilities 的消息类型和数据结构。
8.  核对 EPR PDO 与 AVS/EPR RDO 的适用字段。
9.  建立 synthetic fixture。
10. 尝试采集真实 Extended/EPR 样本。

交付物：Extended Header 位域表、Chunk 规则表、消息类型清单、EPR
字段核对表、样本索引。

验收：所有常量和字段有规范依据；测试向量可独立复算；synthetic 与 real
样本明确区分。

### M6.1：Extended Header 与单帧解析

任务：

-   在现有 PD Header 解析后识别 Extended Message。
-   解析 Extended Header。
-   识别 Unchunked、Chunk Data 和 Request Chunk。
-   校验 Data Size、Chunk Number、Reserved Bits。
-   校验当前帧长度和填充。
-   保留原始扩展数据。

测试：正常 Unchunked、Chunk 0、中间 Chunk、最后 Chunk、Request
Chunk、边界长度、保留位异常、短 Header、截断数据、错误 Chunk Number。

验收：位域和数据边界正确；Request Chunk
不被误判为普通数据块；异常输入不越界、不崩溃。

### M6.2：Unchunked Extended Message

任务：

-   完成不分块扩展消息解析。
-   按 Data Size 截取有效数据。
-   校验填充和实际长度。
-   处理长度不一致。
-   识别未知 Extended Message Type 并保留原始 payload。

验收：支持范围内的 Unchunked
消息完整解析；填充不计入有效数据长度；截断和长度不匹配有诊断。

### M6.3：Chunked Message 重组

任务：

1.  实现重组上下文。
2.  接收并缓存 Chunk。
3.  按 Chunk Number 组织数据。
4.  检查 Data Size 一致性。
5.  检查每个 Chunk 的有效长度。
6.  支持乱序到达后的缓存和完整性判断。
7.  识别相同内容的重复 Chunk。
8.  识别内容冲突的重复 Chunk。
9.  检测缺失 Chunk。
10. 按 Data Size 拼接完整 payload。
11. 保留部分数据和来源记录。

验收：完整消息重组正确；乱序不会错误拼接；重复块不会造成数据重复；冲突块有诊断；缺块时不伪造完整消息。

### M6.4：Request Chunk 与生命周期管理

任务：

-   识别 Request Chunk。
-   关联反方向待传输的扩展消息。
-   检查请求的 Chunk Number。
-   记录请求与后续 Chunk 的关系。
-   处理缺少请求或响应。
-   管理超时。
-   设置最大活动重组数量和最大缓存字节数。
-   处理 Reset 和 Disconnect。
-   提供显式 `expire(timestamp_us)` 或等价接口。

超时策略使用可控的设备时间戳或显式调用，不依赖不可测试的隐式墙上时钟。

验收：Request Chunk
关联正确；反方向普通数据不误关联；超时释放缓存；Reset/Disconnect
后不复用旧会话数据；资源上限生效。

### M6.5：EPR Source Capabilities 与 AVS/EPR 请求解释

任务：

1.  实现 EPR Source Capabilities 类型识别。
2.  对完整重组 payload 做对象边界检查。
3.  按规范解析 EPR 能力对象。
4.  复用 M4 PDO 解码器。
5.  区分 SPR 和 EPR 能力列表。
6.  将 EPR 能力上下文与 `PDSessionContext` 对接。
7.  使用已通告能力解释相关 AVS/EPR 请求。
8.  检查请求位置、能力类型和请求范围。
9.  缺少 EPR Source Capabilities 时返回 `context_missing`。
10. 不完整消息保留部分对象和诊断。

约束：

-   不重写 M4 已验收的 Fixed/PPS/AVS PDO 位域。
-   不根据单条 EPR Request 推断 EPR 合同已建立。
-   不把能力通告、请求接受和实际电源输出混为一谈。
-   未实现的扩展类型保留原始数据。

验收：支持范围内的 EPR Source Capabilities 可解析；PDO
类型和单位正确；SPR/EPR
来源清晰；相关请求可关联正确能力；缺少上下文有诊断。

### M6.6：统一入口集成与兼容性

任务：

-   将 Extended Header 解析集成到 `parse_capture()`。
-   增加 `PDMessageResult.extended_message`。
-   将跨帧状态交给 `ExtendedMessageReassembler`。
-   将 EPR 语义解析交给 `epr.py`。
-   与 `PDSessionContext` 建立最小必要接口。
-   保持 `VDMContext` 不受影响。
-   回归普通 Control/Data、PDO/RDO、VDM/VDO。

验收：旧调用者无需大规模重写；普通 PD 解析不回归；原始数据和 CRC
状态保留；单帧解析与跨帧重组职责清晰。

### M6.7：测试、性能和阶段验收

任务：

-   完成 Extended Header 单元测试。
-   完成 Unchunked 测试。
-   完成 Chunked 重组测试。
-   完成 Request Chunk 关联测试。
-   完成异常和资源上限测试。
-   完成 EPR 能力与 AVS/EPR 请求测试。
-   执行 M0--M5 全量回归。
-   执行纯 Python 协议测试。
-   记录离线重组耗时、吞吐和内存基线。
-   更新 README 和支持范围。
-   编写 M6 验收报告。

------------------------------------------------------------------------

## 7. 自动化测试用例规划

### 7.1 Extended Header

  编号         测试内容               预期结果
  ------------ ---------------------- --------------------------
  T-EXT-H-01   正常 Extended Header   位域正确
  T-EXT-H-02   Chunked 标志           分类正确
  T-EXT-H-03   Unchunked 标志         分类正确
  T-EXT-H-04   Request Chunk          标志和 Chunk Number 正确
  T-EXT-H-05   Reserved Bit 非零      产生诊断
  T-EXT-H-06   短数据                 不越界
  T-EXT-H-07   非法 Chunk Number      invalid/诊断
  T-EXT-H-08   Data Size 边界         判断正确

### 7.2 Unchunked

  编号         测试内容                 预期结果
  ------------ ------------------------ ----------------------
  T-EXT-U-01   正常 Unchunked           payload 正确
  T-EXT-U-02   最小有效数据             长度正确
  T-EXT-U-03   最大 Unchunked 数据      边界正确
  T-EXT-U-04   填充字节                 不计入有效 payload
  T-EXT-U-05   Data Size 大于实际数据   partial/invalid 诊断
  T-EXT-U-06   未知扩展消息类型         原始数据保留

### 7.3 Chunked 重组

  编号         测试内容            预期结果
  ------------ ------------------- ----------------------
  T-EXT-C-01   完整顺序分块        重组正确
  T-EXT-C-02   多块乱序到达        按 Chunk Number 重组
  T-EXT-C-03   缺少中间块          partial，记录缺块
  T-EXT-C-04   相同内容重复块      不重复拼接
  T-EXT-C-05   冲突重复块          冲突诊断
  T-EXT-C-06   Data Size 不一致    拒绝错误拼接
  T-EXT-C-07   最后一块截断        partial/invalid
  T-EXT-C-08   超过最大消息长度    拒绝并诊断
  T-EXT-C-09   Chunk Number 越界   invalid
  T-EXT-C-10   缺少 Chunk 0        报告缺少起始块
  T-EXT-C-11   重复完整消息        不串入上一轮传输
  T-EXT-C-12   不同 SOP 同时分块   上下文隔离

### 7.4 Request Chunk 与生命周期

  编号         测试内容             预期结果
  ------------ -------------------- ----------------------
  T-EXT-R-01   正常 Request Chunk   识别正确
  T-EXT-R-02   请求已缓存的 Chunk   关联正确
  T-EXT-R-03   请求不存在的 Chunk   产生诊断
  T-EXT-R-04   反方向消息           不错误关联
  T-EXT-R-05   缺少待传输上下文     context_missing
  T-EXT-R-06   超时清理             缓存释放
  T-EXT-R-07   Hard Reset           按规则清理
  T-EXT-R-08   Cable Reset          按 SOP 规则清理
  T-EXT-R-09   Disconnect           相关缓存清理
  T-EXT-R-10   缓存数量超限         安全拒绝或淘汰并诊断

### 7.5 EPR 能力和请求

  编号       测试内容                       预期结果
  ---------- ------------------------------ -------------------
  T-EPR-01   EPR Source Capabilities 类型   识别正确
  T-EPR-02   完整 EPR 能力 payload          对象边界正确
  T-EPR-03   EPR PDO 解码                   复用 M4 解码器
  T-EPR-04   SPR/EPR 能力隔离               来源区分正确
  T-EPR-05   AVS/EPR 请求关联               对象位置正确
  T-EPR-06   请求超出能力范围               产生诊断
  T-EPR-07   缺少 EPR 能力上下文            context_missing
  T-EPR-08   不完整 EPR 消息                保留部分对象
  T-EPR-09   未支持扩展类型                 原始 payload 保留

### 7.6 回归与性能

  编号       测试内容                  预期结果
  ---------- ------------------------- ----------------
  T-REG-01   M0--M5 原有全量测试       全部通过
  T-REG-02   纯 Python 协议测试        不加载 PySide6
  T-REG-03   原始 CaptureRecord 回溯   数据完整
  T-REG-04   同一记录重复解析          结果确定一致
  T-REG-05   大量分块回放              无无界内存增长
  T-REG-06   多 SOP 混合回放           上下文不串扰
  T-REG-07   异常输入压力测试          无未处理异常

------------------------------------------------------------------------

## 8. 测试样本与实机验证策略

### 8.1 Synthetic Fixture

在没有真实 Extended Message 样本时，先建立：

-   最小和最大 Unchunked。
-   两块及多块完整消息。
-   Request Chunk。
-   缺块、重复块、乱序。
-   Data Size 冲突和截断。
-   EPR Source Capabilities。
-   AVS/EPR 请求与能力关联。

每个样本在 fixture 索引中标记 `synthetic`，并记录构造依据和预期字段。

### 8.2 Real Fixture

如果硬件、对端设备和固件支持，优先采集：

1.  一条完整 Unchunked Extended Message。
2.  一条完整 Chunked Extended Message。
3.  至少一个 Request Chunk 往返。
4.  一组 EPR Source Capabilities。
5.  一条与已通告 EPR 能力相关的请求。

保存原始 SCPI Binary Block、CaptureRecord
字段、固件版本、捕获周期、设备时间戳、对端设备和测试条件，并标记样本来源。

如果实机环境不能产生对应消息，验收报告必须明确写出限制，不能把 synthetic
fixture 描述为实机验证。

### 8.3 回放要求

实机样本应通过现有 CDC Binary Block、CaptureRecord 和 `parse_capture()`
链路回放，确保测试覆盖真实数据入口，而不只是手工调用底层解码函数。

------------------------------------------------------------------------

## 9. 开发优先级

  优先级   任务                           说明
  -------- ------------------------------ ------------------
  P0       Extended Header                M6 基础
  P0       Unchunked 解析                 单帧完整扩展消息
  P0       Chunked 重组                   核心功能
  P0       缺块/重复/乱序/截断诊断        必须
  P0       Request Chunk                  必须纳入协议支持
  P1       重组上下文生命周期和资源限制   稳定性要求
  P1       EPR Source Capabilities        主要语义扩展
  P1       AVS/EPR 请求关联               依赖能力上下文
  P1       实机 Extended 回放             条件允许时完成
  P2       其他 Extended Message 类型     按需求扩展
  P2       完整 EPR 状态机                后续独立规划
  P2       GUI 扩展消息时间线             第三阶段

------------------------------------------------------------------------

## 10. 预计开发周期

按单人开发估计：

  里程碑   工作内容                         预计时间
  -------- ----------------------------- -----------
  M6.0     规范核对、样本准备              0.5--1 天
  M6.1     Extended Header 和单帧解析           1 天
  M6.2     Unchunked 解析                     0.5 天
  M6.3     Chunked 重组                    1.5--2 天
  M6.4     Request Chunk 和生命周期        1--1.5 天
  M6.5     EPR 能力与 AVS/EPR 请求关联     1--1.5 天
  M6.6     统一入口集成                       0.5 天
  M6.7     测试、性能和验收报告                 1 天

预计总计约 **7--9 个工作日**。如需采集真实 EPR/Extended Message
样本，另行预留硬件捕获和对端设备联调时间。

------------------------------------------------------------------------

## 11. 阶段验收标准

### 11.1 基础扩展消息解析

-   [ ] Extended Header 位域解析正确。
-   [ ] Data Size 和保留位检查正确。
-   [ ] Unchunked 消息解析正确。
-   [ ] Chunked 消息单帧解析正确。
-   [ ] Request Chunk 能够识别。
-   [ ] 未知 Extended Message Type 保留原始数据。

### 11.2 分块重组

-   [ ] 完整 Chunked 消息重组正确。
-   [ ] Chunk Number 顺序处理正确。
-   [ ] Data Size 与重组长度一致。
-   [ ] 缺块、重复、冲突、乱序和截断均有诊断。
-   [ ] Request Chunk 与对应传输关联正确。
-   [ ] 超时、Reset 和 Disconnect 能清理上下文。
-   [ ] 重组缓存有数量和内存上限。

### 11.3 EPR 能力解析

-   [ ] EPR Source Capabilities 消息类型识别正确。
-   [ ] 完整 payload 的对象拆分正确。
-   [ ] PDO 解码复用 M4 实现。
-   [ ] SPR/EPR 能力来源区分正确。
-   [ ] AVS/EPR 请求与通告能力关联正确。
-   [ ] 缺少上下文和能力越界均有诊断。
-   [ ] 不将能力通告误判为实际供电合同。

### 11.4 回归与稳定性

-   [ ] M0--M5 原有全量测试全部通过。
-   [ ] 新增 M6 测试全部通过。
-   [ ] 纯 Python 测试通过且不依赖 PySide6。
-   [ ] 原始 CaptureRecord、CRC 和分块字节可追溯。
-   [ ] real/synthetic fixture 标记明确。
-   [ ] 性能和内存基线已记录。
-   [ ] README 和支持范围说明已更新。
-   [ ] M6 验收报告完成。

------------------------------------------------------------------------

## 12. 交付物

  编号    交付物                       内容
  ------- ---------------------------- ----------------------------------
  D6-01   `extended.py`                Extended Header 和单帧解析
  D6-02   `reassembly.py`              Chunked 分块重组
  D6-03   `extended_context.py`        上下文、Request Chunk 和生命周期
  D6-04   `epr.py`                     EPR 能力和请求关联解析
  D6-05   `models.py`                  Extended 结果模型
  D6-06   `parser.py`                  单帧解析入口集成
  D6-07   `test_extended.py`           Extended Header 和单帧测试
  D6-08   `test_reassembly.py`         分块重组测试
  D6-09   `test_extended_context.py`   上下文和生命周期测试
  D6-10   `test_epr.py`                EPR 能力和请求测试
  D6-11   测试样本集                   real/synthetic fixture 及索引
  D6-12   README 更新                  支持范围、限制和使用方式
  D6-13   性能记录                     解析耗时、吞吐和内存基线
  D6-14   M6 验收报告                  功能、测试、实机证据和遗留问题

------------------------------------------------------------------------

## 13. 开发约束与风险控制

### 13.1 开发约束

1.  不重写 M0--M5 已验收的 SOP、Header、CRC、PDO/RDO、VDM/VDO
    和上下文模块。
2.  不改变 DRPD 原版固件数据帧格式。
3.  不将 Extended Message 解析与 PySide6 GUI 耦合。
4.  不丢弃原始 CaptureRecord、Extended Header 和分块数据。
5.  不把单帧 Chunk 误认为完整扩展消息。
6.  不把 Request Chunk 当作普通数据分块。
7.  不将 PD Message ID 直接作为整个扩展传输的唯一关联键。
8.  所有长度、分块和位域规则以 USB-PD 3.2 Version 1.1 规范为依据。
9.  新增功能必须有自动化测试。
10. synthetic fixture 不得作为实机验收证据。
11. 不因 EPR 能力被通告就认定已经建立 EPR 合同。
12. 保持 M0--M5 全量回归通过。

### 13.2 风险与措施

  -------------------------------------------------------------------------------------
  风险                    影响                    处理措施
  ----------------------- ----------------------- -------------------------------------
  Extended Header         扩展消息解析错误        M6.0 规范核对和独立位域测试
  位域错误                                        

  Data Size 与填充混淆    重组长度错误            按有效数据长度截取，独立测试填充

  Chunk 关联键不足        不同传输串包            SOP、方向、类型、代次和长度共同约束

  Request Chunk           请求关联错误            建立反方向关联测试
  方向处理错误                                    

  缺块被误判完整          产生错误 payload        校验全部必需 Chunk 和最终长度

  重复块导致数据重复      消息内容损坏            相同内容忽略，冲突内容诊断

  缓存无限增长            长时间运行内存耗尽      活动传输数、字节数和超时上限

  Reset 清理过度或不足    后续消息错误关联        按 SOP 和规范分别制定清理规则

  EPR 语义过早实现        能力解释错误            先完成通用重组，再做 EPR 语义

  缺少真实 EPR 样本       实机覆盖不足            synthetic 测试与真实证据分开报告
  -------------------------------------------------------------------------------------

------------------------------------------------------------------------

## 14. 后续阶段衔接

### 14.1 M7：完整协议回归与性能验收

M6 完成后，M7 建议开展：

-   扩充真实 Extended Message、Request Chunk 和 EPR 样本。
-   完成普通 PD、VDM 和 Extended Message 混合回放。
-   验证长时间捕获下的上下文清理和内存稳定性。
-   测量单帧解析耗时、分块重组耗时和持续吞吐。
-   验证异常输入、重复输入和跨 SOP 数据隔离。
-   汇总 M0--M6 协议支持矩阵。
-   编写第二阶段最终验收报告。

### 14.2 第三阶段：协议分析 GUI

M6 完成后，GUI 可以展示：

-   Extended Message 类型。
-   Extended Header 字段。
-   Chunk Number 和 Chunked 状态。
-   当前重组进度。
-   缺失分块和异常诊断。
-   完整重组 payload。
-   EPR Source Capabilities 和 PDO 列表。
-   AVS/EPR 请求与能力关联详情。

GUI 应直接消费解析结果，不应在界面层重新实现 Extended Header 或 Chunk
重组。

------------------------------------------------------------------------

## 15. 本阶段最终目标

M6 的核心目标是建立可靠的 USB-PD Extended Message 处理链：

``` text
DRPD CaptureRecord
        |
        v
   parse_capture()
        |
        v
 Extended Header
        |
        +------------------+
        |                  |
        v                  v
    Unchunked           Chunked
        |                  |
        |                  v
        |          Reassembly Engine
        |                  |
        +--------+---------+
                 |
                 v
       完整/部分 Extended Payload
                 |
                 v
       EPR / 其他扩展语义解析
                 |
                 v
       ExtendedAnalysis
                 |
                 v
       第三阶段 GUI 展示
```

**实施顺序建议：先完成规范核对和 Extended Header，再完成 Unchunked 与
Chunked 解析，随后实现 Request Chunk 和重组生命周期，最后接入 EPR 能力与
AVS/EPR 请求解释，并进行 M0--M5 全量回归。**
