# Historical scoring calibration

Use calibration to test the deterministic risk bands against independent human review. Do not use an event's existing generated `level` as its review label; that would only reproduce the rule being tested.

## Input

Supply a UTF-8 JSON object with a non-empty `records` array. Each review requires:

- `event_id`: stable event identifier;
- `reviewer`: human reviewer identifier or pseudonym;
- `reviewed_level`: `watch`, `low`, `medium`, or `high`, assigned independently after reviewing the evidence and business exposure;
- `score_breakdown`: the same five integer dimensions, each 0–2;
- optional `score`: when present, it must equal the breakdown total.

Multiple reviewers may label the same event, but they must evaluate the same score breakdown. A tied level vote is disclosed and excluded from threshold fitting. Duplicate event/reviewer pairs fail validation.

```json
{
  "records": [
    {
      "event_id": "eu-rule-2026",
      "reviewer": "reviewer-a",
      "reviewed_level": "high",
      "score_breakdown": {
        "regulatory_force": 2,
        "business_exposure": 2,
        "urgency": 2,
        "consequence": 1,
        "evidence": 1
      },
      "score": 8
    }
  ]
}
```

## Run

```text
daily-trade-radar calibrate reviewed-history.json --minimum-samples 20 --minimum-per-level 3 --output calibration-report.json
```

The report records a dataset SHA-256 hash, label distribution, pairwise exact and distance-weighted reviewer agreement, tied-label exclusions, current-rule confusion matrix/accuracy/macro-F1, means for each score dimension by reviewed level, and the best monotonic candidate thresholds.

The default sample gate requires at least 20 consensus events and at least three events in every reviewed level. Below that gate, no candidate is emitted. A candidate never changes the scoring rules automatically. Review dataset representativeness, reviewer disagreement, operational outcomes, and the business cost of false negatives before changing a threshold.
