# 5 分钟上手

本页只介绍最短可用路径。高级校准、远程快照和历史评测不是首次使用的前置条件。

## 1. 安装

在仓库根目录执行：

```bash
python -m pip install -e "./skill/daily-trade-radar[docx]"
daily-trade-radar --help
```

Codex 用户也可以直接通过 `$skill-installer` 安装 `skill/daily-trade-radar` 目录。

## 2. 创建一个小范围试点

默认配置只覆盖中国，不自动加入任何平台：

```bash
daily-trade-radar init --directory my-radar
```

更具体的单品试点：

```bash
daily-trade-radar init --directory router-pilot --name "Router Pilot" \
  --region "European Union" --product "wireless router" --hs-code 851762 \
  --platform Amazon --sku ROUTER-001
```

检查生成的 `profile.json`，确认地区、产品、HS 编码、平台、时区和输出语言。

## 3. 生成研究合同

```bash
daily-trade-radar run --profile my-radar/profile.json
```

首次运行会写入研究计划、平台采集清单和运行状态，并停在：

```json
{"state": "research_required"}
```

这不是错误。接下来需要 Codex 或研究员打开官方来源，核对发布日期、生效日期、适用范围、义务和业务影响，并整理为已复核事件 JSON。

## 4. 校验并生成日报

```bash
daily-trade-radar validate reviewed-events.json --require-language zh-CN
daily-trade-radar run --profile my-radar/profile.json --events reviewed-events.json
```

默认生成 Markdown，并根据配置写入语言检查、去重和告警预览等审计文件。不要在尚未人工核验时使用 `--send-alerts`。

## 5. 查看结果

- [完整中文日报示例](../examples/sample-radar.md)
- [日报预览图](../examples/sample-radar-preview.png)
- `output/radar.md`：人类阅读版本
- `output/deduplicated.json`：事实数据和审计依据
- `output/language-quality.json`：语言一致性检查
- `output/alerts.json`：告警预览

## 常见下一步

```bash
# 查看平台注册表
daily-trade-radar platforms --json

# 生成来源覆盖仪表盘
daily-trade-radar coverage-dashboard --format html --output source-coverage.html

# 检查公开来源访问健康度
daily-trade-radar doctor --json --output source-health.json
```

独立运行的能力限制见 [standalone-cli.md](standalone-cli.md)，其余命令见 [advanced.md](advanced.md)。
