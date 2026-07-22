# Daily Trade Radar

Daily Trade Radar is a Chinese-first Codex Skill for researching, verifying, deduplicating, prioritizing, and writing actionable foreign-trade intelligence. It is designed for cross-border e-commerce teams operating on Amazon, TikTok Shop, Temu, AliExpress, Jumia, and other global marketplaces.

It monitors official trade-policy, customs, export-control, sanctions, tariff, tax, product-compliance, logistics, and marketplace-rule sources. The default deliverable is Markdown backed by validated JSON; a Word template is included for optional formal reports. Coverage will continue expanding to more countries, industries, and marketplace platforms.

> Status: `v0.1.0-alpha`. Use this project as an operational research aid, not as legal, tax, customs, or sanctions advice.

## 中文简介

每日外贸雷达是一套以中文用户为主的 Codex Skill，面向外贸企业和跨境电商团队，用于检索、核验、去重并输出可执行的外贸情报日报。覆盖 Amazon、TikTok Shop、Temu、AliExpress（速卖通）、Jumia 等平台，并将持续扩展至 Shopee、Lazada、eBay、Walmart Marketplace 及更多全球渠道。

它会监测贸易政策、海关合规、出口管制、制裁、关税税务、产品合规、国际物流和平台规则，区分今日新增、今日生效、临近截止、持续关注和待核实事项，并为每条事件提供风险等级、业务影响、行动建议与官方来源。

## What it does

- Searches current primary and official sources.
- Separates publication dates, effective dates, and deadlines.
- Scores events by force, exposure, urgency, consequence, and evidence.
- Deduplicates findings against a previous radar.
- Keeps material updates for human review.
- Validates a stable UTF-8 JSON event format.
- Generates a consistent Chinese Markdown radar.
- Includes a privacy-scrubbed DOCX template for optional formal output.

## Repository layout

```text
skill/daily-trade-radar/   The installable Skill
examples/                  Offline example input and output
tests/                     Standard-library workflow tests
.github/workflows/         GitHub Actions validation
```

The repository wrapper contains user documentation and tests. The installable Skill folder itself stays focused on runtime instructions and resources.

## Install

Codex can install skills from other repositories through `$skill-installer`. Ask Codex:

```text
Use $skill-installer to install the daily-trade-radar skill from
https://github.com/NextBeforeAnd/daily-trade-radar/tree/main/skill/daily-trade-radar
```

For manual installation, copy `skill/daily-trade-radar` to one of Codex's discovery locations:

- User scope: `$HOME/.agents/skills/daily-trade-radar`
- Repository scope: `<repo>/.agents/skills/daily-trade-radar`

Codex detects Skill changes automatically. Restart Codex if the Skill does not appear.

## Use

Invoke it explicitly:

```text
Use $daily-trade-radar to generate today's Chinese foreign-trade radar.
Focus on the EU, United States, China export controls, and Amazon.
Compare it with yesterday's report and cite primary official sources.
```

Or provide a narrower operating brief:

```text
Use $daily-trade-radar to monitor Germany and France for LED lighting products,
HS 9405, Amazon EU, product safety, customs duties, and marketplace rules.
```

Useful inputs include target countries, products, HS codes, platforms, priority themes, timezone, language, and the previous report.

## Output model

```text
official research
      ↓
current.json
      ↓ validate + deduplicate
deduplicated.json
      ↓
daily-trade-radar.md
      └─ optional DOCX/PDF
```

JSON is the source of truth. Markdown is the default human-readable output. DOCX or PDF should be generated only when formal circulation or fixed-layout archiving is required.

Set the root JSON field `language` to `zh-CN` for Chinese output or to `en`/`en-US` for English output. Event content is rendered as supplied; research should therefore write event fields in the requested output language.

## Offline script workflow

The validation, deduplication, and Markdown scripts use only the Python standard library. Word output uses `python-docx`; install it with:

```bash
python -m pip install -r requirements.txt
```

Run the workflow:

```bash
python skill/daily-trade-radar/scripts/validate_events.py examples/current.json
python skill/daily-trade-radar/scripts/deduplicate.py examples/current.json --previous examples/previous.json --output deduplicated.json
python skill/daily-trade-radar/scripts/build_markdown.py deduplicated.json --output daily-trade-radar.md
python skill/daily-trade-radar/scripts/build_docx.py deduplicated.json --output daily-trade-radar.docx
```

The scripts do not scrape the web. Codex performs research with available browsing tools, writes normalized JSON, and then uses the scripts for deterministic validation, comparison, and rendering.

## Quality and safety

- Main-table events require a direct primary source.
- Search-result snippets are not accepted as evidence.
- Unconfirmed items stay out of the main action table.
- Applicability must not be assumed when product, HS code, market, or channel data is missing.
- Reports must disclose the search cutoff, timezone, scope, and coverage gaps.
- Always verify consequential decisions with qualified legal, customs, tax, or sanctions professionals.

## Development

Run the offline test suite:

```bash
python -m unittest discover -s tests -v
```

## Follow / 关注

外贸与跨境电商动态、实操笔记及项目更新：

[老Hai外贸跨境笔记（@HaiNengGao）](https://x.com/HaiNengGao)

## License

[MIT](LICENSE)
