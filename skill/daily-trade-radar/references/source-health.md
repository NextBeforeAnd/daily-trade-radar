# Source health

The source-health layer derives an operator-facing audit from the platform registry, acquisition manifests, and receipts. It does not change receipt results or claim that a successful HTTP request proves a policy event.

## Commands

```text
daily-trade-radar doctor
daily-trade-radar doctor --platform Shopify
daily-trade-radar doctor --probe --platform Shopify --timeout 10
daily-trade-radar doctor --postmortem radar-runs/2026-07-31 --json --output source-health.json
daily-trade-radar doctor --manifest manifest.json --receipt receipt.json --json
```

The default command is a registry inventory. It reports registered routes as `not_checked` and declared source gaps as `not_configured`.

`--probe` performs bounded, read-only HTTP checks of public registered routes. It never probes authenticated dashboards, changes seller settings, or persists authenticated content. A successful probe normally remains `partial` because candidate text still needs substantive review and a public-page snapshot.

`--postmortem` scans a run path for acquisition manifests and receipts, binds every receipt to its exact task, selects the latest receipt per task, and reports missing tasks instead of silently treating them as checked. Unrelated JSON files are ignored; malformed files that identify themselves as acquisition artifacts fail closed.

## Audit states

- `ok`: a verified event receipt completed the required route and snapshot checks;
- `no_relevant_update`: the route was substantively checked, with the required public snapshot, and no relevant update was found;
- `partial`: access succeeded but review, route verification, applicability, or snapshot work remains;
- `blocked`: security, connection, or other access denial;
- `login_required`: an actual authentication gate was observed;
- `timeout`: the bounded request expired;
- `rate_limited`: the source returned a rate-limit signal such as HTTP 429;
- `schema_drift`: the source response no longer matched the expected parser or structure;
- `not_configured`: the registry declares a source-type gap;
- `not_checked`: a route exists but has no receipt in the audited run.

Never translate `blocked`, `timeout`, `rate_limited`, `login_required`, or `not_checked` into “no update.” A healthy access result still requires primary-source reading before any policy claim is made.
