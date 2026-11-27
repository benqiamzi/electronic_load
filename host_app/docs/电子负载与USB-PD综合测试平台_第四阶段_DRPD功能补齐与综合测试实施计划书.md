# 电子负载与 USB-PD 综合测试平台

# 第四阶段：DRPD 功能补齐与综合测试实施计划书

| 项目 | 内容 |
|---|---|
| 文档版本 | V1.0 |
| 规划依据 | 第三阶段 PySide6 实施计划书 V1.2 模块切换版 |
| 前置阶段 | 第三阶段已完成软件回归，部分实机项目待补测 |
| GUI 框架 | PySide6 |
| USB-PD 通信 | USB CDC，沿用 DRPD 原版固件数据帧与现有 SCPI 事务机制 |
| 协议解析 | 复用第二阶段已验收的 USB-PD 解析模块 |
| 功能参考 | DRPD 原版上位机的仪表、测量、捕获、日志、触发和 Sink 功能 |
| 阶段定位 | 补齐第三阶段尚未覆盖的 DRPD 核心仪表能力，并完成综合实机验证 |

---

## 1. 规划结论

第三阶段已经完成了综合平台的基础软件框架和 USB-PD 协议分析主链路。第四阶段不应重复开发已有的实时捕获、PDO/RDO、VDM/VDO、Extended/EPR 解析、诊断、离线回放和导出功能，而应把工作重点转向 DRPD 原版上位机中尚未在第三阶段验收报告中体现的测量、时间关联、触发、日志管理和设备控制能力。

本阶段分为两个层次：

1. **第三阶段收尾验证**：补齐双设备并行实机、捕获期间物理拔出、EPR 实机协商和长时间捕获完整性验证。
2. **DRPD 功能补齐**：优先实现模拟测量仪表、Timestrip、增强型 Message Log 和 Trigger；Sink Control 在固件能力审查后再决定是否纳入本阶段。

### 1.1 已经具备的能力

依据《DRPD_第三阶段验收报告.md》，以下功能已经通过软件回归，部分已完成 DRPD 实机验证：

- 电子负载 / USB PD 测试双工作区切换、状态栏和工作区恢复。
- DRPD USB CDC 连接、设备标识和固件信息读取。
- DRPD 实时捕获、捕获队列排空和报文列表显示。
- PD 报文详情、原始字节、PDO/RDO、VDM/VDO、Extended/EPR 展示。
- 诊断定位、RDO 原始值检索和异常报文原始数据查看。
- 原始捕获保存、CSV、解析 JSON、诊断 Markdown 导出。
- 离线逐帧、暂停、继续、文件错误恢复和重新回放。
- 12,000 条构造记录回放以及现有电子负载 GUI 回归。

第三阶段报告记录了 168 项全量测试通过、118 项纯 Python 测试通过；DRPD 实机捕获约 60.53 秒、归档 111 条记录。上述数据说明现有主链路已经建立，但不等于长时间实机捕获、物理链路无丢帧或全部 DRPD 仪表功能已经完成。

### 1.2 当前主要缺口

| 优先级 | 功能缺口 | 当前判断 | 下一步处理 |
|---|---|---|---|
| P0 | 双设备实机并行 | 第三阶段报告列为待补测 | 在当前 GUI 版本下重新验证电子负载 CDC 与 DRPD CDC 并行 |
| P0 | 捕获期间物理拔出 | 目前由模拟 CDC 覆盖意外移除，实机物理拔出待验证 | 完成拔出、状态恢复、重新连接和捕获状态核验 |
| P0 | EPR 实机协商 | 构造样本覆盖 EPR 分块与请求关联；实机未观察到 EPR Source Capabilities | 使用支持 EPR 的 Source 和合适 DUT 验证完整链路 |
| P0 | 长时间捕获与数据完整性 | 当前实机记录约 1 分钟；固件没有捕获丢包总数 | 扩展实机测试，增加主机队列/背压统计，明确物理丢包不可观测边界 |
| P1 | VBUS / IBUS 实时测量 | 第三阶段报告未体现 DRPD 模拟测量仪表 | 审查 CDC 查询能力后增加测量仪表 |
| P1 | CC Lines | 第三阶段报告未体现 DUT/USDS 两侧 CC 电压仪表 | 审查固件是否提供 CC1/CC2 测量值 |
| P1 | Accumulator | 第三阶段报告未体现累计电荷、能量和计时器 | 审查 `MEAS:ACC?` 等能力后实现 |
| P1 | Timestrip | 目前有报文时间戳和列表，未体现消息与模拟采样统一时间轴 | 实现消息、模拟采样和事件的时间关联视图 |
| P1 | 增强型 Message Log | 已有列表、RDO 原始值搜索和诊断定位；Sender/Receiver 等过滤、标注和历史查询未见验收证据 | 补齐 DRPD 常用过滤、标注和历史日志能力 |
| P1 | Trigger | 第三阶段报告未体现触发配置和外部同步控制 | 审查固件命令后实现触发仪表 |
| P2 | Sink Control | 已读取 Sink 状态，但主动 PDO 请求和协商控制未见验收证据；V1.2 将自动控制列为非目标 | 作为受控扩展，单独审查命令、风险和硬件能力 |
| P2 | 可定制仪表架 | V1.2 采用工作区/页面结构，第三阶段报告未体现 DRPD 式动态仪表架 | 先实现默认仪表布局，再考虑编辑和持久化 |
| P3 | 固件升级、Cable Test、帮助系统 | DRPD 上游存在相关能力，当前验收报告未体现 | 不作为核心功能阻塞项，后续按项目需要选做 |

