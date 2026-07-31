# Daily Trade Radar

Daily Trade Radar is a Chinese-first Codex Skill for researching, verifying, deduplicating, prioritizing, and writing actionable foreign-trade intelligence. It is designed for cross-border e-commerce teams operating on Amazon, TikTok Shop, Temu, AliExpress, Jumia, Shopify and other global marketplaces.

It monitors official trade-policy, customs, export-control, sanctions, tariff, tax, product-compliance, logistics, and marketplace-rule sources. The default deliverable is Markdown backed by validated JSON; a Word template is included for optional formal reports. Coverage will continue expanding to more countries, industries, and marketplace platforms.

> Development version: `v0.3.0` (alpha quality). Use this project as an operational research aid, not as legal, tax, customs, or sanctions advice.

See [CHANGELOG.md](CHANGELOG.md) for development updates.

## 中文简介

每日外贸雷达是一套以中文用户为主的 Codex Skill，面向外贸企业和跨境电商团队，用于检索、核验、去重并输出可执行的外贸情报日报。当前注册表覆盖 Amazon、TikTok Shop、Temu、AliExpress（速卖通）、Shopify、Jumia、Shopee、Lazada、eBay 和 Walmart Marketplace；各平台的可验证来源深度会继续扩展。

它会监测贸易政策、海关合规、出口管制、制裁、关税税务、产品合规、国际物流和平台规则，区分今日新增、今日生效、临近截止、持续关注和待核实事项，并为每条事件提供风险等级、业务影响、行动建议与官方来源。

## What it does

- Searches current primary and official sources.
- Separates publication dates, effective dates, and deadlines.
- Uses the previous report cutoff as the next reporting-window start, or a trailing 24-hour window when no prior report exists.
- Preserves exact event timestamps and source timezones when official sources provide them.
- Records force, exposure, urgency, consequence, and evidence as an auditable score breakdown, then validates the total and risk level.
- Audits scoring against independently reviewed historical labels with sample gates, reviewer-agreement metrics, confusion matrices, and non-binding candidate thresholds.
- Deduplicates findings against a previous radar.
- Uses stable-ID-first, scope-aware, one-to-one weighted matching and retains low-confidence similarities for review instead of deleting them.
- Separates material policy changes from effective-date/deadline refreshes and editorial rewrites.
- Validates a stable UTF-8 JSON event format.
- Generates a consistent Chinese Markdown radar.
- Includes a privacy-scrubbed DOCX template for optional formal output.
- Applies dedicated monitoring routes for TikTok Shop, Temu, Shopify, Jumia, Amazon, and AliExpress.
- Grades platform source depth and requires every missing update, current-policy, or dashboard route to carry an explicit known-gap reason.
- Stores normalized public-page snapshots, compares them with the prior capture, and records machine-readable change status plus saved text diffs.
- Distinguishes authentication-required pages from pages blocked by access controls or anti-bot measures.
- Produces a machine-readable platform coverage ledger for public updates, current-policy pages, and authenticated dashboard checks.
- Extracts marketplace changes into a structured platform/market/program analysis and owner-level action checklist.
- Runs a mandatory seven-day marketplace discovery pass, records every opened source URL, and rejects unsupported "checked" claims.
- Builds registry-driven acquisition manifests and evidence receipts, with bounded HTTP retries, RSS/Atom/sitemap parsing, public-content caching, and automatic draft coverage ledgers.
- Integrity-checks manifest/task identities, binds receipts to their exact routes, preserves immutable receipt history, and prevents failed or expired access results from becoming reusable cache hits.
- Uses an available signed-in browser session for read-only Seller Center checks and retains credible unresolved platform leads in the watchlist.

## Repository layout

```text
skill/daily-trade-radar/   The installable Skill and Python package
examples/                  Offline example input and output
tests/                     Standard-library workflow tests
.github/workflows/         GitHub Actions validation
```

The repository wrapper contains user documentation and tests. Inside the installable Skill, deterministic logic lives under `src/daily_trade_radar`; the files under `scripts/` are backward-compatible entry points for existing Skill commands.

