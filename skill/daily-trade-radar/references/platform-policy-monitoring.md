# Marketplace policy monitoring

Use this generic playbook for every platform registered in `src/daily_trade_radar/platforms/data/`. The registry supplies canonical names, aliases, seller markets, programs, official entry routes, dashboard checks, policy areas, applicability dimensions, and platform-specific cautions. Marketplace rules are market-specific: never transfer a US requirement to the UK, EU, Africa, or another seller program without a source that states the same scope.

## Registry-driven setup

1. Resolve every platform named in scope through the registry. `python -m daily_trade_radar platforms --json` prints the installed configuration.
2. Review the registry's `source_depth` result and declared source gaps. Use registered routes as navigation starting points, not proof that a page was checked. A `conditional` route or seller-market mismatch must be confirmed against the platform-owned country portal before citation.
3. Use `seller_markets`, `programs`, `dashboard_checks`, and `applicability_dimensions` to form separate monitoring rows and search tracks.
4. Adding a registered platform requires one JSON configuration and registry tests; it does not require a new validation branch.
5. For an unregistered channel, use `registry_status: custom` and `official_entry_verification_required: true`, record the platform-owned entry that still needs confirmation, and keep applicability provisional.

Every configured route declares a stable `route_id`, `markets`, `access` (`public`, `authenticated`, or `mixed`), `evidence_role`, `verification_status`, and nullable `last_verified_on`. Every platform expects update, current-policy, and dashboard coverage; a missing type requires a nonblank `source_profile.known_gaps` reason. `full` depth means all three source types plus a verified public route; `hybrid` or `constrained` depth must remain visible as a coverage limitation.

## Mandatory discovery pass

Create an acquisition manifest for the selected platform, seller market, program, seven-day window, and cutoff before opening routes. Record each route outcome as an acquisition receipt, including blocked, login-required, and not-applicable results. Convert receipts into the initial coverage ledger, then add verified event IDs and concise executive coverage gaps during review. See [acquisition.md](acquisition.md).

Run this pass even when the main 24-hour search finds no platform event:

1. Set `platform_window_start` to seven calendar days before the cutoff. Extend to 30 days for an undated current-policy page, a newly discovered source, or a platform whose public pages are indexed late.
2. Establish a platform + seller market + program row. If the user did not provide the market or program, check only public global/update routes and mark applicability `unknown`; do not fabricate a seller-specific result.
3. Open the official update/changelog route and at least one underlying current-policy page when an apparent change exists. Save their normalized visible text with `scripts/snapshot_platform_page.py` and attach the returned snapshot metadata to the source evidence.
4. When the in-app browser is available, open the seller dashboard and inspect notifications, policy center, account health, logistics, settlement, and category qualification. Treat an existing signed-in session as readable context, but do not click acknowledgement, submission, appeal, or settings controls without user authorization.
5. Search the web separately for discovery leads using the platform name, seller market, program, and each taxonomy area. Open promising results. A secondary article, agency post, seller forum, or social post may create an `unconfirmed` event but cannot confirm a binding rule.
6. Record every opened page in `sources_checked`. Record `no_relevant_update`, `candidate_found`, `verified_event`, `login_required`, `blocked`, or `not_applicable`; never backfill a check from memory or a search snippet.
7. Add verified event IDs to `verified_event_ids`. If no verified event remains, retain credible unresolved leads in the watchlist and explicitly report `no material new item found` for the checked platform/market.

Treat snapshot outcomes carefully:

- `first_seen` creates a baseline and cannot by itself establish a before/after rule change;
- `unchanged` means the normalized captured text did not change from the immediately preceding snapshot;
- `changed` supplies a historical diff, but the changed text must still be read for scope, dates, obligation, and enforcement;
- an explicit platform changelog can verify a change without a prior snapshot, but cite both the changelog and the current underlying policy when available.

Do not classify a government tax, customs, sanctions, or product rule as a `platform_policy` event merely because it affects merchants using that platform. Keep the regulatory event in its own jurisdiction and mention the platform only in impact or action unless the platform separately changes its own terms, workflow, fees, or enforcement.

## Coverage ledger

For every platform and relevant market, record these checks in the research notes and final `coverage_ledger`:

1. Public policy-update page or changelog.
2. Current policy/help-center page for any apparent change.
3. Seller dashboard inbox, policy center, or account notice when access is available.
4. Terms, fee schedules, product restrictions, and enforcement pages when implicated.
5. The platform lookback start, each opened URL, source type, result, last checked time, resulting event IDs, and any login, region, language, or indexing gap.

If a seller-only source cannot be accessed, try the in-app browser before recording a gap. Add a concrete `coverage_gaps` entry when access still fails. A search snippet, seller forum, agency post, or news article may identify a lead, but cannot confirm a binding platform rule. Preserve a credible unresolved lead as an `unconfirmed` watchlist event with a direct link to the lead and an action naming the official source or dashboard location that must confirm it.