“未见验收证据”表示现有第三阶段验收报告没有证明该功能已实现，不代表已经确认代码中完全不存在。实施前应以最新 M7 源码和固件命令清单复核。

---

## 2. DRPD 功能对照

本节将 DRPD 原版公开资料中的功能与本项目第三阶段验收状态对照。DRPD 的 WebUSB/USBTMC 前端实现不作为本项目的通信实现模板；本项目继续使用 PySide6、USB CDC 和既有 DRPD 固件数据帧。

### 2.1 设备状态与测量仪表

| DRPD 功能 | DRPD 原版能力 | 本项目当前状态 | 建议 |
|---|---|---|---|
| Device Status | CC Bus 角色、连接状态、捕获状态/计数、Sink 状态 | 已读取设备标识、固件、捕获状态和 Sink 状态；完整状态面板未在报告中逐项证明 | 补齐角色、Attach 状态、捕获状态、Sink 状态和最近更新时间 |
| VBUS | VBUS 电压/电流、保护状态、OVP/OCP 阈值和故障复位 | 第三阶段报告未体现 DRPD VBUS 实时测量与保护配置 | P1 实现 |
| CC Lines | DUT/USDS 两侧 CC1/CC2 电压及状态 | 第三阶段报告未体现 | P1 实现 |
| Accumulator | 累计时间、电荷 mAh、能量 mWh、复位 | 第三阶段报告未体现 | P1 实现 |

DRPD 上游驱动文档公开了模拟测量命令组，包括 `MEAS:ALL?`、`MEAS:ACC?`、`MEAS:VOLT:CC:DUT1?`、`MEAS:VOLT:CC:DUT2?`、`MEAS:VOLT:CC:USDS1?` 和 `MEAS:VOLT:CC:USDS2?`；VBUS 状态与阈值通过 `BUS:VBUS:*` 命令组管理。

这些命令只能作为固件能力审查的参考。必须先确认复刻固件版本确实实现相同命令、参数单位和返回格式，不能只因为上游 DRPD 支持就认定当前固件支持。

### 2.2 协议捕获与分析

| DRPD 功能 | 本项目当前状态 | 差距判断 |
|---|---|---|
| Message Log 实时列表 | 已完成基本实时列表 | 核心能力已有 |
| Message Detail | 已完成原始字节、协议字段、PDO/RDO、VDM/VDO、Extended/EPR 和诊断展示 | 核心能力已有；可增强字段帮助和事件说明 |
| Message Timing | 已有设备时间戳、帧号和报文持续时间相关数据 | 尚未形成与模拟测量统一的交互式时间轴 |
| Search / Filter | 已验证 RDO 原始值检索和诊断代码定位 | Sender、Receiver、SOP、CRC、Flag、Attach/Detach、时间范围等组合过滤未见完整验收证据 |
| Annotation / Flag | 第三阶段报告未体现用户标注、备注或重点标记 | 建议补齐 |
| 历史日志 | 已能保存原始捕获并重新加载 | 尚未证明具备类似 DRPD 的长期历史日志查询和模拟采样持久化 |
| CSV / JSON Export | 已完成原始捕获、CSV、解析 JSON 和诊断 Markdown 导出 | 基本导出已有；可增加实时 CSV 流式记录 |

### 2.3 Timestrip

DRPD Timestrip 不只是报文列表的时间戳列，而是把数字协议事件和模拟测量数据放到统一时间轴：

- USB-PD 消息起止时间、消息持续时间和相邻事件间隔。
- Attach/Detach、Hard Reset、协议错误等事件标记（前提是捕获记录提供相应事件）。
- VBUS 电压和 IBUS 电流模拟采样曲线。
- 时间轴缩放、平移、范围选择和实时跟随。
- 点击时间轴消息可定位 Message Log；选择 Message Log 行可反向定位 Timestrip。
- 在同一时间范围内查看协议事件与电气测量变化。

本项目当前已有报文时间戳和捕获记录，因此可以先完成消息时间轴；模拟曲线需要先完成模拟测量数据采集和持久化。没有模拟采样时不得绘制推算波形。

### 2.4 Trigger

DRPD Trigger 主要提供：

