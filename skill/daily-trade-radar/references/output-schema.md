# Event data and report schema

Use UTF-8 JSON. The root object contains report metadata and an `events` array.

Set `language` to `zh-CN` for a Chinese Markdown report or to `en`/`en-US` for an English report. Write event text fields in the same language; the renderer translates report headings and fixed labels, not event content.

```json
{
  "report_date": "2026-07-21",
  "timezone": "Asia/Singapore",
  "window_start": "2026-07-20T17:00:00+08:00",
  "cutoff": "2026-07-21T17:00:00+08:00",
  "language": "zh-CN",
  "scope": ["China", "EU", "US", "Amazon"],
  "coverage_gaps": [],
  "coverage_ledger": [
    {
      "platform": "TikTok Shop",
      "seller_market": "US",
      "program": "US local seller",
      "lookback_start": "2026-07-14T17:00:00+08:00",
      "public_update_checked": true,
      "current_policy_checked": true,
      "dashboard_checked": false,
      "access_result": "login_required",
      "checked_at": "2026-07-21T16:30:00+08:00",
      "sources_checked": [
        {
          "source_type": "official_updates",
          "url": "https://seller-us.tiktok.com/university/",
          "result": "no_relevant_update",
          "checked_at": "2026-07-21T16:20:00+08:00",
          "notes": "Opened the US Academy update route; no material item in the platform lookback.",
          "snapshot": {
            "snapshot_id": "20260721162000-acde1234abcd",
            "captured_at": "2026-07-21T16:20:00+08:00",
            "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "previous_snapshot_id": "20260720162000-acde1234abcd",
            "change_status": "unchanged",
            "diff_summary": "No normalized page-text change from the previous snapshot.",
            "snapshot_path": "C:/radar-snapshots/tiktok-shop/page/snapshot.json",
            "diff_path": null,
            "storage_backend": "filesystem",
            "snapshot_ref": "tiktok-shop/page/snapshot.json",
            "diff_ref": null,
            "index_recovered": false
          }
        }
      ],
      "verified_event_ids": [],
      "gaps": ["Seller Center account notices were not accessible"]
    }
  ],
  "events": [
    {
      "id": "eu-low-value-parcel-fee-2026",
      "title": "Concise event title",
      "status": "new",
      "level": "high",
      "score": 9,
      "score_breakdown": {
        "regulatory_force": 2,
        "business_exposure": 2,
        "urgency": 2,
        "consequence": 1,
        "evidence": 2
      },
      "jurisdiction": "EU",
      "authority": "European Commission",
      "published_date": "2026-06-08",
      "effective_date": "2026-07-01",
      "deadline": null,
      "published_at": null,
      "effective_at": "2026-07-01T00:00:00+02:00",
      "deadline_at": null,
      "source_timezone": "Europe/Brussels",
      "products_or_channels": ["low-value e-commerce parcels"],
      "summary": "Verified requirement and scope.",
      "impact": "Specific operational or commercial effect.",
      "action": "Owner + verb + object + timing + completion evidence.",
      "rationale": "Why the score and level apply.",
      "source_title": "Official page title",
      "source_url": "https://example.invalid/official-page",
      "retrieved_date": "2026-07-21",
      "platform_policy": {
        "platform": "TikTok Shop",
        "seller_market": "US",
        "program": "US local seller",
        "policy_area": "listing_product_compliance",
        "change_type": "rule_change",
        "seller_scope": "US sellers listing the named product categories",
        "previous_state": null,
        "new_state": "Listing-level documents are required after the stated preparation period.",
        "enforcement_consequence": "Affected listings cannot go live without the documents.",
        "backend_verification_required": true
      },
      "action_items": [
        {
          "owner": "marketplace operations",
          "action": "Export affected listings and map each SKU to the required document.",
          "deadline": "within 2 business days",
          "completion_evidence": "Reviewed SKU-document matrix and Seller Center submission record"
        }
      ]
    }
  ]
}
```

## Required event fields

Require the original root and event fields shown above, including `score_breakdown`. `window_start`, `coverage_ledger`, `published_at`, `effective_at`, `deadline_at`, and `source_timezone` are backward-compatible optional fields, but new reports must populate them when the information exists. Use ISO `YYYY-MM-DD` dates and ISO 8601 date-times with UTC offsets. Permit `null` only when an exact date or time genuinely does not exist. Use one of `new`, `effective`, `deadline`, `ongoing`, or `unconfirmed` for status and one of `high`, `medium`, `low`, or `watch` for level.

## Score fields

`score_breakdown` requires exactly these five integer fields, each from 0 to 2: `regulatory_force`, `business_exposure`, `urgency`, `consequence`, and `evidence`. Their sum must equal `score`. The normal level mapping is 8-10 `high`, 5-7 `medium`, 2-4 `low`, and 0-1 `watch`.

When a verified stoppage or another documented exception requires a level different from the numeric mapping, add:

```json
"level_override": {
  "level": "high",
  "reason": "Verified account enforcement will block the affected listings before the next operating cycle."
}
```

The override level must match the event `level`, the reason must be nonblank, and the override must be omitted when the ordinary mapping already produces that level. Evidence 0 always requires `watch` and cannot be overridden.

## Deduplication metadata

After `deduplicate.py` runs, the root `deduplication` object records `previous_report`, `threshold`, `review_threshold`, `matching_strategy`, and `matches`. Each match records:

- `current_id` and `previous_id`;
- numeric `similarity`;
- `match_method`: `exact_id` or `weighted_fields`;
- `match_confidence`: `high`, `medium`, or `low`;
- `match_components`: the auditable field-level similarities used by weighted matching;
- `review_required`: boolean;
- `disposition`: `duplicate_removed`, `material_update`, `operational_refresh`, or `review_required`;
- `change_reasons`.