Record `login_required` only when an authentication screen or authenticated-session requirement is observed. Record `blocked` for connection closure, access denial, regional/security blocking, robots denial, or browser-policy rejection. A blocked page is not evidence that login would have succeeded.

## Official-source routes

URLs and navigation can vary by seller market. Confirm that the page is owned by the platform and states the applicable market before citing it.

The JSON registry is the machine-readable source for entry routes. The platform notes below retain research judgment for the original platforms and Alibaba.com. Shopee, Lazada, eBay, and Walmart Marketplace use the same mandatory discovery pass; their configured dashboard checks and applicability dimensions replace the need for hard-coded validation logic.

### TikTok Shop

- Start with the market-specific TikTok Shop Academy/University and its **New and updated** or **Policy Center updates** area. For the United States, the public host is `seller-us.tiktok.com/university/`.
- Recheck the underlying policy page because monthly Policy Pulse summaries can combine changes with different dates and scopes.
- When available, check Seller Center notifications, Account Health, Shop Performance Score, logistics, settlements, category qualification, and creator/affiliate notices.
- Search separately for seller, creator, affiliate, LIVE/content, listing, prohibited/restricted products, fulfillment SLA, returns/refunds, fees, settlement, account health, violations, and appeals.
- If no seller market was provided, run public discovery against the global/public entry and the United States update route, but label the seller market as `unknown` until a source establishes applicability.

### Temu

- Start at the official Seller Center (`seller.temu.com`) and its Seller Academy/help material.
- Treat Seller Center announcements, account messages, product-compliance requests, pricing notices, logistics/warehouse instructions, after-sales rules, penalties, and settlement statements as the authoritative seller-specific layer.
- Public pages are often incomplete. State explicitly when login-only announcements or a mainland-China/Hong Kong seller program were not checked.
- Separate fully managed, semi-managed, local-seller, and other operating models; do not assume one program's fee, fulfillment, pricing, or return rule applies to another.
- If no operating model was provided, search fully managed, semi-managed, and local-seller notices as separate discovery tracks. Keep all applicability provisional until the source states the model and market.

### Shopify

- Check the official Shopify Changelog (`changelog.shopify.com`) for dated product and workflow changes.
- Check the Shopify Help Center (`help.shopify.com`) for current operational requirements and Shopify Legal (`shopify.com/legal`) for binding terms and policies.
- Distinguish Shopify's platform terms from the merchant's legal obligations, and distinguish Shopify, Shop, Shopify Payments, Managed Markets, Markets, POS, apps, and plan-specific features.
- Search for checkout, payments/payouts, tax and duties, Markets/Managed Markets, shipping, returns, subscriptions, privacy/data, Shop channel eligibility, product restrictions, app/API deprecations, and plan availability.
- Treat Changelog entries as platform changes only after opening the dated entry. Treat laws reflected in Help Center guidance as regulatory events unless Shopify itself changes a product, term, workflow, fee, or enforcement state.

### Jumia

- Start with the official Jumia VendorHub (`vendorhub.jumia.com`) and the market-specific Seller Center/Vendor Center linked by Jumia.
- Check seller announcements, Jumia University/training, commission and fee tables, product and content rules, fulfillment/drop-off/warehouse instructions, returns, penalties, account quality, and payment schedules.
- Record the exact country because seller rules, commissions, fulfillment models, and portals vary across Jumia markets.
- If the relevant Vendor Center requires authentication or is not publicly indexed, log the market and missing source as a coverage gap rather than generalizing from another country.
- If no country was provided, open VendorHub and enumerate the currently linked country portals. Do not claim those countries were policy-checked until their own update or Vendor Center routes were opened.

### Amazon

- Treat each Amazon store and program separately. Record the marketplace (for example US, UK, Germany, Japan) and whether the rule applies to FBA, FBM, Brand Registry, Amazon Business, advertising, payments, or another program.
- Start with Seller Central **Seller News** and the marketplace-specific News and Announcements category. Public posts authored by `News_Amazon` or another clearly identified Amazon account can be official evidence; ordinary seller replies remain secondary discovery leads.
- Open the linked Seller Central Help policy, fee schedule, program policy, or agreement whenever a news item announces a rule change. Do not rely only on a forum headline or seller summary.
- When authenticated access is available, check Performance Notifications, Account Health, Manage Your Compliance, FBA inventory/fee notices, Payments, Voice of the Customer, and marketplace-specific Seller News.
- Search separately for referral and FBA fees, storage/capacity, product compliance, restricted products, listing/content rules, returns/refunds, fulfillment SLAs, account health, disbursement, tax, advertising, API/developer, and Brand Registry changes.
- If no marketplace was provided, check the public US Seller News route for discovery only and keep seller-market applicability `unknown` until the source establishes it.

