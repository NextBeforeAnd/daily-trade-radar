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
daily-trade-radar calibration-scaffold evaluation/drafts/manifest.json \
  --output evaluation/calibration-review-scaffold.json
daily-trade-radar calibration-scaffold evaluation/drafts/manifest.json \
  --existing evaluation/calibration-review-scaffold.json \
  --output evaluation/calibration-review-scaffold.next.json \
  --diff-output evaluation/calibration-review-scaffold.diff.json \
  --require-calibration-ready
daily-trade-radar calibrate reviewed-history.json --minimum-samples 20 --minimum-per-level 3 --output calibration-report.json
```

The scaffold command accepts the manifest used by historical evaluation. It includes only approved
positive events, deduplicates stable event IDs across runs, and performs conservative cross-ID semantic
clustering. It automatically merges only strongly corroborated pairs, using canonical official URLs,
publication or effective dates, authorities, regulatory identifiers, title similarity, and non-year
numeric anchors. Ambiguous pairs such as a reused rolling-announcement URL are withheld from threshold
fitting and emitted in `semantic_duplicate_review_queue`. Automatic aliases are disclosed in
`excluded_semantic_duplicates`; conflicting human levels across an alias cluster are disclosed in
`excluded_semantic_level_conflicts` and excluded. The scaffold also excludes stable IDs whose reviewed
level changed across runs. It carries over the independently reviewed level and sets all five score
dimensions to `null`. Generated report scores are intentionally excluded to avoid anchoring the human
review. Resolve conflicts and the semantic review queue, then complete every dimension before passing
the file to `calibrate`. The command refuses to overwrite an existing worksheet unless `--force` is
supplied, so incremental human scoring is not lost accidentally.

Use `--existing` after adding or changing historical label files. Each generated record carries a
normalized evidence snapshot and SHA-256 review fingerprint. The merge preserves valid complete or
partial human scores only when the independently reviewed level and evidence fingerprint still match.
It leaves new records unscored, resets changed records to blank dimensions, and emits each reset or
conflict in `incremental_merge.review_queue`. Existing-only records, including manually added watch
observations, remain in the worksheet with `record_origin: existing_only`. Legacy worksheets without a
fingerprint receive a one-time context-identity migration; later changes are fingerprint checked.

Write incremental output to a new path, inspect the audit counts, and replace the prior worksheet only
after review. `--force` only permits overwriting the output file; it does not bypass merge validation.
Threshold decisions and calibration reports remain separate artifacts and are never changed by this
command.

Every incremental worksheet embeds an `incremental_diff` object. Its category arrays identify each
preserved complete or partial score, new unscored event, changed/reset event, existing-score conflict,
and retained existing-only observation. `--diff-output` writes this object as a standalone JSON report;
the terminal prints the counts and actionable blocker IDs.

The nested `calibration_gate` is ready only when every retained record has a complete score breakdown
and both the incremental and semantic-duplicate review queues are empty. With
`--require-calibration-ready`, a blocked run still writes the worksheet and diff for review, then returns
exit code `3`. The `calibrate` command independently rejects any incremental worksheet whose gate is
missing, invalid, or blocked. This keeps review work recoverable while preventing premature threshold
fitting.

## One-command incremental update

```text
daily-trade-radar calibration-update evaluation/drafts/manifest.json \
  --existing evaluation/calibration-review-scaffold.json \
  --previous-calibration evaluation/calibration-report.json \
  --decision-record evaluation/calibration-readiness.json \
  --output-dir evaluation/updates/2026-07-31
```

`calibration-update` performs the scaffold, merge, diff gate, calibration, comparison, and threshold
control checks in one process. It writes into a new directory through a staged directory rename and
refuses to use an existing destination. The directory contains:

- `calibration-review-scaffold.json` and `calibration-diff.json` on every completed run;
- `calibration-report.json` only when the incremental gate is ready;
- `calibration-update.json` with status, portable artifact names, metric deltas, prior human decision,
  and the non-automatic threshold-control result.

Exit code `0` means calibration completed with a sufficient sample, `3` means human review is required,
and `4` means the merge is ready but the calibration sample is insufficient. Input or filesystem errors
return `1`; command-usage conflicts return `2`. A previous decision is carried forward only when the
decision-relevant sample counts, label distribution, accuracy, macro-F1, disagreement count,
recommendation status, and candidate metrics are unchanged. No status permits automatic threshold
modification.

## Promote an approved formal baseline

```text
daily-trade-radar calibration-promote evaluation/updates/2026-07-31 \
  --baseline-dir evaluation \
  --backup-dir evaluation/backups/promotion-2026-07-31 \
  --decision retain_current_thresholds \
  --reviewed-by "workspace owner" \
  --reason "Boundary evidence is still insufficient." \
  --promoted-at "2026-07-31T18:00:00+08:00"
```

Promotion requires a complete four-file update bundle with matching scaffold/diff gates, a sufficient
sample, and a calibration report identical to an independent recomputation. The command requires an
explicit reviewer, timezone-aware timestamp, reason, and one of three decisions:

- `retain_current_thresholds` promotes the reviewed sample and report without changing scoring rules;
- `defer` returns exit code `3`, creates no backup, and makes no baseline change;
- `accept_candidate_thresholds` succeeds only if the candidate already equals the tested runtime
  thresholds after a separate reviewed code change and a fresh `calibration-update` run.

Before replacing the three formal baseline files, the command locks the baseline and publishes a new
backup directory containing the exact originals and `promotion-manifest.json`. The manifest records
before/after hashes, candidate-bundle hashes, the human decision, and rollback instructions. Promoted
files are hash-verified after writing; an exception restores each original through atomic file
replacement from the backup and marks the manifest `rolled_back_after_error`. Existing backup
directories are never reused.

## Roll back one completed promotion

```text
daily-trade-radar calibration-rollback evaluation/backups/promotion-2026-07-31 \
  --baseline-dir evaluation \
  --pre-rollback-dir evaluation/backups/pre-rollback-2026-07-31 \
  --rolled-back-by "workspace owner" \
  --reason "Regression detected after promotion." \
  --rolled-back-at "2026-07-31T19:00:00+08:00"
```

Rollback accepts only a promotion manifest whose status is `complete`. Before changing the baseline, it
requires every live formal file to match the manifest's post-promotion hash and every original backup to
match its pre-promotion hash. This prevents rollback across later legitimate edits or a damaged backup.

The command then publishes a new pre-rollback snapshot containing the promoted baseline, the untouched
promotion manifest, and `rollback-manifest.json`. Under the promotion lock, it marks the operation in
progress, restores all three baseline files byte-for-byte, verifies their hashes, marks the promotion
`rolled_back`, and completes the rollback manifest. If any write or verification fails, it restores the
promoted state and original promotion manifest from the pre-rollback snapshot and records
`pre_rollback_state_restored_after_error`. A rolled-back promotion cannot be replayed.

The report records a dataset SHA-256 hash, label distribution, pairwise exact and distance-weighted reviewer agreement, tied-label exclusions, current-rule confusion matrix/accuracy/macro-F1, means for each score dimension by reviewed level, and the best monotonic candidate thresholds.

The default sample gate requires at least 20 consensus events and at least three events in every reviewed level. Below that gate, no candidate is emitted. A candidate never changes the scoring rules automatically. Review dataset representativeness, reviewer disagreement, operational outcomes, and the business cost of false negatives before changing a threshold.