```text
skill/daily-trade-radar/
  src/daily_trade_radar/
    models.py
    scoring.py
    validation.py
    deduplication.py
    platforms/
      registry.py
      data/                   One JSON playbook per platform
    snapshots/
    acquisition/              Manifests, receipts, adapters, cache, and coverage conversion
    renderers/
    cli.py
  scripts/                  Backward-compatible thin wrappers
  assets/
  references/
  pyproject.toml
```

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

For marketplace monitoring, provide the seller market and operating model when possible—for example, TikTok Shop US local seller, Temu semi-managed, Shopify Managed Markets, or Jumia Nigeria Vendor Center. The workflow does not generalize a rule across markets or seller programs without evidence.

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

Marketplace-policy events can also carry a `platform_policy` object and `action_items` array. These fields preserve the verified seller scope, before/after state, enforcement consequence, action owner, time horizon, and completion evidence while keeping the legacy top-level `action` summary compatible with existing reports.

Every event includes `score_breakdown` with five 0-2 dimensions. Its sum must equal `score`, and the validator derives the expected risk band. A level outside the normal band requires a structured `level_override` reason; evidence 0 always remains `watch`.

Set the root JSON field `language` to `zh-CN` for Chinese output or to `en`/`en-US` for English output. Event content is rendered as supplied; research should therefore write event fields in the requested output language.

## Offline script workflow

The validation, deduplication, and Markdown scripts use only the Python standard library. Word output uses `python-docx`; install it with:

```bash
python -m pip install -r requirements.txt
```

For package development, install the Skill in editable mode with the Word extra:

```bash
python -m pip install -e "skill/daily-trade-radar[docx]"
daily-trade-radar validate examples/current.json
```

The package also supports `python -m daily_trade_radar`. Commands are `validate`, `deduplicate`, `snapshot`, `snapshot-audit`, `markdown`, `docx`, `platforms`, `acquisition`, `calibrate`, `calibration-scaffold`, `calibration-update`, `calibration-promote`, `calibration-rollback`, `evaluation-scaffold`, `evaluate`, and `evaluate-history`. Direct `scripts/*.py` usage remains supported and does not require package installation.

List the installed marketplace registry:

```bash
python -m daily_trade_radar platforms
python -m daily_trade_radar platforms --json
```

Platform coverage is data-driven. The bundled registry includes Amazon, TikTok Shop, Temu, Shopify, Jumia, AliExpress, Shopee, Lazada, eBay, and Walmart Marketplace. To add another registered channel, add one UTF-8 JSON file under `src/daily_trade_radar/platforms/data/` with names and aliases, seller markets, programs, official route starting points, dashboard checks, applicability dimensions, policy areas, and cautions. The validator discovers it automatically. Unregistered channels remain usable only when their platform-policy record is marked `custom` and requires official-entry verification.

Each route also declares its stable ID, supported markets, access mode, evidence role, and verification status. `daily-trade-radar platforms --json` returns a `source_depth` assessment. Missing source types must be declared as known gaps, so a login-only platform cannot appear as fully covered merely because one Seller Center URL exists.

Calibrate the deterministic scoring bands only with independently reviewed labels:

```bash
daily-trade-radar calibration-scaffold evaluation/drafts/manifest.json --output evaluation/calibration-review-scaffold.json
daily-trade-radar calibration-scaffold evaluation/drafts/manifest.json --existing evaluation/calibration-review-scaffold.json --output evaluation/calibration-review-scaffold.next.json --diff-output evaluation/calibration-review-scaffold.diff.json --require-calibration-ready
daily-trade-radar calibrate reviewed-history.json --minimum-samples 20 --minimum-per-level 3 --output calibration-report.json
```

The scaffold deduplicates stable event IDs across runs and also performs conservative cross-ID semantic clustering. Exact official-page/date matches, shared regulatory identifiers, and corroborated authority/date/title anchors can be merged automatically; ambiguous reused URLs are withheld in `semantic_duplicate_review_queue` for human adjudication. Cross-run and cross-alias level conflicts remain excluded. The scaffold carries over independently reviewed levels and deliberately blanks every score dimension. Generated scores are excluded. Calibration reports human agreement, label conflicts, score distributions, current-rule accuracy/macro-F1, and a non-binding candidate threshold set. They never edit scoring rules automatically.