- 触发状态和事件计数。
- 触发事件类型：Preamble Start、SOP Start、Header Start、Data Start、Message Complete、Hard Reset、Invalid K-Code、CRC Error、Timeout、Runt Pulse、Any Error 等（以固件实际枚举为准）。
- 事件阈值。
- Sender Filter：Any / Source / Sink / Cable。
- Message Type Filter。
- Auto Repeat。
- Sync 输出模式：Pulse High、Pulse Low、Toggle、Pull Down。
- Sync Pulse Width 设置。
- 触发配置读取、设置、复位和状态回读。

本项目第三阶段验收报告未体现 Trigger 控制面板和命令回读。该功能应列为 P1，但必须先核对固件命令是否可用。

### 2.5 Sink Control

DRPD Sink Control 是让 DRPD 作为 USB-PD Sink 向被测 Source 请求电压/电流档位，不是直接控制充电器作为 Source 输出某个电压。

DRPD 原版能力包括：

- 读取 Source 通告的 PDO 列表。
- 选择 PDO。
- 对 Fixed / PPS / AVS 等已支持能力设置请求电压和电流。
- 显示请求状态、当前协商 PDO、协商电压和电流。
- 对请求范围进行校验。
- 根据固件支持范围发送额外的 Sink Inquiry。

本项目第三阶段只在验收报告中证明读取了 Sink 状态，没有证明完整的 PDO 请求和协商控制。V1.2 将自动控制充电器输出电压/电流列为暂不实现，因此本阶段不建议做自动扫描或无人值守电压扫测。若后续纳入，先做用户确认的手动请求，并显示“请求已发送”“设备已接受”“协议协商成功”三个不同状态。

### 2.6 仪表架与布局

DRPD 使用 Instrument Rack 组织 VBUS、Accumulator、Device Status、CC Lines、Sink Control、Sync Trigger、Message Log、Timestrip 和 Message Detail。

DRPD 的布局能力包括：

- 添加和移除仪表。
- 仪表跨行拖动和排序。
- 调整仪表宽度及行高度。
- 仪表全屏查看。
- 编辑模式下保存或取消布局变更。
- 保存布局并在下次启动时恢复。

本项目 V1.2 采用双工作区和固定功能页面，第三阶段报告证明工作区切换已经完成，但没有证明实现了可定制仪表架。建议不要为了视觉一致性立即重构全部 GUI；先把核心测量/日志组件做成独立 QWidget，再以默认固定布局组合。待功能稳定后再增加拖动、尺寸调整和布局持久化。

---

## 3. 第四阶段范围

### 3.1 本阶段必须完成

| 编号 | 工作项 | 目标 |
|---|---|---|
| P4-01 | 第三阶段实机收尾 | 完成双设备并行、物理拔出、EPR 实机协商验证 |
| P4-02 | 固件命令能力审查 | 建立 MEAS、VBUS、CC、TRIG、SINK 命令和返回格式清单 |
| P4-03 | Device Status 增强 | 统一展示角色、连接状态、捕获状态和 Sink 状态 |
| P4-04 | 模拟测量服务 | 接入 VBUS、IBUS、CC1/CC2 和累计测量数据 |
| P4-05 | 测量仪表 | 实现 VBUS、CC Lines、Accumulator 仪表 |
| P4-06 | Timestrip | 建立消息与模拟采样统一时间轴 |
| P4-07 | Message Log 增强 | 增加组合过滤、标注、历史查询和实时记录 |
| P4-08 | Trigger | 实现触发配置、状态回读和同步输出控制（固件支持时） |
| P4-09 | 仪表架基础布局 | 把核心功能组件组合为可扩展的默认仪表布局 |
| P4-10 | 系统联调 | 实机、性能、数据完整性和电子负载回归 |

### 3.2 条件实现

以下项目必须通过 P4-02 固件能力审查后才能进入开发：

- Sink Control 的 PDO 请求和 PPS/AVS 请求。
- EPR Sink 配置和请求。
- VBUS OVP/OCP 阈值设置及故障复位。
- Trigger 的所有事件源、消息类型过滤和外部 Sync。
- CC 线路测量与状态分类。
- VBUS/IBUS 模拟采样的高频轮询和历史记录。

如果固件不支持某项命令，本阶段只输出接口差距清单，不允许通过 GUI 模拟命令成功或填充假数据。

### 3.3 本阶段暂不实现

- 修改 DRPD 原版 Binary Block / CaptureRecord 数据帧格式。
- 重写第二阶段协议解析器。
- 完整 USB-PD 电源协商状态机。
- 完整 Alternate Mode / USB4 状态机。
- 自动化电压/电流扫描和无人值守 Sink 测试。
- 云端同步、多人协作和远程设备管理。
- 完整固件升级工具（除非项目后续明确要求）。
- 复杂的多设备同步分析。

---

## 4. 软件架构增量

