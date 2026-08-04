# Research planning

Create a research plan before browsing when the radar covers more than one jurisdiction, product, HS code, or marketplace. The plan is a deterministic research contract, not evidence and not a replacement for opening sources.

## Scope input

The scope JSON accepts:

- `created_at`, `window_start`, `cutoff`, and optional `deadline_end`, all as ISO 8601 timestamps with UTC offsets;
- `language`;
- `regions`, `products`, `hs_codes`, `keywords`, and `priority_themes` arrays;
- `platforms`, whose entries may be registered display names or objects with `platform`, `seller_market`, and `program`.

When time fields are omitted, the builder uses the current local cutoff, a trailing 24-hour reporting window, and a 30-day upcoming deadline window. When regions are omitted, it uses China, the United States, and the European Union. When the `platforms` field is omitted, every registered cross-border channel is planned with market and program marked `unknown`; pass an explicit empty array to exclude platform monitoring. Platform names must resolve through the bundled registry; unknown markets or programs remain explicitly `unknown` rather than being inferred.

```json
{
  "cutoff": "2026-07-31T09:00:00+08:00",
  "regions": ["European Union"],
  "products": ["LED lighting"],
  "hs_codes": ["9405.10"],
  "platforms": [
    {"platform": "Amazon", "seller_market": "DE", "program": "FBA"}
  ]
}
```

## Build and validate

```text
daily-trade-radar plan --scope scope.json --output research-plan.json --manifest-dir manifests
daily-trade-radar plan --validate research-plan.json
```

The plan always contains official-publication, upcoming-effective/deadline, and secondary-lead tracks. The secondary-lead track is a rolling seven-day backfill for late-indexed and previously missed government, product-regulator, and material logistics developments. United States default authority coverage includes FCC Covered List and equipment-authorization developments even when no product keywords were supplied. Product or HS-code scope adds a product-applicability track. Each scoped marketplace adds exactly one platform-policy track and one `manifest_request`. `--manifest-dir` materializes those requests through the existing platform registry, producing normal acquisition manifests with a minimum seven-day platform window.

Track evidence requirements are fixed:

- official, effective/deadline, and product tracks require primary evidence;
- marketplace tracks require platform-owned evidence;
- discovery leads are `lead_only` and may enter only the unconfirmed watchlist until confirmed.

The plan ID covers all timestamps, scope fields, tracks, queries, source URLs, and manifest requests. Edited or incomplete plans fail validation. A valid plan proves only that research was planned; receipts, opened pages, snapshots, and event verification remain required.
