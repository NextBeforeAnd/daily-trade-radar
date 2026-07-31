---
name: daily-trade-radar
description: Research, verify, deduplicate, prioritize, and write a daily foreign-trade radar covering official trade policy, customs, sanctions and export controls, tariffs and tax, product compliance, logistics, and marketplace rule changes. Use for requests such as “今天的外贸行情”, “看看今天外贸”, “今日外贸雷达”, “跨境政策更新”, a daily trade briefing, current cross-border regulatory developments, comparison with a previous radar, impact assessment by market/product/HS code/platform, or an actionable Chinese or English Markdown/DOCX report.
---

# Daily Trade Radar

Produce an evidence-led daily radar that distinguishes new developments from ongoing items and turns them into specific actions. Treat policy dates, scope, rates, product codes, and deadlines as high-risk facts.

## Collect the brief

Infer missing preferences when safe. Record:

- report date and timezone;
- target countries or regions;
- products, keywords, and HS codes;
- marketplaces and sales channels;
- priority themes;
- output language;
- previous radar or event JSON used for deduplication.

If no scope is supplied, cover China export controls and customs, the United States, the European Union, major cross-border marketplaces, and material logistics changes. State this default scope in the report.

Treat an unqualified request for “外贸行情” as a request for this regulatory and operational radar. Include exchange rates, demand indicators, freight prices, or macro commentary only when the user asks for them or when they materially change a listed action.

Set the reporting window before research:

- when a previous radar JSON exists, use its `cutoff` as the new `window_start`;
- otherwise use the trailing 24 hours;
- independently scan rules taking effect, expiring, or reaching a consultation deadline in the next 30 days;
- normalize the cutoff and exact event timestamps to ISO 8601 with UTC offsets.

Before browsing a multi-jurisdiction, product, HS-code, or marketplace scope, build and validate the structured research plan described in [references/research-planning.md](references/research-planning.md). Use its official, effective/deadline, product, marketplace, and lead tracks as the research contract. When marketplaces are in scope, materialize the plan's registry-driven acquisition manifests:

```text
daily-trade-radar plan --scope scope.json --output research-plan.json --manifest-dir manifests
daily-trade-radar plan --validate research-plan.json
```

A plan is not evidence. Do not mark a track complete until its direct sources have been opened and its acquisition receipts or explicit gaps exist.

## Research current developments

Browse because the task is time-sensitive. Search the source categories and query patterns in [references/source-map.md](references/source-map.md). Prefer primary official publications; use a platform's own announcement for marketplace rules. Use secondary reporting only to discover a primary source or to add clearly attributed context.

For every registered platform named in scope, load its bundled configuration from `src/daily_trade_radar/platforms/data/` and run the mandatory discovery pass in [references/platform-policy-monitoring.md](references/platform-policy-monitoring.md). The registry currently includes TikTok Shop, Temu, Shopify, Jumia, Amazon, AliExpress, Shopee, Lazada, eBay, and Walmart Marketplace. Use a seven-day platform lookback in addition to the main reporting window because seller pages are often indexed late or omit publication timestamps. Open and record every page actually checked. A coverage checkbox without a supporting URL is not evidence.

Use the auditable acquisition workflow in [references/acquisition.md](references/acquisition.md): create a registry-driven manifest before checking platform routes, produce one receipt for every successful or failed access attempt, and derive the draft coverage ledger from those receipts. A receipt proves an access attempt, not a policy claim; primary-source reading, snapshot comparison, and event verification are still required.

Use the source-health workflow in [references/source-health.md](references/source-health.md) to distinguish successful coverage from missing, partial, blocked, authenticated, timed-out, rate-limited, or structurally changed sources:

```text
daily-trade-radar doctor
daily-trade-radar doctor --probe --platform Shopify
daily-trade-radar doctor --postmortem RUN_DIRECTORY --json --output source-health.json
```

Public probes are bounded access checks only. They do not probe authenticated dashboards and do not prove that a policy page was substantively reviewed.