在 V1.2 已有 DeviceService、CaptureService、AnalysisService、ReplayService、ExportService 和 WorkspaceManager 的基础上，增量增加以下模块。实际目录以当前 M7 代码为准，不要求为了匹配本文档而整体搬迁现有代码。

```text
electronic_load_gui/
├── services/
│   ├── telemetry_service.py       # 模拟测量轮询、数据单位和时间戳
│   ├── vbus_service.py            # VBUS 状态、阈值和保护状态
│   ├── trigger_service.py         # 触发配置与状态
│   ├── sink_service.py            # 条件实现：Sink PDO 请求
│   ├── log_service.py             # 历史日志、标注和查询
│   └── timestrip_service.py       # 消息/模拟采样时间轴数据适配
├── ui/
│   ├── instruments/
│   │   ├── device_status_widget.py
│   │   ├── vbus_widget.py
│   │   ├── cc_lines_widget.py
│   │   ├── accumulator_widget.py
│   │   ├── trigger_widget.py
│   │   ├── message_log_widget.py
│   │   ├── timestrip_widget.py
│   │   └── message_detail_widget.py
│   └── rack/
│       ├── rack_view.py
│       ├── rack_layout_model.py
│       └── rack_layout_editor.py
└── tests/
    ├── test_telemetry_service.py
    ├── test_trigger_service.py
    ├── test_log_service.py
    └── test_timestrip_model.py
```

### 4.1 TelemetryService

职责：

- 统一接收固件实际提供的 VBUS、IBUS、DUT CC1/CC2、USDS CC1/CC2 和累计测量值。
- 保存设备时间戳和主机接收时间戳。
- 统一单位、有效性、超时和缺失状态。
- 向 VBUS、CC Lines、Accumulator 和 Timestrip 发布更新。
- 对轮询频率、平均窗口和显示刷新频率分层管理。
- 设备断开时停止轮询并清理当前会话状态。

要求：

- 设备实测值与协议通告/请求值必须分开显示。
- 数据无效或超时时显示 `Unavailable` / `Stale`，不能保持绿色正常状态。
- 不根据 PDO/RDO 推算实际 VBUS/IBUS。
- 不允许 GUI 直接发起无序并发 SCPI 查询；继续沿用单串口请求串行化机制。

### 4.2 TimestripService

职责：

- 将 PD 消息、固件事件和模拟采样转换为统一时间轴数据。
- 保留设备侧时间戳和主机时间戳，不混淆两个时间基准。
- 处理捕获重启、时间戳回绕/重置和不同会话之间的时间轴断点。
- 支持按可视时间范围加载数据，避免一次性把全部历史记录绘制到界面。
- 向 Message Log 和 Message Detail 提供双向定位索引。

### 4.3 LogService

职责：

- 保存原始捕获记录、解析摘要、模拟采样和用户标注。
- 支持按捕获会话、时间范围、消息类型、Sender、Receiver、SOP、CRC、Flag 和诊断代码查询。
- 支持历史记录分页和搜索。
- 支持实时 CSV 流式写入及离线 CSV/JSON 导出。
- 数据库或文件格式需要版本号和迁移策略。
- 原始 Binary Block / CaptureRecord 必须无损保留，CSV 摘要不能替代原始捕获。

第一版可采用 SQLite 保存索引、模拟采样和标注；若现有原始捕获格式已稳定，应保留原始文件格式，不要为增加数据库而破坏兼容性。

---

## 5. 具体实施里程碑

### P4.0：基线同步与接口能力审查

任务：

1. 将第三阶段验收所用 M7 代码基线和验收报告同步到 GitHub，明确唯一可复现的分支和提交。
2. 检查当前 `feature/usb-pd-decoder` 分支是否已包含第三阶段 M7 代码；若未包含，先完成代码同步，不以旧分支作为第四阶段开发基线。
3. 对照 DRPD 固件源码/命令定义，建立 `P4_DRPD_COMMAND_MATRIX.md`。
4. 审查 `MEAS:ALL?`、`MEAS:ACC?`、CC 电压、VBUS 状态/阈值、TRIG 和 SINK 命令。
5. 对每条命令记录：命令字符串、参数范围、返回字段、单位、固件版本、是否已在复刻板实测。
6. 核对 USB CDC 请求队列是否可以承载模拟测量轮询和捕获读取并存。
7. 记录固件是否提供捕获溢出/丢包计数；若没有，明确主机侧可观测范围。
8. 冻结第四阶段第一批仪表范围和默认布局。

交付物：

- `P4_DRPD_COMMAND_MATRIX.md`
- `P4_FEATURE_GAP_MATRIX.md`
- `P4_ARCHITECTURE_UPDATE.md`

验收：

- 每项计划功能均有已验证的数据/命令来源，或被明确标记为固件不支持。
- 不更改原版固件数据帧。
- M7 代码、测试和验收报告可从 GitHub 对应提交复现。

