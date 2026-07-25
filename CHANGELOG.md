# Changelog

All notable changes to Daily Trade Radar are documented in this file.

## Unreleased

### 2026-07-25

#### Added

- Added natural-language triggers such as “今天的外贸行情” and enabled implicit invocation metadata.
- Added reporting-window start, exact event timestamps with UTC offsets, source timezone, and a machine-readable platform coverage ledger.
- Added Markdown and Word rendering for coverage-ledger checks and exact event timing.

#### Changed

- Word reports now use the bundled DOCX file as the actual build template through the `--template` option.
- Deduplication treats changes to exact publication, effective, or deadline timestamps as material updates.
- Daily research defaults to the previous report cutoff or a trailing 24-hour window, plus a 30-day effective-date and deadline scan.

### 2026-07-24

#### Changed

- Replaced binary duplicate/update detection with `material_update`, `operational_refresh`, and `duplicate_removed` classifications.
- Editorial changes to summaries, impacts, actions, and scores no longer keep an otherwise unchanged event.
- Material-change detection now focuses on dates, scope, official sources, rates and other factual signals, obligations, and verified marketplace-policy state.
- Deduplication output now records machine-readable `change_reasons`, and Markdown/Word reports distinguish material updates from effective-date or deadline refreshes.

#### Added

- Added regression tests for editorial rewrites, rate changes, effective-date transitions, and Chinese substring false positives.

### 2026-07-23

#### Added

- Added a dedicated monitoring playbook for TikTok Shop, Temu, Shopify, and Jumia, including official-source routes, a policy taxonomy, an applicability gate, and login-only coverage handling.
- Added optional, backward-compatible `platform_policy` analysis and structured `action_items` with owner, deadline/horizon, and completion evidence.
- Added platform-policy analysis to Markdown and Word event details and owner-level actions to both renderers.
- Added validation and regression tests for complete and incomplete structured marketplace events.

#### Changed

- Marketplace exposure now requires an established seller market plus a relevant account, program, product, fulfillment, payment, or feature dimension before receiving the highest exposure score.
- Deduplication now treats changes to structured platform analysis and action items as material updates.

### 2026-07-22

#### Added

- Added English Markdown output when the root JSON `language` field is `en` or starts with `en-`.
- Added Chinese and English Word (`.docx`) report generation from validated event JSON.
- Added Word sections for the daily assessment, radar table, priority actions, deduplication, event details, official sources, watchlist, and coverage gaps.
- Added clickable official-source links, repeating table headers, page numbers, fixed table geometry, and risk-level highlighting to Word reports.
- Added automatic removal of document author metadata, custom properties, and Word revision-session identifiers.
- Added `python-docx` as the Word-generation dependency and installed it in GitHub Actions.
- Added automated tests for English Markdown and bilingual Word output.

#### Changed

- Rebuilt the bundled Word template to remove corrupted Chinese text and metadata.
- Updated the README, Skill instructions, and output-schema reference with bilingual and Word-output usage.
- Expanded the automated test suite from two tests to four.

## 0.1.0-alpha - 2026-07-21

### Added

- Published the initial Daily Trade Radar Codex Skill.
- Added official-source research guidance, event scoring, JSON validation, deduplication, and Chinese Markdown generation.
- Added offline examples, workflow tests, GitHub Actions validation, an MIT license, and installation instructions.
