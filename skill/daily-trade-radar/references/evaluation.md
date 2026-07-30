# Evaluation workflow

Use evaluation to measure a generated radar against labels reviewed independently from the
generation run. Do not relabel generated output as ground truth.

## Label set

Create one JSON object with:

- `dataset_version`: `1`;
- `dataset_name`: stable name for the benchmark;
- `review_status`: `draft` or `independently_reviewed`;
- `reviewed_by` and `reviewed_at`: required for `independently_reviewed`;
- `records`: the closed candidate universe, including positive and rejected events;
- `deduplication_cases`: expected historical matches and dispositions.

For every included event, record its stable ID, accepted direct primary-source URLs, publication,
effective and deadline dates, status, and reviewed risk level. A rejected candidate needs only its
ID and `should_include: false`.

## Run

Create a review-ready draft from one pre-deduplication report and its final report:

```text
daily-trade-radar evaluation-scaffold current.json deduplicated.json \
  --dataset-name radar-2026-07-30 --output 2026-07-30.labels.json
```

The scaffold copies provisional decisions only to reduce reviewer data entry. It always writes
`review_status: draft`, includes rejected candidates, and warns that the radar's own output is not
ground truth. Review direct sources before changing the status to `independently_reviewed`.

Evaluate the reviewed labels:

```text
daily-trade-radar evaluate report.json labels.json --output evaluation.json
```

Default release gates require at least 20 positive events, independently reviewed metadata,
precision and recall of 0.90, primary-source rate of 0.95, date accuracy of 0.98,
deduplication accuracy of 0.90, and zero unsupported sources.

Use relaxed thresholds only for synthetic or draft fixtures. A draft fixture is suitable for
testing the evaluator, not for making quality claims:

```text
daily-trade-radar evaluate examples/current.json examples/evaluation-labels.json \
  --allow-draft --minimum-positive-events 2 --min-deduplication-accuracy 0
```

Exit code `0` means the gate passed, `1` means invalid input or execution failure, and `3` means
the evaluation completed but one or more quality gates failed.

Aggregate a manifest of independently reviewed runs without allowing repeated event IDs from
different dates to overwrite one another:

```text
daily-trade-radar evaluate-history evaluation/drafts/manifest.json radar-runs \
  --output evaluation/history-evaluation.json
```

The manifest `files` array supplies label filenames. Each `YYYY-MM-DD[-N].labels.json` file maps
to `radar-runs/YYYY-MM-DD[-N]/deduplicated.json`. Aggregate metrics are micro-averaged across
runs, while error identifiers are prefixed with the run name for auditability.

## Grow the benchmark

Start with 50 independently reviewed candidates and include at least 20 positive events and 10
deduplication cases. Expand toward 100–200 candidates across policy, customs, sanctions,
compliance, logistics, and marketplace rules. Preserve rejected leads so precision is measurable.
Never tune on the final holdout set.
