# Changelog

All notable changes to Daily Trade Radar are documented in this file.

## Unreleased (target: 0.5.0)

### 2026-08-08 (operator experience)

#### Added

- Added `daily-trade-radar init` for safe starter profiles that default to a narrow China-only, no-marketplace pilot and optionally generate a one-SKU catalog.
- Added `daily-trade-radar platforms scaffold` for validation-ready platform templates whose starter routes remain conditional and whose unconfigured source types are explicit gaps.
- Added deterministic Chinese/English content-consistency checks through `language-check`, `validate --require-language`, and profile-driven strict run gates without automatic factual translation.
- Added static HTML, Markdown, and JSON source-coverage dashboards with route depth, conditional and missing sources, optional source-health results, priority ordering, and next actions.
- Added operator-experience regression coverage for initialization, scaffolding, language gates, and dashboards.

#### Changed

- Bumped the package and development version to `0.5.0`.

### 2026-08-08

#### Added

- Added a validated JSON profile and `daily-trade-radar run` orchestration command that prepares the evidence contract, stops explicitly for research, and completes applicability matching, validation, deduplication, rendering, and alert generation when reviewed events are supplied.
- Added a machine-readable China official-source registry covering verified entry routes for MOFCOM, GACC, the State Taxation Administration, and SAMR; scoped research plans now include those direct routes.
- Added auditable organization-catalog matching by HS-code prefix, product term, market, and platform, exposed through `daily-trade-radar match`.
- Added verified-event alert selection, applicability gating, signature-based duplicate suppression, preview JSON, and explicit HTTPS webhook delivery through `daily-trade-radar alert` and `run --send-alerts`.
- Added example profile/catalog files and end-to-end regression tests for the new operational path.

#### Changed

- Bumped the package and development version to `0.4.0`.

### 2026-07-30

#### Added

- Added identity-bound research plans with validated official-update, upcoming-deadline, product/HS-code, marketplace-policy, and lead-only discovery tracks.
- Added `daily-trade-radar plan` plus a compatibility script, deterministic default windows, strict platform scope resolution, plan-tamper detection, and optional materialization of registry-driven marketplace manifests.
- Added `daily-trade-radar doctor` plus a compatibility script for registry inventory, bounded public probes, explicit fix guidance, and receipt-backed postmortems over completed run directories.
- Added typed source-health states for successful checks, no relevant updates, partial work, blocking, authentication gates, timeouts, rate limits, schema drift, declared configuration gaps, and unchecked routes.
- Added research-planning and source-health operator documentation and offline regression coverage for both phases.
- Added `discover` early-signal prioritization with typed lead inputs, deterministic 0-100 verification priority, distinct-domain corroboration, scope-conflict-safe clustering, a noise floor, and a hard unconfirmed/watch/no-promotion boundary.
- Added a local SQLite radar library that ingests validated reports, replaces repeated runs idempotently, preserves stable-ID sightings, uses FTS5 when available, and falls back to portable field search.
- Added `drill` plans for exact event IDs with report or library baselines, historical sightings, primary and registered platform targets, focused revalidation queries, refresh policy, and fail-closed promotion requirements.
- Added compatibility scripts, operator references, unified CLI routes, and offline regression tests for discovery, history search, and focused drills.

- Added an optional S3-compatible snapshot backend with SDK-chain credentials, AES-256 server-side encryption requests, immutable create-only snapshot objects, optimistic ETag page-index protection, portable references, and offline fake-client regression tests.
- Extended `snapshot-audit` to S3 stores with chain, hash, chronology, diff, reference, encryption-metadata, and orphan-object verification.
- Added deterministic report evaluation against independently reviewed closed candidate sets.
- Added precision, recall, F1, primary-source, date, status, risk-level, unsupported-source, and deduplication metrics.
- Added configurable release gates with distinct invalid-input and quality-failure exit codes.
- Added a draft offline label fixture, evaluation documentation, regression tests, and a CI evaluator smoke test.
- Added a deterministic draft-label scaffolder that preserves rejected candidates and deduplication review context without claiming independent ground truth.
- Added a 12-run review queue containing 56 candidates and 27 deduplication cases from July 21–30 historical radar outputs.

- Added micro-aggregated historical evaluation with run-namespaced error identifiers and release-gate reporting.
- Added a leakage-resistant calibration worksheet generator that deduplicates stable event IDs, excludes cross-run level conflicts, and blanks generated score dimensions.
- Added conservative cross-ID semantic clustering to calibration scaffolds, with auditable automatic aliases, cross-alias level-conflict exclusion, and a fail-closed human review queue for ambiguous matches.
- Added fail-closed incremental calibration updates with evidence fingerprints, score preservation via `--existing`, changed-record review queues, existing-only observation retention, machine-readable difference reports, and a calibration-readiness gate enforced by both scaffold automation and calibration.
- Added the atomic `calibration-update` pipeline, which publishes a non-overwriting artifact bundle, stops before calibration when review is pending, compares decision-relevant metrics with the prior report, and preserves human threshold decisions only when those metrics are unchanged.
- Added guarded `calibration-promote` baseline promotion with independent bundle recomputation, explicit human decisions, runtime threshold-adoption checks, locking, verified backups, before/after hashes, and automatic restoration on write failure.
- Added replay-safe `calibration-rollback` with live-baseline and backup hash validation, byte-exact cross-platform restoration, pre-rollback snapshots, lock reuse, rollback manifests, and automatic recovery to the promoted state on failure.

#### Changed