Treat cached public receipts as bounded research acceleration only. Reuse only successful receipts within their configured TTL; retry login gates, blocked requests, missing routes, and connection failures on the next run. Use an explicit refresh when current access state matters or the source may have changed inside the TTL.

Capture the normalized visible text of every opened public update or current-policy page and run `scripts/snapshot_platform_page.py` against the persistent snapshot store for that radar series. Put the returned `snapshot` object into the matching `sources_checked` entry. Use the historical diff to distinguish a real page change from a refreshed timestamp or a first-seen page. A first snapshot establishes a baseline; it does not prove what changed.

Choose and operate the persistent backend according to [references/snapshot-storage.md](references/snapshot-storage.md). The default filesystem backend is human-inspectable, SQLite provides transactional concurrent history, Git provides commit-addressed audit history, and S3 provides conditional shared private object storage for public page text. Preserve `storage_backend`, `snapshot_ref`, `diff_ref`, and `index_recovered`; also preserve `git_commit` and `git_tree` for Git captures. Use portable refs instead of absolute compatibility paths when moving history.

```text
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store radar-snapshots --backend filesystem --captured-at "2026-07-27T17:00:00+08:00" --output snapshot.json
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store radar-history.sqlite3 --backend sqlite --captured-at "2026-07-27T17:00:00+08:00" --output snapshot.json
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store radar-history.git --backend git --captured-at "2026-07-27T17:00:00+08:00" --output snapshot.json
python scripts/snapshot_platform_page.py --platform "Amazon" --url "https://..." --content-file page.txt --store s3://private-radar/history --backend s3 --captured-at "2026-07-27T17:00:00+08:00" --output snapshot.json
daily-trade-radar snapshot-audit --store radar-history.git --output snapshot-audit.json
daily-trade-radar snapshot-audit --store s3://private-radar/history --backend s3 --output snapshot-audit.json
```

When the in-app browser is available, use it for platform pages that require interactive navigation or may already have a signed-in seller session. Check the authenticated inbox, policy center, account health, logistics, settlement, and category notices when accessible. Never submit, acknowledge, appeal, change settings, or otherwise mutate a seller account unless the user requests that action.

Preserve credible platform leads that cannot yet be confirmed as `unconfirmed` watchlist events instead of silently dropping them. Label the source type and the missing confirmation. Do not promote a lead to the main action table until the underlying platform-owned page or authenticated notice has been opened.

When secondary leads are numerous or conflicting, normalize them and run the early-signal workflow in [references/discovery-signals.md](references/discovery-signals.md):

```text
daily-trade-radar discover leads.json --output discovery.json
```

Use its priority score only to order verification work. It is not the event risk score. Cross-source clustering must respect jurisdiction and platform conflicts, and every output remains `unconfirmed`, `watch`, and ineligible for promotion until primary confirmation.

For every candidate event, capture the publication date, effective date, jurisdiction, affected products or sellers, concrete requirement, source title, direct URL, and retrieval date. Capture `published_at`, `effective_at`, `deadline_at`, and `source_timezone` when an official source supplies exact timing. Never treat a search-result snippet as evidence. Open and read the supporting page.

Separate:

- `new`: first published inside the reporting window;
- `effective`: previously announced but taking effect now;
- `deadline`: an approaching compliance or consultation deadline;
- `ongoing`: still material but neither new nor newly effective;
- `unconfirmed`: relevant claim lacking adequate primary confirmation.

Do not place `unconfirmed` items in the main action table. Put them in a short watchlist with an explicit caveat, or omit them.

## Normalize and assess

Represent reviewed events in the JSON format defined in [references/output-schema.md](references/output-schema.md). Apply [references/scoring-rules.md](references/scoring-rules.md) consistently.

Populate all five `score_breakdown` dimensions before setting the total `score` and `level`. Let the validator enforce their sum and the normal level mapping. Use `level_override` only for a documented exception, with a specific reason; evidence 0 can never be raised above `watch`.

