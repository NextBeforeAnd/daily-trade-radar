# Scoring rules

Assign each event a numeric score, then map it to a level. Score the user's likely exposure, not the global importance of the headline.

## Score

- Regulatory force: 0 commentary only; 1 proposal/guidance; 2 final rule or binding platform policy.
- Business exposure: 0 out of scope; 1 possible/indirect; 2 clearly affects a supplied market, product, HS code, or channel.
- Urgency: 0 over 30 days; 1 within 8–30 days; 2 effective now or within 7 days.
- Consequence: 0 informational; 1 cost/process/listing impact; 2 shipment block, legal breach, account restriction, major duty, or sanctions exposure.
- Evidence: 0 unconfirmed; 1 official summary or incomplete text; 2 direct primary text with dates and scope.

## Level

- High: 8–10, or a verified shipment/legal/account-stoppage event with clear user exposure.
- Medium: 5–7.
- Low: 2–4.
- Watch: 0–1 or insufficient confirmation.

Never raise an item above `watch` when evidence is 0. Explain any override in `rationale`.

For marketplace rules, business exposure can be 2 only when the platform and seller market are established and the supplied account, operating model, product/category, fulfillment mode, payment product, or feature/plan is clearly affected. A platform name alone is exposure 1 at most.

For login-only notices, evidence can be 2 when the original notice is available and its date, account/market scope, obligation, and effective/enforcement timing are captured. If the notice cannot be opened, a third-party description or search snippet remains evidence 0 even when it appears credible.

## Action standard

Write one concise action that includes:

- owner or function, such as sales, customs, compliance, product, finance, or marketplace operations;
- object, such as affected orders, ASINs, suppliers, HS codes, or declarations;
- action verb;
- deadline or time horizon;
- evidence or decision needed to close the action.

Avoid generic actions such as “pay attention” or “continue monitoring.”

For platform events, also identify the seller market and affected objects, and record completion evidence. Prefer separate structured `action_items` for different owners instead of combining marketplace operations, finance, logistics, and compliance into one vague sentence.