- Bumped the package and development version to `0.3.0`.
- Upgraded AliExpress, Lazada, Temu, and Jumia from constrained to hybrid source depth by adding verified public current-policy entry routes while retaining conditional or explicit gaps for missing stable official-update feeds.
- Tightened `full` platform source depth so every required source type must have a verified route; merely configuring conditional routes no longer qualifies a platform as fully covered.

## 0.2.0

### 2026-07-28

#### Added

- Added a required five-dimension `score_breakdown` for every event and deterministic validation of the total score and normal risk-level mapping.
- Added structured `level_override` records for documented risk-band exceptions while preventing evidence-zero events from being raised above `watch`.
- Added marketplace applicability validation before assigning the highest business-exposure score.
- Added regression tests for missing or inconsistent score breakdowns, level overrides, evidence-zero handling, and marketplace applicability.
- Replaced best-single-string deduplication with stable-ID-first, scope-aware, one-to-one weighted matching.
- Added canonical URL comparison, regulatory-identifier signals, field-level match components, confidence labels, and retained `review_required` matches.
- Added regression tests for cross-market ID collisions, reused announcement URLs, tracking parameters, low-confidence review, and one-to-one assignment.
- Moved validation, deduplication, snapshots, and renderers into an installable `src/daily_trade_radar` package while preserving every existing `scripts/*.py` command as a thin compatibility wrapper.
- Added shared scoring, model, and bundled-path modules plus a lazy unified CLI for `validate`, `deduplicate`, `snapshot`, `markdown`, and `docx`.
- Added direct unit tests for package APIs, score boundaries, URL and scope normalization, regulatory-identifier conflicts, snapshot normalization, template resolution, and CLI dispatch.
- Added a data-driven marketplace registry with one bundled JSON playbook per platform and automatic alias/scope resolution in coverage validation.
- Added Shopee, Lazada, eBay, and Walmart Marketplace alongside the original six registered platforms.
- Added explicit safety metadata for unregistered custom platforms and a `platforms` CLI command for inspecting installed routes and scope dimensions.
- Added registry, Chinese/English alias, new-platform coverage, ledger-alias, and custom-platform validation tests.
- Added a `SnapshotStore` protocol and backend factory while preserving the original functional snapshot API and CLI.
- Added filesystem page locks, atomic writes, corrupt-index scan recovery, and idempotent concurrent capture handling.
- Added portable `snapshot_ref`/`diff_ref`, backend metadata, recovery disclosure, validation rules, and deep storage tests.
- Added registry-driven acquisition manifests, stable evidence receipts, a content-addressed public cache, and coverage-ledger conversion with explicit missing-receipt and missing-snapshot gaps.
- Added bounded, rate-limited HTTP acquisition with retries and cached receipts, plus offline RSS, Atom, and sitemap parsing.
- Added manual and browser adapters that hash but never persist authenticated visible text, acquisition-receipt validation, a unified `acquisition` CLI, and focused acquisition tests.
- Hardened acquisition task IDs, manifest digests, receipt-to-task binding, portable cache paths, and untrusted JSON field validation.
- Added immutable receipt history, successful-result TTLs, failure-safe cache reuse, forced refresh, and a bounded public `acquisition fetch` command.
- Added a transactional SQLite snapshot backend with WAL, normalized-content history, stored diffs, chronological chain protection, logical portable refs, and idempotent concurrent capture.
- Expanded CI to install the package and run the full suite on Python 3.10, 3.11, and 3.12; aligned the README development version with package version `0.2.0`.
- Added historical scoring calibration with independent-review labels, sample sufficiency gates, reviewer agreement, conflict exclusion, confusion matrices, macro-F1, dimension summaries, and non-binding monotonic threshold candidates.
- Added route-level platform source metadata, strict registry depth validation, explicit missing-source declarations, market-mismatch reverification, and source-depth reporting in the platform CLI.
- Expanded verified public routes for Shopee SG, Shopify admin alerts, and TikTok Shop US current policy while preserving conditional status for unverified country-specific entry points.
- Added a dedicated Git snapshot backend with one commit per capture, exact commit/tree provenance, dirty-tree and unmarked-repository guards, disabled hooks, chronological protection, and no automatic remote operations.
- Added `snapshot-audit` to verify Git objects, clean state, tracked snapshots, normalized-content hashes, predecessor chains, change-status semantics, and page indexes.

### 2026-07-27

#### Added

- Added persistent platform-page snapshots with normalized SHA-256 hashes, prior-snapshot links, and saved unified diffs.
- Added dedicated Amazon and AliExpress monitoring routes and mandatory scope-ledger validation.
- Added regression tests for first-seen, unchanged, and changed pages, plus Amazon/AliExpress coverage.

#### Fixed

- Replaced checklist-only marketplace monitoring with a mandatory seven-day discovery pass and read-only authenticated-browser fallback.
- Prevented reports from claiming that a platform was checked without recording opened source URLs and access results.
- Preserved credible but unverified marketplace leads in the watchlist instead of silently discarding them.
- Prevented government tax, customs, sanctions, or product rules from being mislabeled as platform-owned policy changes.
- Split access-blocked pages from pages that specifically require authentication; one can no longer satisfy the other's evidence rule.

#### Added (earlier changes)

- Added `lookback_start`, `sources_checked`, and `verified_event_ids` to platform coverage records.
- Added validation for platform scope coverage, source evidence, dashboard login attempts, seven-day lookback, and event-ID linkage.
- Added Markdown and Word rendering of the exact platform sources opened during research.
- Added regression tests for missing evidence, missing platform ledgers, and short platform lookback windows.

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