### P4.1：第三阶段实机收尾验证

任务：

1. 双设备并行：同时连接电子负载和 DRPD，验证两个 CDC 端口独立运行。
2. 并行工作负载：电子负载持续测量/控制，DRPD 同时捕获 PD 报文。
3. 捕获期间物理拔出 DRPD：确认串口关闭、捕获状态复位、队列和上下文清理。
4. 重新插入设备：重新识别、连接并启动新捕获会话。
5. EPR 实机验证：使用支持 EPR 的 Source、合适线缆和 DUT，观察 EPR Source Capabilities、进入 EPR 模式及 AVS/EPR Request。
6. 长时间捕获：逐步扩展到至少 30 分钟，再根据设备和目标吞吐延长。
7. 记录捕获记录数、主机处理数、队列峰值、背压次数、解析耗时、导出耗时、内存峰值。
8. 如果固件没有物理丢包计数，不得声称“物理链路零丢帧”；报告只能说明主机收到并归档的记录完整性。

验收：

- 双设备并行期间两个设备状态互不覆盖。
- 物理拔出不导致 GUI 崩溃或串口请求永久挂起。
- 重连后新会话不继承旧会话上下文。
- EPR 实机结果有原始捕获文件和可复现步骤。
- 长时间捕获的主机侧数据完整性和性能边界有量化记录。

### P4.2：设备状态与模拟测量仪表

任务：

1. 完成 Device Status：角色、Attach 状态、捕获开关、捕获计数、Sink 状态和设备错误。
2. 完成 VBUS：电压、电流、功率、OVP/OCP 阈值、保护状态和故障复位。
3. 完成 CC Lines：DUT/USDS 两侧 CC1/CC2 电压和状态标签。
4. 完成 Accumulator：累计时间、电荷 mAh、能量 mWh 和 Reset。
5. 增加数据更新时间、超时和不可用状态。
6. 对模拟测量值使用单独的数据模型，不与 PDO/RDO 能力值混合。
7. 增加仪表单元测试和真实设备采样测试。

验收：

- 所有显示读数均来自固件返回的真实数据。
- 单位和量程与固件命令定义一致。
- 保护阈值设置后必须读回确认。
- 断开设备后仪表显示断开/无数据，不保留误导性的旧读数。
- Reset 操作有二次确认，累计值复位结果与设备返回一致。

### P4.3：Timestrip 时间轴与模拟曲线

任务：

1. 显示 PD 消息的起始时间、结束时间、持续时间和相邻事件间隔。
2. 显示 Hard Reset、Attach/Detach、协议错误等可识别事件。
3. 接入 VBUS/IBUS 模拟采样曲线。
4. 对齐设备时间戳与主机时间戳，显示时间基准。
5. 支持缩放、平移、范围选择和实时跟随。
6. Timestrip 选择消息后定位 Message Log。
7. Message Log 选中消息后反向定位 Timestrip。
8. 处理采样缺口、设备重连和时间戳重置，不跨会话错误连线。

验收：

- 同一捕获会话的消息和模拟采样能按设备时间戳正确排列。
- 选择消息与时间轴定位双向同步。
- 缺失模拟采样时不生成插值假数据。
- 大数据量下只加载可视范围及必要缓冲数据。

### P4.4：增强型 Message Log 与历史日志

任务：

1. 补齐 Sender、Receiver、Message Type、SOP、CRC、Flag、解析状态和时间范围过滤。
2. 支持 Attach/Detach、Hard Reset、设备事件等事件过滤（仅限捕获记录实际提供的事件）。
3. 支持组合过滤和一键清除过滤条件。
4. 增加 Flag / Annotation / Comment。
5. 标注与原始消息、捕获会话和时间戳绑定。
6. 建立本地历史日志索引和分页查询。
7. 增加实时 CSV 流式记录。
8. 保留原始捕获文件、CSV 摘要和 JSON 详细导出的不同用途。
9. 增加历史日志清理和存储空间提示。

验收：

- 过滤不修改原始记录。
- 搜索结果能定位到原始消息和 Timestrip。
- 用户标注重启后仍存在，并能随记录导出。
- 原始捕获可以独立重新回放。
- 大规模历史日志查询不会阻塞 GUI 主线程。

### P4.5：Trigger 仪表

任务：

1. 查询并显示 Trigger 当前状态和事件计数。
2. 实现固件实际支持的事件类型选择。
3. 实现事件阈值和 Sender Filter。
4. 实现 Message Type Filter。
5. 实现 Auto Repeat。
6. 实现 Sync Mode 和 Sync Pulse Width。
7. 实现读取当前配置、设置配置和 Reset。
8. 配置应用后重新查询设备状态，不以按钮点击成功代替设备确认。
9. 记录触发配置和捕获文件元数据，便于复现实验。

验收：