### AliExpress

- Start at the official seller portal (`seller.aliexpress.com` or `sell.aliexpress.com`) and follow its current Rules/Announcements/Academy navigation. Do not use the retired unauthenticated `rulechannel.aliexpress.com` route as evidence when it redirects to an error page.
- Separate China-mainland cross-border sellers, local sellers, managed/Choice programs, warehouse or fulfillment programs, and market-specific operations. Do not generalize deposits, commissions, penalties, logistics SLAs, or category restrictions across programs.
- When authenticated access is available, check seller announcements, violation/penalty messages, category access, product compliance, logistics and warehouse notices, after-sales disputes, funds/settlement, and store assessment notices.
- Search separately for category and prohibited-product rules, listing/content, pricing and promotions, commissions/deposits, Choice/managed programs, logistics SLAs, returns/refunds, intellectual property, penalties, settlement, and data/API changes.
- If the seller portal is public but its rule feed requires authentication, record the public entry as checked and the rule feed/dashboard as `login_required`; if the site closes the connection or rejects the region, record `blocked` instead.

### Alibaba.com

- Treat Alibaba.com (阿里巴巴国际站) as a separate B2B marketplace from AliExpress. Never merge their rules, seller programs, or evidence.
- Start with the Alibaba.com Rule Center (`rulechannel.alibaba.com/icbu?type=detail`) for dated rule announcements and the Alibaba.com Seller Central pages for current onboarding and product-control requirements.
- When authenticated access is available, check My Alibaba notifications, rule and violation messages, business verification, product qualification, intellectual property, Trade Assurance, logistics, payments, RFQ, and supplier-rating notices.
- Separate Gold Supplier, Verified Supplier, Trade Assurance, RFQ, and country-specific seller programs. Keep the seller market and program `unknown` when the source does not establish them.
- Cite the direct rule detail or current-policy page, not only the Rule Center index or a Seller Central marketing page. Record My Alibaba as `login_required` only after observing the authentication gate.

## Evidence requirements

Each `coverage_ledger.sources_checked` item must contain:

- `source_type`: `official_updates`, `current_policy`, `dashboard`, or `discovery_lead`;
- `url`: the direct page opened, never a search-results URL;
- `result`: `no_relevant_update`, `candidate_found`, `verified_event`, `login_required`, `blocked`, or `not_applicable`;
- `checked_at`: ISO 8601 date-time with a UTC offset;
- `notes`: a concise description of what was or was not established.

New runs should also include the generated `acquisition_receipt` metadata. It binds the source entry to a stable task ID and records the retrieval method, attempt count, response status, content hash/reference, route-verification state, and observed error. It is operational provenance, not substantive evidence of a policy change.

For an opened `official_updates` or `current_policy` source whose result is `no_relevant_update`, `candidate_found`, or `verified_event`, also include the `snapshot` object returned by `snapshot_platform_page.py`. Keep the persistent snapshot store outside the skill package, normally beside the radar run history.

Set `public_update_checked`, `current_policy_checked`, or `dashboard_checked` to `true` only when `sources_checked` contains the corresponding source type. A generic search query does not satisfy any of those booleans.

## Policy taxonomy

Assign one `policy_area` value to a marketplace-policy event:

- `onboarding_kyc`
- `listing_product_compliance`
- `pricing_promotions`
- `fees_commissions`
- `fulfillment_logistics`
- `returns_refunds_aftersales`
- `payments_settlement_tax`
- `content_ads_affiliate`
- `data_privacy_security`
- `account_health_enforcement`
- `api_feature_deprecation`
- `other`

Assign one `change_type`: `new_rule`, `rule_change`, `enforcement_change`, `fee_change`, `feature_change`, `deadline`, or `clarification`.

## Analysis and action extraction

For each verified platform event, populate `platform_policy` and `action_items` as defined in [output-schema.md](output-schema.md). Extract rather than paraphrase loosely:

- exact platform, seller market, program/model, and affected seller/account/SKU/order population;
- previous state and new state when both are evidenced;
- publication, notice, effective, grace-period, and enforcement dates separately;
- thresholds, fees, SLAs, document requirements, exceptions, and enforcement consequence;
- whether the rule is automatic, requires configuration, or requires seller submission;
- the dashboard path or report needed to identify exposed objects;
- one action per owner, each with a time horizon and completion evidence.

Do not invent a previous state when only the current rule is available. Use `null` and say that the prior state was not established. Keep the legacy top-level `action` as a concise executive summary; `action_items` is the auditable execution list.

## Applicability gate

Before assigning business exposure above 1, establish at least the platform and seller market plus one of: seller program/model, product/category, fulfillment mode, payment product, feature/plan, or directly affected account notice. If those facts are missing, write a verification action and keep the exposure score provisional.
