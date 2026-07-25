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

## Research current developments

Browse because the task is time-sensitive. Search the source categories and query patterns in [references/source-map.md](references/source-map.md). Prefer primary official publications; use a platform's own announcement for marketplace rules. Use secondary reporting only to discover a primary source or to add clearly attributed context.

For TikTok Shop, Temu, Shopify, and Jumia, also follow [references/platform-policy-monitoring.md](references/platform-policy-monitoring.md). Complete a platform-and-market coverage ledger, distinguish public sources from login-only seller notices, and disclose inaccessible dashboards as coverage gaps.

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

Write impact and action fields for the user's actual market, product, HS code, or platform. If applicability is unknown, say what must be checked instead of assuming applicability.

For a verified marketplace-policy event, populate the structured `platform_policy` object and `action_items` array. Preserve the top-level `action` as the short executive instruction. Separate platform, seller market, program/model, policy area, change type, seller scope, before/after state, enforcement consequence, and backend-verification need. Never infer market-wide applicability from a single account notice.

Populate the root `coverage_ledger` for every platform and seller market checked. Record the program, public update check, current-policy check, dashboard access, access result, checked time, and gaps. Keep `coverage_gaps` as the concise executive disclosure.

## Deduplicate

Compare candidates with the previous event JSON when available:

```text
python scripts/deduplicate.py current.json --previous previous.json --output deduplicated.json
```

Review deduplication dispositions before delivery. `material_update` means a factual date, scope, obligation, rate, source, or verified platform-policy state changed. `operational_refresh` means an unchanged rule reached its effective date or deadline today. `duplicate_removed` covers editorial rewrites, action wording, impact phrasing, and score-only changes. Label retained repeats as `effective`, `deadline`, or `ongoing`; do not call them new.

If the previous radar exists only as prose, compare by jurisdiction, authority, regulation or program name, product/HS code, platform, and effective date. Explain the deduplication basis briefly.

## Validate and render

Validate the final event file before writing:

```text
python scripts/validate_events.py deduplicated.json
python scripts/build_markdown.py deduplicated.json --output daily-trade-radar.md
```

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
- risk levels follow the scoring rules;
- actions name an owner or business function and a time horizon where possible;
- every marketplace-policy event identifies its platform and seller market, or explicitly states what remains unknown;
- platform actions include a completion artifact such as an exported SKU/order list, settings screenshot, submitted document, ticket, or approved decision record;
- no unsupported inference is written as fact;
- the report states the search cutoff, timezone, scope, and known coverage gaps;
- the report states the reporting-window start and exact event times when available;
- the platform coverage ledger matches the narrative coverage gaps;
- “no material new item found” is used when the research supports that conclusion.