- 每项触发配置均与设备读回值一致。
- 不支持的事件类型明确禁用。
- 外部 Sync 输出通过示波器/逻辑分析仪验证脉冲极性和宽度。
- 触发发生后，Message Log、Timestrip 和捕获文件能定位相应事件（若固件提供对应记录）。

### P4.6：Sink Control（条件实现）

仅在 P4.0 确认复刻固件已提供对应命令、且硬件测试条件安全时实施。

任务：

1. 读取 Source 通告 PDO 列表。
2. 展示 PDO 类型、序号、电压范围、电流/功率能力。
3. 选择 PDO 并输入请求电压、电流。
4. 对 Fixed、PPS、AVS、EPR AVS 等模式按固件支持范围实现参数校验。
5. 发送请求前显示请求预览和确认。
6. 显示请求状态、当前协商 PDO、电压、电流和错误状态。
7. 区分命令发送、设备接受和协议协商完成。
8. 对 EPR 请求设置额外的能力检查和安全限制。
9. 记录每次请求的参数、设备响应和关联报文。

验收：

- 请求参数不得超出当前 Source PDO 能力范围。
- 请求成功状态必须由设备/协议响应确认。
- 不支持的 PDO 类型或固件命令不得发送。
- 第一版只做用户主动操作，不做自动扫描和无人值守调压。

若固件不支持 Sink 请求命令，本里程碑延期，不影响 P4.2～P4.5 的交付。

### P4.7：仪表架基础与布局持久化

任务：

1. 将 Device Status、VBUS、CC Lines、Accumulator、Trigger、Message Log、Timestrip、Message Detail 封装为独立 QWidget。
2. 先实现固定默认布局。
3. 增加仪表显示/隐藏和恢复默认布局。
4. 增加面板尺寸调整。
5. 后续实现编辑模式、拖动排序、跨行移动、全屏查看。
6. 使用版本化 JSON 或 QSettings 保存布局。
7. 保存布局时只保存仪表类型、实例 ID、位置、尺寸和面板配置，不保存实时设备状态。

验收：

- 每个仪表独立刷新和处理异常。
- 单个仪表不可用不影响其他仪表。
- 布局保存和恢复稳定。
- 编辑布局不会中断捕获或设备控制。

### P4.8：系统联调与阶段验收

任务：

1. 执行所有新增 Service 和 GUI 单元测试。
2. 执行 168 项及后续新增测试的完整回归。
3. 执行纯 Python 协议测试，确保不依赖 PySide6。
4. 实机验证模拟测量、Trigger、Sink Control（仅已支持项目）。
5. 验证长时间捕获和历史日志。
6. 验证 Timestrip 与 Message Log 联动。
7. 验证设备拔出、重连和双设备并行。
8. 验证原始捕获、CSV、JSON 和历史日志导出。
9. 验证原有电子负载测量、恒流控制和保护功能。
10. 编写第四阶段验收报告和功能差距报告。

---

## 6. 自动化测试与验收用例

### 6.1 实机与连接测试

| 编号 | 测试内容 | 预期结果 |
|---|---|---|
| T4-HW-01 | 电子负载与 DRPD 双设备同时连接 | 两个 CDC 会话独立运行 |
| T4-HW-02 | 双设备同时工作 | 测量、控制和 PD 捕获互不阻塞 |
| T4-HW-03 | 捕获期间物理拔出 DRPD | GUI 不崩溃，设备状态转为断开 |
| T4-HW-04 | 拔出后重新连接 | 新会话可正常启动，上下文清理 |
| T4-HW-05 | EPR Source 实机捕获 | 能观察并保存 EPR 能力及相关请求（设备支持时） |
| T4-HW-06 | 30 分钟以上连续捕获 | 记录数量、队列、背压和内存统计完整 |

### 6.2 测量仪表测试

| 编号 | 测试内容 | 预期结果 |
|---|---|---|
| T4-MEAS-01 | VBUS 电压/电流 | 与设备返回值一致 |
| T4-MEAS-02 | OVP/OCP 阈值读取 | 单位和数值正确 |
| T4-MEAS-03 | OVP/OCP 设置 | 设置后读回一致 |
| T4-MEAS-04 | CC1/CC2 四路测量 | DUT/USDS 映射正确 |
| T4-MEAS-05 | Accumulator 计时/电荷/能量 | 显示值与设备一致 |
| T4-MEAS-06 | 设备断开 | 显示 Stale/Unavailable，不保留正常状态 |
| T4-MEAS-07 | 轮询与捕获并行 | 不出现 SCPI 请求重叠或响应错位 |

### 6.3 Timestrip 与日志测试

