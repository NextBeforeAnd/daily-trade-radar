# Early-signal discovery

Use discovery to decide which unresolved leads deserve primary-source verification first. Discovery priority is not regulatory risk, does not alter the five-dimension event score, and cannot promote a lead to the main action table.

## Input and command

Provide a cutoff, optional scope, and normalized leads:

```json
{
  "cutoff": "2026-07-31T12:00:00+08:00",
  "scope": {
    "regions": ["EU"],
    "platforms": ["Amazon"],
    "products": ["LED lighting"],
    "hs_codes": ["940510"]
  },
  "leads": [
    {
      "source_title": "Possible seller-document change",
      "source_url": "https://trade.example/article",
      "source_name": "Trade Example",
      "source_tier": "trade_media",
      "source_type": "trade_media",
      "published_at": "2026-07-31T08:00:00+08:00",
      "retrieved_at": "2026-07-31T10:00:00+08:00",
      "jurisdiction": "EU",
      "platform": "Amazon",
      "products": ["LED lighting"],
      "hs_codes": ["940510"],
      "claim": "The source claims that seller documents may change.",
      "momentum_score": 0,
      "momentum_evidence": ""
    }
  ]
}
```

```text
daily-trade-radar discover leads.json --output discovery.json
```

Accepted source tiers range from official or platform-owned previews to industry associations, carriers, trade media, seller forums, social posts, and other leads. A positive `momentum_score` requires written momentum evidence.

## Priority and clustering

The 0-100 priority is the sum of:

- recency, up to 25;
- cross-domain corroboration, up to 30;
- business-scope relevance, up to 20;
- source quality, up to 20;
- explicitly evidenced momentum, up to 5.

This is a verification-work queue. It is unrelated to the report's regulatory-force, exposure, urgency, consequence, and evidence risk score.

Leads cluster by canonical URL, shared regulatory identifiers, or sufficiently similar claims and titles. Known jurisdiction or platform conflicts prevent merging, including transitive merging through an unknown-scope lead. Corroboration counts distinct source domains, so multiple pages from one publisher do not create false cross-source confirmation.

Every emitted cluster has `event_status: unconfirmed`, `risk_level: watch`, and `promotion_eligible: false`. When no cluster reaches the threshold, return `nothing_solid` with at most one weak signal instead of ranking noise. Open a direct primary or platform-owned source and verify operative text, dates, and applicability before creating or promoting an event.
