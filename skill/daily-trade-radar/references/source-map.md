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

## Maritime chokepoints and material logistics

- Run this track on every radar, even when the user supplies no logistics keyword. At minimum check the Strait of Hormuz, Bab el-Mandeb and the Red Sea, the Suez Canal, and the Panama Canal. Include the South China Sea, Taiwan Strait, and Black Sea when a material incident, closure, port restriction, or security advisory is reported.
- Open UKMTO recent incidents and advisories, IMO maritime-security/topic pages, JMIC or Maritime Security Centre Indian Ocean products when available, U.S. MARAD Maritime Security Communications with Industry notices, and the relevant canal, port, coast-guard, or navigation authority.
- Run both a reporting-window check and a rolling seven-day backfill. Search for vessel attacks, projectiles, seizures, collisions, groundings, closures, reopening, safe-navigation notices, draft or transit restrictions, congestion, rerouting, service suspension, insurance limits, and emergency surcharges.
- Treat a material incident whose event time falls inside the reporting window as a candidate even when a carrier has issued no new notice. Record the incident time and source publication time separately.
- Use carrier notices to confirm operational consequences such as suspension, rerouting, acceptance limits, insurance requirements, or surcharges. Do not infer “no material logistics change” from carrier silence or from checking carrier pages alone.
- Treat negotiations, reported progress, or political assurances about reopening as unconfirmed operational status until a current navigational authority or direct maritime notice confirms the change.
- If a mandatory direct route cannot be opened, disclose that exact coverage gap. Do not replace it with a no-update conclusion.

## Marketplaces and carrier operations

- Use official seller announcements, help centers, release notes, and policy pages from the relevant marketplace.
- Use carrier, postal authority, port, canal authority, and customs notices for operational logistics changes after completing the mandatory maritime-chokepoint track.
- Treat seller forums as primary only when the post is authored by an identifiable official platform account.
- For every registered marketplace in scope, load the platform configuration from `src/daily_trade_radar/platforms/data/`, then follow the snapshot workflow, coverage ledger, taxonomy, and applicability gate in [platform-policy-monitoring.md](platform-policy-monitoring.md).
- Treat each platform + seller market + operating program as a separate monitoring scope. A rule observed in one market or program is not evidence for another.

## Search sequence

1. Search mandatory authority sites for publications inside the reporting window.
2. Open the mandatory maritime-security routes and run the named-chokepoint reporting-window and seven-day checks.
3. Run the product-neutral seven-day discovery and missed-item backfill.
4. Search by the user's products, HS codes, markets, and platforms.
5. Search for rules taking effect or expiring in the next 30 days.
6. Recheck ongoing high-risk topics from the previous radar.
7. Open every cited page and record publication, incident, and effective dates separately.
8. For platform events, recheck the current underlying policy and extract structured `platform_policy` and `action_items` fields.

Record inaccessible or unsearched sources as coverage gaps. Do not imply exhaustive monitoring when access was incomplete.
