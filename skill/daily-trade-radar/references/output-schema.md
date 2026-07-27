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
            "diff_path": null
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

Require the original root and event fields shown above. `window_start`, `coverage_ledger`, `published_at`, `effective_at`, `deadline_at`, and `source_timezone` are backward-compatible optional fields, but new reports must populate them when the information exists. Use ISO `YYYY-MM-DD` dates and ISO 8601 date-times with UTC offsets. Permit `null` only when an exact date or time genuinely does not exist. Use one of `new`, `effective`, `deadline`, `ongoing`, or `unconfirmed` for status and one of `high`, `medium`, `low`, or `watch` for level.

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

Use `login_required` only when an authentication gate was observed. Use `blocked` when the connection, region, security layer, robots policy, or browser policy prevented access before authentication could be established.

An opened `official_updates` or `current_policy` source with result `no_relevant_update`, `candidate_found`, or `verified_event` requires `snapshot`. Generate it with `scripts/snapshot_platform_page.py`. The object contains `snapshot_id`, `captured_at`, the lowercase SHA-256 `content_hash`, nullable `previous_snapshot_id`, `change_status` (`first_seen`, `unchanged`, or `changed`), `diff_summary`, `snapshot_path`, and nullable `diff_path`. A `changed` or `unchanged` snapshot must reference the previous snapshot; `first_seen` must not.

Create stable `id` values from jurisdiction, rule/program, and year. Keep the same ID across daily reports unless the event represents a distinct legal instrument or implementation change.

## Marketplace-policy fields

`platform_policy` and `action_items` are optional for backward compatibility, but both are required by the research workflow for newly reviewed marketplace-policy events.

`platform_policy` requires:

- `platform`: `TikTok Shop`, `Temu`, `Shopify`, `Jumia`, `Amazon`, `AliExpress`, or the official name of another channel;
- `seller_market`: the country/region whose seller rule was verified, or `unknown` when the source does not establish it;
- `program`: operating model, plan, feature, fulfillment model, or seller program; use `unknown` when not established;
- `policy_area`: one value from the taxonomy in `platform-policy-monitoring.md`;
- `change_type`: `new_rule`, `rule_change`, `enforcement_change`, `fee_change`, `feature_change`, `deadline`, or `clarification`;
- `seller_scope`: the affected account, seller, category, SKU, order, or feature population;
- `previous_state`: a string or `null`; never reconstruct an unsupported previous rule;
- `new_state`: the verified current obligation or behavior;
- `enforcement_consequence`: the verified consequence, or `not stated`;
- `backend_verification_required`: boolean.

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
