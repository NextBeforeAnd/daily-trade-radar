# History library and event drill

The local history library indexes validated radar JSON only. It stores report metadata and public event fields in a user-selected SQLite database. It does not ingest acquisition caches, authenticated browser text, seller messages, credentials, or account exports.

## Build and search the library

```text
daily-trade-radar library ingest daily-trade-radar.json --db radar-library.sqlite3
daily-trade-radar library ingest radar-runs --db radar-library.sqlite3
daily-trade-radar library search "EU battery regulation" --db radar-library.sqlite3
daily-trade-radar library show EVENT_ID --db radar-library.sqlite3
daily-trade-radar library stats --db radar-library.sqlite3
```

Directory ingestion skips unrelated or invalid JSON and reports every skipped path. Explicitly ingesting one invalid report fails closed. A report identity is derived from its report date, cutoff, and scope; re-importing the same run replaces that run atomically instead of duplicating sightings.

Events are joined across reports by stable event ID. Search uses SQLite FTS5 when available and a portable field search fallback. Results expose the first and latest sighting, sighting count, source report path, and the full stored event for every run. Semantic aliases remain the responsibility of the existing reviewed deduplication workflow; the library does not silently merge different IDs.

## Drill one event

```text
daily-trade-radar drill EVENT_ID --report daily-trade-radar.json --output drill-plan.json
daily-trade-radar drill EVENT_ID --library radar-library.sqlite3 --refresh --output drill-plan.json
```

The drill command creates a focused verification plan. It does not browse or modify the event. The plan contains:

- the latest baseline event and all historical sightings;
- the cited primary URL and relevant registered platform routes;
- queries for current consolidated text, amendments, corrigenda, implementation guidance, dates, scope, and enforcement;
- required outputs for a refreshed snapshot, material-change comparison, applicability finding, verified dates, and completion evidence;
- a fail-closed promotion gate.

An unconfirmed or evidence-zero event uses `confirmation` mode and must remain watch-level. Other events use `revalidation` mode. `--refresh` requests fresh access for the drill run but does not bypass authentication, access controls, or the normal receipt and snapshot requirements.
