# M7 验收基线

| 项目 | 基线 |
| --- | --- |
| 日期与时区 | 2026-11-26，Asia/Shanghai |
| Git 分支 | `feature/usb-pd-decoder` |
| M7 开始前远端基线 | M4/M5 提交 `14feb218080bca4177313c9dad6a2f86b1028b9a`，前一阶段已验证 GitHub 分支 |
| M6 本地冻结基线 | `2ecbd84473ff2223013f11aec737594cbd50e252` |
| 起始工作区 | M6 代码、测试、fixture 与报告起初待提交。M7 的代码回归从已独立提交的 M6 版本开始 |
| 上位机版本 | `0.3.1`，USB-PD 第二阶段 M7 是本次验收版本标记 |
| 运行环境 | Windows NT 10.0.26200.0 x64，Intel Core i5-1340P，16 个逻辑处理器，Python 3.13.2 |
| M6 回归 | 144 项全量测试、99 项无 PySide6 的协议测试通过 |
| 实机 | DRPD 复刻板，`COM15`，固件 `1.0.0-beta.1`，10 ns 采样周期，DUT 为酷态科 10 号充电器 Mini |

M6 性能负载用 4,000 次 260 B 重组。每次发送 10 个数据块和 9 个反向请求，共 76,000 帧，交替使用 SOP 和 SOP′。数据向量预先构造，设备时间每帧推进 200 µs。每次核对完整字节并检查最终活跃和缓存状态。M6 记录为 16,053 帧/s、62.29 µs/帧、214.5 KiB/s 有效载荷及 29,721 B 的同规模 `tracemalloc` 峰值。 [M6 验收报告](../DRPD_第二阶段_M6_验收报告.md)

建议门槛为吞吐不低于 14,448 帧/s、均值不高于约 69.2 µs/帧、有效载荷不低于 193.05 KiB/s、同规模 Python 分配峰值不高于 37,151 B。源字节缓存和活动传输都须归零。阈值用于本项目软件回归。

从 `host_app` 复跑性能，脚本默认对完全相同的负载计时三次，单独进行峰值跟踪，然后执行补充场景。

```powershell
python -S tests/protocol_benchmark.py --output ../tmp/m7/performance.json
```

完整测试、纯协议、压力和性能执行方式见 [README](../README.md)。实测结果见 [M7 性能报告](M7_PERFORMANCE_REPORT.md)。