`review_required` items remain in `events` and carry `deduplication_review`, `matched_previous_id`, and `deduplication_reasons`. They must be reviewed before delivery. Matching is one-to-one, and conflicting jurisdictions, platforms, or seller markets are isolated even when an ID or source page is reused.

## Coverage ledger fields

Each `coverage_ledger` entry requires:

- `platform`, `seller_market`, and `program` strings; use `unknown` when not established;
- `lookback_start`: ISO 8601 date-time with a UTC offset; use at least a seven-day platform lookback;
- `public_update_checked`, `current_policy_checked`, and `dashboard_checked` booleans;
- `access_result`: `public_checked`, `login_required`, `blocked`, `checked_authenticated`, `not_checked`, or `not_applicable`;
- `checked_at`: ISO 8601 date-time with a UTC offset;
- `sources_checked`: a non-empty array of opened-page evidence items. Each item requires `source_type`, direct `url`, `result`, `checked_at`, and `notes`;
- `verified_event_ids`: an array containing the stable IDs of verified platform events produced by that ledger row;
- `gaps`: an array of concise strings.

Allowed source types are `official_updates`, `current_policy`, `dashboard`, and `discovery_lead`. Allowed results are `no_relevant_update`, `candidate_found`, `verified_event`, `login_required`, `blocked`, and `not_applicable`. Positive coverage booleans must be supported by a matching source type in `sources_checked`. Every platform named in the root `scope` must have at least one matching ledger entry.

New acquisition-driven runs may attach `acquisition_receipt` to each source. It requires `task_id` (a 24-character lowercase SHA-256 prefix), `retrieval_method`, `attempts`, nullable `http_status` from 100 through 599, nullable lowercase SHA-256 `content_hash`, nullable portable POSIX `content_ref`, nullable `error_type`, and boolean `route_verified`. Authenticated-browser receipts must not contain a `content_ref`.

Use `login_required` only when an authentication gate was observed. Use `blocked` when the connection, region, security layer, robots policy, or browser policy prevented access before authentication could be established.

An opened `official_updates` or `current_policy` source with result `no_relevant_update`, `candidate_found`, or `verified_event` requires `snapshot`. Generate it with `scripts/snapshot_platform_page.py`. The backward-compatible fields are `snapshot_id`, `captured_at`, the lowercase SHA-256 `content_hash`, nullable `previous_snapshot_id`, `change_status` (`first_seen`, `unchanged`, or `changed`), `diff_summary`, `snapshot_path`, and nullable `diff_path`. A `changed` or `unchanged` snapshot must reference the previous snapshot; `first_seen` must not.

New captures also contain `storage_backend`, relative POSIX `snapshot_ref`, nullable relative POSIX `diff_ref`, and boolean `index_recovered`. When any portable storage field is present, all four are required. Refs must not be absolute, contain `..`, or use backslashes. Absolute path fields remain for compatibility with existing local workflows; portable consumers should prefer the refs. Git captures additionally require lowercase `git_commit` and `git_tree` object IDs.

Bundled `storage_backend` values are `filesystem`, `sqlite`, and `git`. Filesystem refs identify files relative to the store root. SQLite refs are logical paths identifying rows inside the database; `snapshot_path` and `diff_path` combine the absolute database path with a row fragment for backward-compatible traceability. Git refs identify committed files relative to the dedicated repository root, while `git_commit` and `git_tree` bind the report metadata to exact Git objects. Consumers must not assume every portable ref is directly openable as a filesystem file.

Create stable `id` values from jurisdiction, rule/program, and year. Keep the same ID across daily reports unless the event represents a distinct legal instrument or implementation change.

## Marketplace-policy fields

`platform_policy` and `action_items` are optional for backward compatibility, but both are required by the research workflow for newly reviewed marketplace-policy events.

`platform_policy` requires:

- `platform`: a registered display name or alias, or the official name of another channel;
- `seller_market`: the country/region whose seller rule was verified, or `unknown` when the source does not establish it;
- `program`: operating model, plan, feature, fulfillment model, or seller program; use `unknown` when not established;
- `policy_area`: one value from the taxonomy in `platform-policy-monitoring.md`;
- `change_type`: `new_rule`, `rule_change`, `enforcement_change`, `fee_change`, `feature_change`, `deadline`, or `clarification`;
- `seller_scope`: the affected account, seller, category, SKU, order, or feature population;
- `previous_state`: a string or `null`; never reconstruct an unsupported previous rule;
- `new_state`: the verified current obligation or behavior;
- `enforcement_consequence`: the verified consequence, or `not stated`;
- `backend_verification_required`: boolean.

Registered platforms are resolved through `src/daily_trade_radar/platforms/data/`. For an unregistered channel, also require `registry_status: "custom"` and `official_entry_verification_required: true`. A registered platform may omit these fields or use `registry_status: "registered"`; it must not claim that custom-entry verification is required.

Each `action_items` entry requires nonblank `owner`, `action`, `deadline`, and `completion_evidence` strings. `deadline` can be an ISO date or an explicit horizon such as `today`, `within 48 hours`, or `before the platform effective date`. Split actions when owners or completion evidence differ.

The top-level `action` remains required. It is the concise management summary; `action_items` is the operational checklist.

## Markdown order

1. Title, date, timezone, cutoff, and scope.
2. Today's judgment in one short paragraph.
3. Main radar table ordered by level, urgency, and date.
4. Priority actions.
5. Platform policy analysis when structured platform events exist.
6. Deduplication note.
7. Watchlist for unconfirmed or low-evidence items.
8. Coverage gaps.
9. Platform coverage ledger when platform checks were performed.
10. Official sources.
11. Tomorrow's watch.
