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

## Action standard

Write one concise action that includes:

- owner or function, such as sales, customs, compliance, product, finance, or marketplace operations;
- object, such as affected orders, ASINs, suppliers, HS codes, or declarations;
- action verb;
- deadline or time horizon;
- evidence or decision needed to close the action.

Avoid generic actions such as “pay attention” or “continue monitoring.”

