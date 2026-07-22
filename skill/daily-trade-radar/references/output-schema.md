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
      "retrieved_date": "2026-07-21"
    }
  ]
}
```

## Required event fields

Require all fields shown above. Permit `null` only for dates that genuinely do not exist. Use ISO `YYYY-MM-DD` dates. Use one of `new`, `effective`, `deadline`, `ongoing`, or `unconfirmed` for status and one of `high`, `medium`, `low`, or `watch` for level.

Create stable `id` values from jurisdiction, rule/program, and year. Keep the same ID across daily reports unless the event represents a distinct legal instrument or implementation change.

## Markdown order

1. Title, date, timezone, cutoff, and scope.
2. Today's judgment in one short paragraph.
3. Main radar table ordered by level, urgency, and date.
4. Priority actions.
5. Deduplication note.
6. Watchlist for unconfirmed or low-evidence items.
7. Coverage gaps.
8. Official sources.
9. Tomorrow's watch.