For later runs, pass the reviewed worksheet with `--existing` and write to a new output path. The
incremental merge preserves complete or partial human scores only when the reviewed level and evidence
fingerprint are unchanged. New events stay blank; changed evidence or labels are reset and listed in
`incremental_merge.review_queue`; existing-only manual observations are retained. The audit counts make
every preservation, reset, addition, and retention explicit.

The merged worksheet embeds `incremental_diff`; `--diff-output` writes the same machine-readable report
separately. It lists every preserved, new, reset, conflicting, and retained event. Its
`calibration_gate` allows calibration only when all score breakdowns are complete and no semantic review
item remains. `--require-calibration-ready` returns exit code `3` after writing both artifacts when human
review is still required, and the `calibrate` command also rejects a blocked incremental worksheet.

Run the complete incremental workflow into a new, immutable output directory:

```bash
daily-trade-radar calibration-update evaluation/drafts/manifest.json \
  --existing evaluation/calibration-review-scaffold.json \
  --previous-calibration evaluation/calibration-report.json \
  --decision-record evaluation/calibration-readiness.json \
  --output-dir evaluation/updates/2026-07-31
```

The command stages the bundle and then publishes the directory as one unit. A ready run contains the
updated scaffold, diff, calibration report, and update summary. A blocked run returns exit code `3` and
omits the calibration report; a ready run below the calibration sample gate returns `4`. Existing output
directories are never overwritten. Calibration comparisons ignore metadata-only dataset-hash changes,
and a prior human threshold decision is retained only when decision-relevant metrics are unchanged.

After human review, explicitly promote a completed update into the formal baseline:

```bash
daily-trade-radar calibration-promote evaluation/updates/2026-07-31 \
  --baseline-dir evaluation \
  --backup-dir evaluation/backups/promotion-2026-07-31 \
  --decision retain_current_thresholds \
  --reviewed-by "workspace owner" \
  --reason "Boundary evidence is still insufficient." \
  --promoted-at "2026-07-31T18:00:00+08:00"
```

Promotion independently recomputes calibration, verifies cross-artifact identity and hashes, requires
the incremental and sample gates, locks the formal baseline, publishes a verified backup, and checks the
new files after writing. Any write failure triggers restoration from that backup. `defer` returns `3`
without changing the baseline. `accept_candidate_thresholds` is refused unless those thresholds already
exist in the tested runtime rules; promotion never edits scoring code or silently adopts a threshold.

Roll back one completed promotion only when its live baseline has not drifted:

```bash
daily-trade-radar calibration-rollback evaluation/backups/promotion-2026-07-31 \
  --baseline-dir evaluation \
  --pre-rollback-dir evaluation/backups/pre-rollback-2026-07-31 \
  --rolled-back-by "workspace owner" \
  --reason "Regression detected after promotion." \
  --rolled-back-at "2026-07-31T19:00:00+08:00"
```

Rollback verifies the promotion manifest, original backup hashes, and live post-promotion hashes before
making any change. It snapshots the live baseline and original promotion manifest first, then restores
the originals byte-for-byte under the same lock. A failed rollback restores the promoted state; a
successful rollback marks the promotion `rolled_back`, preventing replay. Drifted baselines, changed
backups, reused snapshot directories, and already-consumed promotions fail closed.

Evaluate a complete radar against an independently reviewed closed candidate set:

```bash
daily-trade-radar evaluation-scaffold current.json deduplicated.json --dataset-name radar-2026-07-30 --output labels.json
daily-trade-radar evaluate report.json labels.json --output evaluation.json
daily-trade-radar evaluate-history evaluation/drafts/manifest.json ../radar-runs --output evaluation/history-evaluation.json
```

The default release gate requires at least 20 positive events, independently reviewed labels, precision and recall of 0.90, primary-source rate of 0.95, date accuracy of 0.98, deduplication accuracy of 0.90, and zero unsupported sources. See [`references/evaluation.md`](skill/daily-trade-radar/references/evaluation.md) for the label schema and draft-fixture workflow.

Run the workflow:

