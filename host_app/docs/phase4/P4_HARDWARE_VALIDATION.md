# P4.1 第三阶段实机收尾记录

2026-11-27 在 COM15 上使用固件 `1.0.0-beta.1` 的 DRPD 复刻板执行首轮试采。测试使用实际 USB PD 工作区、串口工作线程、捕获表格与文件导出。设备处于 `PE_SNK_READY`，每 5 秒查询一次 Source Capabilities。

| 项目 | 65 秒试采结果 |
| --- | --- |
| 捕获持续时间 | 65.06 s |
| 主机读取 / 分析 / 原始归档 / 文件读回 | 131 / 131 / 131 / 131 |
| 完整性核验 | 按接收顺序对每条载荷的长度和原始字节计算 SHA-256，两端摘要一致 |
| 表格保留 / 滚出 | 131 / 0 |
| 设备队列峰值 / 主机待交付峰值 / 主机背压 | 8 / 8 / 3 次 |
| CRC Invalid / CRC Unavailable / 诊断 | 0 / 1 / 2 |
| 捕获读取 / 分析异常 / 日志写入失败 | 0 / 0 / 0 |
| 分析总耗时 | 86.61 ms |
| 原始文件 / CSV 导出 | 22.45 ms / 64.87 ms，含测试驱动等待导出通知的轮询间隔 |
| 主线程 20 ms 定时器最大间隔 | 31.73 ms |
| Python 追踪分配峰值 | 1,264,967 B |
| 停止后状态 | 捕获 OFF，设备队列与主机待交付队列均为 0 |

原始捕获、CSV 与性能 JSON 保存在本机仓库根目录的 `tmp/p4-capture-20261127-104438/`。另一次 6 秒 CDC 验证在同一连接交替收到 29 组模拟测量和 30 条二进制捕获记录，停止后回读 OFF。第四阶段当前代码通过 168 项全量回归和 118 项纯 Python 回归。

固件提供设备队列瞬时深度，物理漏捕总数不可观测。本次完整性结论覆盖主机已接收记录。

| 用例 | 已验证 | 后续实机验收 |
| --- | --- | --- |
| T4-HW-01 / 02 双设备并行 | 枚举到 COM15 DRPD 与 COM1/COM2 虚拟端口 | 接入电子负载 CDC 后，验证负载采样/控制和 DRPD 捕获同时运行 |
| T4-HW-03 / 04 捕获时拔出及重连 | 模拟 CDC 覆盖意外移除及重连 | 捕获运行时物理拔出，重新插入后核对新会话与历史边界 |
| T4-HW-05 EPR | 复刻板 EPR 配置回读 ON，已有构造回放样本 | 使用支持 EPR 的 Source、线缆和 DUT 保存真实协商 |
| T4-HW-06 连续捕获 | 65 秒前置试采通过，300.06 秒主机基线捕获通过 | 本轮验收目标为 5 分钟，综合版本结果见第四阶段验收报告 |

从 `host_app` 目录运行，输出目录需要是新目录。省略 `--inquiry-interval` 时被动捕获，提供正数时只在现有 Sink 会话已就绪期间发送 Source Capabilities 查询。

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
$env:PYTHONPATH = '.'
python tests/drpd_long_capture.py COM15 ../tmp/p4-capture-long --seconds 300 --inquiry-interval 5
```

[固件命令矩阵](P4_DRPD_COMMAND_MATRIX.md) · [架构更新](P4_ARCHITECTURE_UPDATE.md) · [第四阶段验收报告](P4_ACCEPTANCE_REPORT.md)
