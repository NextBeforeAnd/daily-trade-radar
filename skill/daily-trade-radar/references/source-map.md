# Source map

Use this file to plan searches, not as a guarantee that every site must be checked. Prefer the authority responsible for the rule.

## China

- Ministry of Commerce: export controls, trade remedies, sanctions and licensing.
- General Administration of Customs: customs announcements, inspection and quarantine, commodity classification.
- State Taxation Administration and Ministry of Finance: export tax rebates and tax policy.
- State Administration for Market Regulation and national standards bodies: product compliance and standards.

Query with the product name, HS code, authority name, and terms such as 公告, 征求意见, 生效, 出口管制, 法检, 许可证, 关税, 退税.

## European Union

- European Commission directorates: customs and taxation, trade, environment, climate, and product policy.
- EUR-Lex: final regulations, delegated acts, implementing acts, and corrigenda.
- Access2Markets: tariffs, origin, procedures, and product requirements.
- Safety Gate and relevant EU agencies when product alerts or technical rules matter.

## United States

- Federal Register for official notices and rules.
- BIS for export administration and Entity List changes.
- OFAC for sanctions.
- USTR for tariffs, exclusions, consultations, and trade actions.
- CBP for customs implementation.
- FCC Covered List, Daily Digest, press releases, and Public Safety and Homeland Security Bureau / Office of Engineering and Technology notices for equipment authorization, import, marketing, or new-model restrictions. Check these routes whenever the United States is in default scope, even without product keywords.
- FDA, CPSC, EPA, USDA, and other product regulators when in scope.

Use product-neutral United States queries as well as authority searches. Include terms such as `import ban`, `covered list`, `equipment authorization`, `national security determination`, `new models`, `marketing prohibition`, `advanced robotic devices`, and `connected power inverters`.

## Cross-source discovery and missed-item backfill

- Run a rolling seven-day discovery pass across credible wire services and major reporting in addition to direct authority searches. Use secondary results only as leads, then open the responsible authority's publication before promoting an event.
- Search without requiring a known product name. Combine each default jurisdiction with terms for import/export bans, certification or equipment authorization, covered/entity lists, sanctions, tariffs, customs, product safety, logistics disruption, and rules applying to new models.
- Compare discovery leads with the previous seven days of event JSON. Re-open and retain a material item that was missed by an earlier run; classify it by its real publication/effective timing and disclose that it was backfilled.
- Record every mandatory authority route that was not checked or could not be read as a coverage gap. Do not turn a partial authority checklist into a jurisdiction-wide no-update claim.

## Marketplaces and logistics

- Use official seller announcements, help centers, release notes, and policy pages from the relevant marketplace.
- Use carrier, postal authority, port, canal authority, and customs notices for logistics changes.
- Treat seller forums as primary only when the post is authored by an identifiable official platform account.
- For every registered marketplace in scope, load the platform configuration from `src/daily_trade_radar/platforms/data/`, then follow the snapshot workflow, coverage ledger, taxonomy, and applicability gate in [platform-policy-monitoring.md](platform-policy-monitoring.md).
- Treat each platform + seller market + operating program as a separate monitoring scope. A rule observed in one market or program is not evidence for another.

## Search sequence

1. Search mandatory authority sites for publications inside the reporting window.
2. Run the product-neutral seven-day discovery and missed-item backfill.
3. Search by the user's products, HS codes, markets, and platforms.
4. Search for rules taking effect or expiring in the next 30 days.
5. Recheck ongoing high-risk topics from the previous radar.
6. Open every cited page and record the publication/effective dates separately.
7. For platform events, recheck the current underlying policy and extract structured `platform_policy` and `action_items` fields.

Record inaccessible or unsearched sources as coverage gaps. Do not imply exhaustive monitoring when access was incomplete.