```bash
python skill/daily-trade-radar/scripts/validate_events.py examples/current.json
python skill/daily-trade-radar/scripts/deduplicate.py examples/current.json --previous examples/previous.json --output deduplicated.json
python skill/daily-trade-radar/scripts/build_markdown.py deduplicated.json --output daily-trade-radar.md
python skill/daily-trade-radar/scripts/build_docx.py deduplicated.json --template skill/daily-trade-radar/assets/radar-template.docx --output daily-trade-radar.docx
python skill/daily-trade-radar/scripts/evaluate_report.py deduplicated.json evaluation-labels.json --output evaluation.json
python skill/daily-trade-radar/scripts/evaluate_history.py evaluation/drafts/manifest.json ../radar-runs --output evaluation/history-evaluation.json
python skill/daily-trade-radar/scripts/scaffold_calibration_reviews.py evaluation/drafts/manifest.json --output evaluation/calibration-review-scaffold.json
```

Deduplication defaults to an automatic-match threshold of `0.82` and a review threshold of `0.65`. Override them with `--threshold` and `--review-threshold` when calibrating against a labeled fixture set. Matches below the automatic threshold are retained with `review_required`; jurisdiction, platform, or seller-market conflicts are never matched.

Capture a public platform page after the browser has extracted its visible text:

```bash
python skill/daily-trade-radar/scripts/snapshot_platform_page.py --platform Amazon --url "https://sellercentral.amazon.com/seller-forums/discussions" --content-file amazon-visible.txt --store snapshots --backend filesystem --output amazon-snapshot.json
python skill/daily-trade-radar/scripts/snapshot_platform_page.py --platform Amazon --url "https://sellercentral.amazon.com/seller-forums/discussions" --content-file amazon-visible.txt --store radar-history.sqlite3 --backend sqlite --output amazon-snapshot.json
python skill/daily-trade-radar/scripts/snapshot_platform_page.py --platform Amazon --url "https://sellercentral.amazon.com/seller-forums/discussions" --content-file amazon-visible.txt --store radar-history.git --backend git --output amazon-snapshot.json
python skill/daily-trade-radar/scripts/snapshot_platform_page.py --platform Amazon --url "https://sellercentral.amazon.com/seller-forums/discussions" --content-file amazon-visible.txt --store "s3://private-radar/history" --backend s3 --s3-region ap-southeast-1 --output amazon-snapshot.json
daily-trade-radar snapshot-audit --store radar-history.git --output snapshot-audit.json
daily-trade-radar snapshot-audit --store "s3://private-radar/history" --backend s3 --s3-region ap-southeast-1 --output snapshot-audit.json
```

Snapshot persistence is exposed through a `SnapshotStore` protocol. The filesystem backend provides human-inspectable files, page locks, atomic replacement, and scan recovery. SQLite provides transactional WAL history for concurrent writers, compact backup, and querying. The Git backend initializes only a new empty, dedicated store; every capture is committed with hooks disabled and returns exact commit/tree provenance. The optional S3-compatible backend uses the standard SDK credential chain, encrypted create-only snapshot objects, and conditional ETag index updates; install it with `pip install -e ".[s3]"`. `snapshot-audit` verifies Git or S3 content hashes, predecessor chains, change semantics, indexes, diffs, and backend-specific integrity metadata. Git never configures or pushes a remote. Git and S3 stores are restricted to public page text.

Codex still performs the substantive research with available browsing tools, including the in-app browser for interactive or authenticated seller pages. The acquisition package adds bounded public HTTP retrieval, supplied RSS/Atom/sitemap parsing, stable task receipts, and draft coverage-ledger conversion; it is not a general crawler. Platform coverage cannot be marked as checked unless the report records the direct page URL and access result. Public pages that were substantively checked must also carry snapshot metadata, and authenticated browser content is never persisted by the acquisition cache.

## Quality and safety

- Main-table events require a direct primary source.
- Search-result snippets are not accepted as evidence.
- Unconfirmed items stay out of the main action table.
- Applicability must not be assumed when product, HS code, market, or channel data is missing.
- Reports must disclose the search cutoff, timezone, scope, and coverage gaps.
- Always verify consequential decisions with qualified legal, customs, tax, or sanctions professionals.

## Development

CI installs the package and runs the complete offline suite on Python 3.10, 3.11, and 3.12, matching the package's declared support range.

Run the offline test suite:

```bash
python -m unittest discover -s tests -v
```

## Follow / 关注

外贸与跨境电商动态、实操笔记及项目更新：

[老Hai外贸跨境笔记（@HaiNengGao）](https://x.com/HaiNengGao)

## License

[MIT](LICENSE)
