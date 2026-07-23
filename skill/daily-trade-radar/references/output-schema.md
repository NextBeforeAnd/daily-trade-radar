# Event data and report schema

Use UTF-8 JSON. The root object contains report metadata and an `events` array.

Set `language` to `zh-CN` for a Chinese Markdown report or to `en`/`en-US` for an English report. Write event text fields in the same language; the renderer translates report headings and fixed labels, not event content.

```json
{
  "report_date": "2026-07-21",
  "timezone": "Asia/Singapore",
  "cutoff": "2026-07-21T17:00:00+08:00",
  "language": "zh-CN",
  "scope": ["China", "EU", "US", "Amazon"],
  "coverage_gaps": [],
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

Require all fields shown above. Permit `null` only for dates that genuinely do not exist. Use ISO `YYYY-MM-DD` dates. Use one of `new`, `effective`, `deadline`, `ongoing`, or `unconfirmed` for status and one of `high`, `medium`, `low`, or `watch` for level.

Create stable `id` values from jurisdiction, rule/program, and year. Keep the same ID across daily reports unless the event represents a distinct legal instrument or implementation change.

## Marketplace-policy fields

`platform_policy` and `action_items` are optional for backward compatibility, but both are required by the research workflow for newly reviewed marketplace-policy events.

`platform_policy` requires:

- `platform`: `TikTok Shop`, `Temu`, `Shopify`, `Jumia`, or the official name of another channel;
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
9. Official sources.
10. Tomorrow's watch.