When independently reviewed historical labels exist, run the deterministic calibration workflow in [references/scoring-calibration.md](references/scoring-calibration.md). Review every semantic-duplicate queue item and keep unresolved pairs out of threshold fitting. For routine later runs, prefer `calibration-update` with a new output directory; it performs the incremental merge, difference gate, calibration, comparison, and threshold-control checks together. Use the lower-level `calibration-scaffold --existing`, `--diff-output`, and `--require-calibration-ready` commands when manual control is needed. Promote a completed bundle only through `calibration-promote`, with an explicit human decision, reviewer, reason, timestamp, and new backup directory. Roll back a promotion only through `calibration-rollback`, using a new pre-rollback snapshot directory; never bypass its live-baseline and backup hash checks. Do not calibrate until `incremental_diff.calibration_gate.ready` is true. Require the sample gate before considering candidate thresholds. Never calibrate on levels originally generated by the same rules, and never change thresholds automatically from the calibration output.

When historical candidate and final reports exist, scaffold a review queue and evaluate the completed radar with the deterministic workflow in [references/evaluation.md](references/evaluation.md). Keep generation and labeling independent, preserve rejected candidates, and do not claim benchmark quality from draft or self-generated labels.

Write impact and action fields for the user's actual market, product, HS code, or platform. If applicability is unknown, say what must be checked instead of assuming applicability.

For a verified marketplace-policy event, populate the structured `platform_policy` object and `action_items` array. Preserve the top-level `action` as the short executive instruction. Separate platform, seller market, program/model, policy area, change type, seller scope, before/after state, enforcement consequence, and backend-verification need. Never infer market-wide applicability from a single account notice.

Use the registered display name or alias when available. For an unregistered channel, set `registry_status` to `custom` and `official_entry_verification_required` to `true`; do not treat its entry route as verified until a platform-owned page has been opened.

Populate the root `coverage_ledger` for every platform and seller market checked. Record the program, lookback start, every source URL opened, its source type and result, public/current-policy/dashboard access, checked time, resulting event IDs, and gaps. Keep `coverage_gaps` as the concise executive disclosure. If a named platform appears in `scope`, the report must contain a matching ledger entry. Do not claim a platform was checked when only a generic web search was run.

Keep access outcomes semantically distinct. Use `login_required` only when an actual login or authentication gate was reached. Use `blocked` for connection closure, robots/security denial, regional blocking, or browser-policy rejection. Do not convert a blocked request into a login result.

## Deduplicate

Compare candidates with the previous event JSON when available:

```text
python scripts/deduplicate.py current.json --previous previous.json --output deduplicated.json
```

Review deduplication dispositions before delivery. `material_update` means a factual date, scope, obligation, rate, source, or verified platform-policy state changed. `operational_refresh` means an unchanged rule reached its effective date or deadline today. `duplicate_removed` covers editorial rewrites, action wording, impact phrasing, and score-only changes. Label retained repeats as `effective`, `deadline`, or `ongoing`; do not call them new.

The deduplicator matches stable IDs first, rejects jurisdiction/platform/seller-market conflicts, then uses one-to-one weighted matching across titles, authorities, product/channel scope, canonical URLs, regulatory identifiers, and platform scope. The default automatic threshold is `0.82`; similarities from the `0.65` review threshold up to the automatic threshold are retained as `review_required`. Review every such item manually and never delete it merely because it resembles an earlier event.

If the previous radar exists only as prose, compare by jurisdiction, authority, regulation or program name, product/HS code, platform, and effective date. Explain the deduplication basis briefly.

For persistent continuity across validated runs, use the local history and drill workflow in [references/history-and-drill.md](references/history-and-drill.md):

```text
daily-trade-radar library ingest REPORT_OR_RUN_DIRECTORY --db radar-library.sqlite3
daily-trade-radar library search "QUERY" --db radar-library.sqlite3
daily-trade-radar drill EVENT_ID --library radar-library.sqlite3 --output drill-plan.json
```

The library joins only stable event IDs and never silently performs semantic aliasing. A drill plan schedules focused source revalidation; it does not itself confirm, promote, or modify an event. Run its queries and primary targets through the normal receipt, snapshot, scoring, validation, and deduplication gates.

