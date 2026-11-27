# P4.0 架构更新

第四阶段沿用 [第三阶段架构](../phase3/P3_ARCHITECTURE.md) 和 [GitHub 基线 46d7945](https://github.com/benqiamzi/electronic_load/commit/46d79451f7f6bad3e0df9fb467f18050f5625fe0)。PySide6 工作区继续消费现有协议解析结果，USB CDC 保持原有文本与二进制响应格式。

## CDC 调度与仪表范围

- 每台 DRPD 只由 `DeviceService` 的工作线程持有串口。测量、设备状态、捕获和控制共用该线程上的 `DrpdProtocolClient`，任意时刻最多一个等待响应的 SCPI 请求。
- `CaptureClient` 默认每轮读取最多 32 条，经 GUI 回执恢复后续轮询。低频测量优先使用一条 `MEAS:ALL?`。计划以 500 ms 为初始测量间隔，至多保留一条未完成轮询，高负载或停止排空时主动让出队列。角色和保护配置用较低频率刷新。实际吞吐与轮询并行效果在 P4.2 实机验证。
- COM15 上已使用同一 `DrpdProtocolClient` 交替发出文本查询和读取二进制捕获，约 6 秒读回 29 个 `MEAS:ALL?` 响应及 30 条捕获记录，未出现错位或超时。
- 响应超时或流失步由现有传输层关闭会话。设备断开、超时或解码失败需更新仪表有效性。按命令定义解析返回字段，文本 SCPI 负数错误响应与合法的负电流按各查询的响应格式识别。
- 默认布局沿用 USB PD 工作区。设备连接页显示 Device Status，测量页显示 VBUS/IBUS/功率及保护、DUT/USDS 四路 CC 和 Accumulator，实时捕获页继续显示消息列表和已有详情。Trigger 与 Timestrip 随后按里程碑接入。
- 测量样本包含设备 µs 时间戳、主机接收时间、来源和有效性。保护设置发送后读回，Accumulator Reset 经用户确认并读取结果。Sink 操作须满足 P4.6 的硬件条件。

## 完整性与时间基准

- `BUS:CC:CAP:COUNT?` 测量设备队列深度。环形缓冲区可能覆盖未读取记录，当前命令集没有可核对的累计溢出或物理漏捕计数。主机验收以已收记录、分析结果和原始归档逐项核对。
- 主机读取、分析异常、CRC invalid/unavailable、刷盘成功记录数、写入失败、待交付批次深度和 GUI 背压分别统计。表格滚出属于显示窗口变化，完整性以原始文件读回为准。
- 捕获与模拟采集的固件时间戳来自板载计时器，Timestrip 在同一连续会话内按设备 µs 对齐；主机接收时间用于显示和排障。重连、采样断档和时钟回退以边界区分，无真实样本的区间留空。
- 原始 `.drpd` v1 继续用于无损回放。版本化 SQLite 索引记录会话、可查询摘要、模拟采样和标注。以会话 ID 与原始记录序号关联，索引重建依赖原始文件和采样记录。历史查询及导出在工作线程执行。

[固件命令与实机回读](P4_DRPD_COMMAND_MATRIX.md) · [功能差距矩阵](P4_FEATURE_GAP_MATRIX.md) · [实机收尾记录](P4_HARDWARE_VALIDATION.md)
