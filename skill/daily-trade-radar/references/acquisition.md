# Auditable acquisition

The acquisition layer turns a research plan into deterministic route tasks and evidence receipts. It supplements Codex browsing; it does not replace source judgment or crawl arbitrary sites.

## Workflow

1. Build a manifest from registered platform routes. Platform windows must span at least seven days.
2. Open each task through the appropriate adapter: bounded HTTP for public pages, supplied RSS/Atom/sitemap XML for discovery, or manual/browser recording for interactive pages.
3. Save one receipt for every outcome, including failures. Stable task IDs make reruns cacheable and auditable.
4. Convert the manifest and latest receipts into draft `coverage_ledger` rows. Missing receipts, unverified country routes, and public policy pages without snapshots become explicit gaps.
5. Review the opened primary sources, attach snapshots, verify events, and populate `verified_event_ids`. A content hash or receipt alone cannot establish a changed rule.

With the package installed:

```text
daily-trade-radar acquisition manifest --platform Shopify --seller-market SG --program Shopify --window-start "2026-07-20T00:00:00+08:00" --cutoff "2026-07-28T00:00:00+08:00" --output manifest.json
daily-trade-radar acquisition receipt --manifest manifest.json --task-id TASK_ID --checked-at "2026-07-28T00:00:00+08:00" --result candidate_found --method browser_public --notes "Opened dated changelog entry" --content-file visible.txt --cache acquisition-cache --snapshot snapshot.json --output receipt.json
daily-trade-radar acquisition fetch --manifest manifest.json --task-id TASK_ID --checked-at "2026-07-28T00:00:00+08:00" --cache acquisition-cache --cache-ttl 86400 --output receipt.json
daily-trade-radar acquisition coverage --manifest manifest.json --receipt receipt.json --output coverage-ledger.json
daily-trade-radar acquisition xml --input feed.xml --kind auto --output discovery.json
```

The Python API also exposes `HttpAdapter`, which uses per-host rate limiting, bounded response sizes, retries for transient failures, and a receipt cache. Reusable successful receipts expire after 24 hours by default. Use `--refresh` to bypass a reusable receipt. Login gates, blocked requests, connection failures, and missing routes are recorded but never reused, so a later run tries the route again. XML parsers only process supplied files and never follow links.

Manifests also preserve registry `planning_gaps` for missing official-update, current-policy, or dashboard source types. A route whose declared markets do not include the requested seller market is retained only as a lead and is marked as requiring route verification before citation.

Task IDs are 24-character lowercase SHA-256 prefixes derived from the platform, market, program, source type, URL, and lookback start. Manifest IDs cover the creation time, window, cutoff, and complete task objects. Loading altered identity fields or attaching a receipt to a different manifest task fails closed. The cache writes an immutable content-derived copy of every receipt under `receipt-history/` while keeping the latest receipt for bounded reuse.

## Privacy and evidence boundaries

- Public normalized text may be stored in a content-addressed cache.
- Authenticated browser text is hashed for receipt correlation but is never written to the content cache. Only the non-content receipt metadata is saved.
- Never pass seller PII, account exports, messages, or credentials to the public HTTP adapter or public-content cache.
- A search snippet, discovery feed entry, HTTP 200 response, or first-seen snapshot is not proof of a policy change. Open and read the platform-owned page.
- The acquisition CLI is intentionally read-only. It does not acknowledge notices, submit forms, change seller settings, or bypass access controls.

## Receipt fields

Receipts record the task/platform scope, requested and final URLs, source and result types, checked time, retrieval method, attempt count, route-verification status, HTTP status/error, normalized content hash and optional portable content reference, and optional snapshot metadata. `browser_authenticated` receipts must have a null `content_ref`. Receipt paths accept only derived task IDs, and portable content references cannot be absolute, traverse with `..`, or escape the cache root through a symlink.