## Validate and render

Validate the final event file before writing:

```text
python scripts/validate_events.py deduplicated.json
python scripts/build_markdown.py deduplicated.json --output daily-trade-radar.md
```

For release evaluation against independently reviewed labels, run:

```text
python scripts/evaluate_report.py deduplicated.json evaluation-labels.json --output evaluation.json
```

The `scripts/*.py` files are stable compatibility entry points backed by the shared `src/daily_trade_radar` package. Keep automation on the documented script commands unless the package has been installed; package developers may use the equivalent unified `daily-trade-radar` CLI.

Use the Markdown structure produced by the script. Edit for clarity only after validation. Preserve direct source links and factual qualifiers.

When the user requests DOCX, use `assets/radar-template.docx` as the actual build template and follow the available document-generation skill's render-and-inspect workflow. Do not assume the template has passed visual QA in the current environment.

Generate Word output from the validated JSON source:

```text
python scripts/build_docx.py deduplicated.json --template assets/radar-template.docx --output daily-trade-radar.docx
```

The DOCX renderer follows the JSON `language` field in the same way as the Markdown renderer. Event text must already be written in the requested language. Render and visually inspect the generated DOCX before delivery. If the document skill's renderer cannot run because LibreOffice/`soffice` is unavailable, run its structural audits, verify table geometry and fields, and disclose that visual QA was unavailable; do not claim a render pass.

When the user asks to repurpose a validated radar for X, LinkedIn, email, or another channel, derive the copy from the validated JSON rather than researching again. Preserve factual qualifiers and use a hook, the most material changes, one concrete action, and a concise close.

## Quality gate

Before delivery, confirm:

- every main-table event has a direct primary source;
- publication and effective dates are not conflated;
- every deadline includes year and timezone when relevant;
- new items are genuinely new relative to the supplied previous radar;
- every event has a complete score breakdown whose total and risk level follow the scoring rules, and every exception has a structured override reason;
- actions name an owner or business function and a time horizon where possible;
- every marketplace-policy event identifies its platform and seller market, or explicitly states what remains unknown;
- every platform registry entry exposes source depth, and every missing update/current-policy/dashboard route has a declared gap;
- every platform named in scope has a coverage-ledger entry and every positive check is backed by an opened URL;
- every planned platform route has an acquisition receipt or an explicit coverage gap, and authenticated browser text was not persisted;
- the research plan passes identity validation, covers every scoped platform exactly once, and keeps discovery leads at `lead_only` evidence status;
- the source-health postmortem contains no unexplained `not_checked`, `partial`, `blocked`, `timeout`, `rate_limited`, or `schema_drift` state hidden behind a “no update” conclusion;
- discovery priority is kept separate from event risk, cross-source corroboration counts distinct domains, and no discovery cluster is marked promotion-eligible;
- every drill conclusion is backed by newly opened primary or platform-owned evidence, not merely by the generated drill plan or historical library;
- every reused acquisition receipt is successful, unexpired, and identity-bound to the exact manifest task;
- every opened public update/current-policy page has snapshot metadata, and every claimed page change cites either a historical diff or an explicit platform changelog;
- the selected snapshot backend remains consistent within a radar series and its persistent store is retained outside the Skill package;
- every Git or S3 snapshot store passes `snapshot-audit` and contains public page text only; Git is pushed only through an explicit operator-controlled workflow;
- the platform discovery pass uses at least a seven-day lookback and retains credible unresolved leads as `unconfirmed` watchlist events;
- laws or customs measures that merely affect platform sellers are not mislabeled as platform-owned policy changes;
- platform actions include a completion artifact such as an exported SKU/order list, settings screenshot, submitted document, ticket, or approved decision record;
- no unsupported inference is written as fact;
- the report states the search cutoff, timezone, scope, and known coverage gaps;
- the report states the reporting-window start and exact event times when available;
- the platform coverage ledger matches the narrative coverage gaps;
- `blocked` and `login_required` reflect different observed access outcomes;
- “no material new item found” is used when the research supports that conclusion.
