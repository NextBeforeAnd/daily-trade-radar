# Marketplace policy monitoring

Use this playbook for TikTok Shop, Temu, Shopify, and Jumia. Marketplace rules are market-specific: never transfer a US requirement to the UK, EU, Africa, or another seller program without a source that states the same scope.

## Coverage ledger

For every platform and relevant market, record these checks in the research notes:

1. Public policy-update page or changelog.
2. Current policy/help-center page for any apparent change.
3. Seller dashboard inbox, policy center, or account notice when access is available.
4. Terms, fee schedules, product restrictions, and enforcement pages when implicated.
5. The last checked time, access result, and any login, region, language, or indexing gap.

If a seller-only source cannot be accessed, add a concrete `coverage_gaps` entry. A search snippet, seller forum, agency post, or news article may identify a lead, but cannot confirm a binding platform rule.

## Official-source routes

URLs and navigation can vary by seller market. Confirm that the page is owned by the platform and states the applicable market before citing it.

### TikTok Shop

- Start with the market-specific TikTok Shop Academy/University and its **New and updated** or **Policy Center updates** area. For the United States, the public host is `seller-us.tiktok.com/university/`.
- Recheck the underlying policy page because monthly Policy Pulse summaries can combine changes with different dates and scopes.
- When available, check Seller Center notifications, Account Health, Shop Performance Score, logistics, settlements, category qualification, and creator/affiliate notices.
- Search separately for seller, creator, affiliate, LIVE/content, listing, prohibited/restricted products, fulfillment SLA, returns/refunds, fees, settlement, account health, violations, and appeals.

### Temu

- Start at the official Seller Center (`seller.temu.com`) and its Seller Academy/help material.
- Treat Seller Center announcements, account messages, product-compliance requests, pricing notices, logistics/warehouse instructions, after-sales rules, penalties, and settlement statements as the authoritative seller-specific layer.
- Public pages are often incomplete. State explicitly when login-only announcements or a mainland-China/Hong Kong seller program were not checked.
- Separate fully managed, semi-managed, local-seller, and other operating models; do not assume one program's fee, fulfillment, pricing, or return rule applies to another.

### Shopify

- Check the official Shopify Changelog (`changelog.shopify.com`) for dated product and workflow changes.
- Check the Shopify Help Center (`help.shopify.com`) for current operational requirements and Shopify Legal (`shopify.com/legal`) for binding terms and policies.
- Distinguish Shopify's platform terms from the merchant's legal obligations, and distinguish Shopify, Shop, Shopify Payments, Managed Markets, Markets, POS, apps, and plan-specific features.
- Search for checkout, payments/payouts, tax and duties, Markets/Managed Markets, shipping, returns, subscriptions, privacy/data, Shop channel eligibility, product restrictions, app/API deprecations, and plan availability.

### Jumia

- Start with the official Jumia VendorHub (`vendorhub.jumia.com`) and the market-specific Seller Center/Vendor Center linked by Jumia.
- Check seller announcements, Jumia University/training, commission and fee tables, product and content rules, fulfillment/drop-off/warehouse instructions, returns, penalties, account quality, and payment schedules.
- Record the exact country because seller rules, commissions, fulfillment models, and portals vary across Jumia markets.
- If the relevant Vendor Center requires authentication or is not publicly indexed, log the market and missing source as a coverage gap rather than generalizing from another country.

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
