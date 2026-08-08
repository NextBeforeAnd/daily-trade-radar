# 高级功能与命令导航

首次使用请从 [Quickstart](quickstart.md) 开始。本页用于需要扩展、审计或长期运营的团队。

## 日常核心命令

| 目标 | 命令 |
|---|---|
| 创建试点配置 | `daily-trade-radar init` |
| 执行配置化流程 | `daily-trade-radar run` |
| 校验报告 | `daily-trade-radar validate` |
| 去重 | `daily-trade-radar deduplicate` |
| 生成 Markdown/DOCX | `daily-trade-radar markdown` / `docx` |
| 检查语言 | `daily-trade-radar language-check` |
| 来源覆盖仪表盘 | `daily-trade-radar coverage-dashboard` |

## 来源与平台运营

- `platforms` / `platforms scaffold`：查看或扩展平台注册表；
- `plan`：生成和验证研究合同；
- `acquisition`：生成采集任务、回执和覆盖账本；
- `doctor`：检查来源配置、公开访问健康度和运行后状态；
- `snapshot` / `snapshot-audit`：保存与审计公开页面变化。

参考文档：

- [研究计划](../skill/daily-trade-radar/references/research-planning.md)
- [采集工作流](../skill/daily-trade-radar/references/acquisition.md)
- [平台监控](../skill/daily-trade-radar/references/platform-policy-monitoring.md)
- [来源健康](../skill/daily-trade-radar/references/source-health.md)
- [快照存储](../skill/daily-trade-radar/references/snapshot-storage.md)

## 研究历史与钻取

- `discover`：整理尚未确认的早期线索；
- `library`：将已验证日报写入 SQLite 历史库；
- `drill`：针对一个事件生成后续研究计划。

参考 [历史库与钻取](../skill/daily-trade-radar/references/history-and-drill.md)。

## 实验性：校准与发布评测

`calibrate`、`calibration-scaffold`、`calibration-update`、`calibration-promote`、`calibration-rollback`、`evaluation-scaffold`、`evaluate` 和 `evaluate-history` 面向已经积累独立人工标签的团队。

这些能力不是日常生成日报的前置条件。没有独立标签、足够样本和人工审查者时，不应据此修改评分阈值或宣传模型质量。

- [评分校准](../skill/daily-trade-radar/references/scoring-calibration.md)
- [发布评测](../skill/daily-trade-radar/references/evaluation.md)

## 实验性：Git 与 S3 快照

日常单机使用默认 filesystem 或 SQLite 即可。Git 和 S3 后端适合有明确审计、并发或共享存储需求的团队，不建议首次试点直接启用。