| 编号 | 测试内容 | 预期结果 |
|---|---|---|
| T4-LOG-01 | 消息时间轴 | 消息起止时间和顺序正确 |
| T4-LOG-02 | 模拟曲线 | VBUS/IBUS 与设备时间戳正确关联 |
| T4-LOG-03 | 时间轴选择消息 | Message Log 定位正确 |
| T4-LOG-04 | Message Log 选择消息 | Timestrip 定位正确 |
| T4-LOG-05 | 多条件过滤 | 过滤结果正确，原始数据不变 |
| T4-LOG-06 | Annotation/Comment | 重启后仍能恢复 |
| T4-LOG-07 | 实时 CSV | 持续写入且文件可重新读取 |
| T4-LOG-08 | 历史查询 | 时间范围和分页结果正确 |
| T4-LOG-09 | 大规模日志 | 查询和滚动不阻塞主线程 |

### 6.4 Trigger / Sink Control 测试

| 编号 | 测试内容 | 预期结果 |
|---|---|---|
| T4-CTL-01 | Trigger 状态读取 | 与设备状态一致 |
| T4-CTL-02 | Trigger 事件类型设置 | 设备读回一致 |
| T4-CTL-03 | Sender/Message Type Filter | 触发条件与配置一致 |
| T4-CTL-04 | 外部 Sync 输出 | 示波器测量极性和脉宽符合配置 |
| T4-CTL-05 | Sink PDO 列表 | 与 Source 通告一致 |
| T4-CTL-06 | Sink 请求越界 | GUI 阻止发送 |
| T4-CTL-07 | Sink 请求成功 | 设备状态和协议响应确认协商结果 |
| T4-CTL-08 | 固件不支持命令 | 控件禁用并显示 Not Supported |

---

## 7. 数据完整性与性能要求

第三阶段报告记录的 12,000 条构造记录回放约 6.01 秒，表格保留 4,000 条、滚出 8,000 条；大文件回放时 20 ms 主线程定时器最大采样间隔为 60.8 ms，进程工作集从 114.2 MiB 增至采样峰值 126.1 MiB。第四阶段应在此基础上补充可重复的性能基线。

必须统计：

- 设备侧捕获队列计数（若固件提供）。
- 主机成功读取的记录数。
- 主机成功解析的记录数。
- 主机写入原始捕获文件的记录数。
- GUI 表格当前显示数和滚出数。
- 主机待处理队列当前深度、峰值和背压次数。
- 主机缓存溢出/丢弃数。
- 解析异常、CRC Invalid 和 CRC Unavailable 数。
- 日志写入失败数。
- 回放速度、导出耗时、内存峰值和 UI 定时器延迟。

**重要限制：** 如果固件不提供硬件捕获溢出/丢包计数，主机只能证明已经收到的数据是否完整归档，不能证明 USB-C 物理链路没有漏捕。报告必须区分“主机无丢弃”和“硬件物理零丢帧”。

---

## 8. 推荐实施顺序与工期

建议按依赖关系实施，不要同时开发所有仪表。

| 顺序 | 工作项 | 预计时间 | 优先级 |
|---|---|---:|---|
| 1 | P4.0 基线同步和命令能力审查 | 1～2 天 | P0 |
| 2 | P4.1 第三阶段实机收尾 | 2～4 天 | P0 |
| 3 | P4.2 Device Status 与模拟测量仪表 | 3～4 天 | P1 |
| 4 | P4.3 Timestrip 与模拟曲线 | 3～4 天 | P1 |
| 5 | P4.4 Message Log 增强和历史日志 | 2～4 天 | P1 |
| 6 | P4.5 Trigger 仪表 | 2～3 天 | P1 |
| 7 | P4.6 Sink Control（条件实现） | 2～4 天 | P2 |
| 8 | P4.7 仪表架布局增强 | 2～4 天 | P2 |
| 9 | P4.8 联调与验收 | 2～3 天 | P0 |

核心测量、时间轴、日志和触发功能预计约 **15～22 个工作日**；若同时纳入 Sink Control 和可定制仪表架，预计约 **19～30 个工作日**。以上估算以固件已经具备对应 SCPI 命令为前提，不包含新增固件功能开发时间。

---

## 9. 本阶段交付物

| 编号 | 交付物 | 内容 |
|---|---|---|
| D4-01 | DRPD 功能差距矩阵 | DRPD 原版能力、本项目现状、证据和优先级 |
| D4-02 | 固件命令能力清单 | 命令、参数、返回值、固件版本和实测状态 |
| D4-03 | 实机收尾报告 | 双设备、物理拔出、EPR 和长时间捕获结果 |
| D4-04 | TelemetryService | 模拟测量采集和状态管理 |
| D4-05 | 测量仪表 | Device Status、VBUS、CC Lines、Accumulator |
| D4-06 | Timestrip | 消息和模拟采样统一时间轴 |
| D4-07 | LogService | 历史日志、过滤、标注和导出 |
| D4-08 | Trigger 仪表 | 触发配置和状态显示 |
| D4-09 | Sink Control | 条件实现的 PDO 请求和状态回读 |
| D4-10 | 仪表架布局 | 默认布局、面板管理和布局持久化 |
| D4-11 | 自动化测试 | Service、GUI、实机和性能测试 |
| D4-12 | 第四阶段验收报告 | 已完成能力、实机证据、性能边界和遗留问题 |

---

## 10. 开发约束与风险控制

1. GUI 框架固定使用 PySide6，不引入 PyQt6。
2. USB-PD 设备继续使用 USB CDC 和 DRPD 原版固件数据帧，不切换为 WebUSB/USBTMC。
3. 所有 SCPI 请求必须通过同一设备会话的串行调度器，不允许并发破坏无标签响应流。
4. 不重写第二阶段已验收的协议解析器；GUI 只消费解析结果。
5. VBUS/IBUS 实测值与 PDO/RDO 通告/请求值必须分开显示。
6. 所有测量数据必须显示来源、单位、时间戳和有效性。
7. Sink Control 只允许在固件能力和硬件条件确认后启用，第一版不做自动扫描。
8. Trigger 和外部 Sync 必须用真实设备回读和示波器/逻辑分析仪验证。
9. 工作区切换不能意外停止后台捕获或电子负载任务。
10. DRPD 上游仅作为功能参考；不得未经许可直接复制其前端源码、图标、样式、图片或文档内容。若复用代码或资源，先核对对应许可证和义务。

---

## 11. DRPD 参考资料

以下资料用于确认 DRPD 原版功能范围和命令能力。上游代码/文档可能持续变化，正式开发前应固定参考版本或提交号。

- [DRPD GitHub 仓库](https://github.com/T76-org/drpd)
- [DRPD Datasheet：产品、协议、测量、Trigger、Sink 和软件功能](https://github.com/T76-org/drpd/blob/main/media/datasheet.md)
- [Rack and Instruments：仪表架、添加/移除、拖动、尺寸调整和布局保存](https://github.com/T76-org/drpd/blob/main/frontend/docs/rack-instruments.md)
- [DRPD Device Guide：命令组、设备状态和事件](https://github.com/T76-org/drpd/blob/main/frontend/docs/drpd-device.md)
- [DRPD Logging：模拟采样、消息日志、历史存储和导出](https://github.com/T76-org/drpd/blob/main/frontend/docs/drpd-logging.md)
- [DRPD VBUS 仪表实现](https://github.com/T76-org/drpd/blob/main/frontend/src/features/rack/instruments/DrpdVbusInstrumentView.tsx)
- [DRPD Sink Control 仪表实现](https://github.com/T76-org/drpd/blob/main/frontend/src/features/rack/instruments/DrpdSinkControlInstrumentView.tsx)
- [DRPD Trigger 仪表实现](https://github.com/T76-org/drpd/blob/main/frontend/src/features/rack/instruments/DrpdTriggerInstrumentView.tsx)
- [DRPD Message Log 仪表实现](https://github.com/T76-org/drpd/blob/main/frontend/src/features/rack/instruments/DrpdUsbPdLogInstrumentView.tsx)
- [DRPD Timestrip 仪表实现](https://github.com/T76-org/drpd/blob/main/frontend/src/features/rack/instruments/DrpdTimeStripInstrumentView.tsx)
- [DRPD Analog Monitor 命令组](https://github.com/T76-org/drpd/blob/main/frontend/src/lib/device/drpd/analogMonitor.ts)
- [DRPD Sink 命令组](https://github.com/T76-org/drpd/blob/main/frontend/src/lib/device/drpd/sink.ts)
- [DRPD Trigger 命令组](https://github.com/T76-org/drpd/blob/main/frontend/src/lib/device/drpd/trigger.ts)
- [DRPD VBUS 命令组](https://github.com/T76-org/drpd/blob/main/frontend/src/lib/device/drpd/vbus.ts)

---

## 12. 阶段最终目标

第四阶段完成后，软件应从“具备 USB-PD 捕获、解码、诊断和回放能力的上位机”，进一步发展为“具备协议事件与电气测量联合分析能力的 USB-PD 测试平台”。

推荐最终交互流程：

1. 连接 DRPD 和电子负载。
2. 在 USB PD 工作区观察设备状态、VBUS/IBUS、CC Lines 和累计测量。
3. 启动捕获并在 Message Log 中查看协议消息。
4. 在 Timestrip 中关联协议事件和模拟测量曲线。
5. 使用 Trigger 捕获特定消息、协议错误或测量事件。
6. 通过 Message Detail 查看 PDO/RDO、VDM/VDO、Extended/EPR 和原始字节。
7. 保存原始捕获、历史日志和用户标注，支持离线回放与导出。
8. 在需要进行 Source 兼容性测试时，再启用经过安全审查的 Sink Control。

本阶段优先完成真实测量、时间关联和可靠捕获，不以“功能数量与 DRPD 完全一致”为验收目标。对于固件尚未支持或当前硬件不具备的功能，必须明确记录为未支持或后续扩展。
