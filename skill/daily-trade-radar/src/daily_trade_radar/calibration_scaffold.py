"""Build a leakage-resistant human scoring worksheet from reviewed labels."""

from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import sys

from .calibration import LEVEL_ORDER
from .deduplication import canonical_url, normalized, regulatory_identifiers
from .scoring import SCORE_DIMENSIONS
from .snapshots.filesystem import atomic_write_text


SEMANTIC_AUTO_TITLE_SIMILARITY = 0.44
SEMANTIC_REVIEW_TITLE_SIMILARITY = 0.30
NUMBER_PATTERN = re.compile(r"(?<!\d)\d+(?:st|nd|rd|th)?(?!\d)", flags=re.IGNORECASE)


def _run_name(label_filename: str) -> str:
    suffix = ".labels.json"
    if not label_filename.endswith(suffix):
        raise ValueError(f"manifest label file must end with {suffix}: {label_filename}")
    return label_filename[:-len(suffix)]


def _semantic_event(source: dict, context: dict) -> dict:
    accepted_urls = source.get("accepted_primary_source_urls")
    fallback_url = accepted_urls[0] if isinstance(accepted_urls, list) and accepted_urls else ""
    return {
        "id": source.get("event_id"),
        "title": context.get("title"),
        "authority": context.get("authority"),
        "jurisdiction": context.get("jurisdiction"),
        "source_title": context.get("source_title"),
        "source_url": context.get("source_url") or fallback_url,
        "published_date": source.get("published_date"),
        "effective_date": source.get("effective_date"),
        "deadline": source.get("deadline"),
    }


def _compact(value: object) -> str:
    return "".join(re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE))


def _title_similarity(left: dict, right: dict) -> float:
    left_title = _compact(left.get("title"))
    right_title = _compact(right.get("title"))
    if not left_title or not right_title:
        return 0.0
    return SequenceMatcher(None, left_title, right_title).ratio()


def _number_anchors(event: dict) -> set[str]:
    text = " ".join(str(event.get(field) or "") for field in ("title", "source_title"))
    anchors: set[str] = set()
    for match in NUMBER_PATTERN.finditer(text):
        raw = re.sub(r"(?:st|nd|rd|th)$", "", match.group(0).casefold())
        number = int(raw)
        if 1900 <= number <= 2100:
            continue
        anchors.add(str(number))
    return anchors


def _same_nonblank(left: dict, right: dict, field: str) -> bool:
    left_value = normalized(left.get(field))
    right_value = normalized(right.get(field))
    return bool(left_value and right_value and left_value == right_value)


def _authority_matches(left: dict, right: dict) -> bool:
    left_value = normalized(left.get("authority"))
    right_value = normalized(right.get("authority"))
    if not left_value or not right_value:
        return False
    return left_value == right_value or SequenceMatcher(None, left_value, right_value).ratio() >= 0.9


def _semantic_match(left: dict, right: dict) -> dict | None:
    """Classify a conservative cross-ID semantic match for calibration clustering."""
    left_url = canonical_url(left.get("source_url"))
    right_url = canonical_url(right.get("source_url"))
    same_url = bool(left_url and right_url and left_url == right_url)
    same_published = _same_nonblank(left, right, "published_date")
    same_effective = _same_nonblank(left, right, "effective_date")
    authority_match = _authority_matches(left, right)
    title_similarity = _title_similarity(left, right)
    shared_identifiers = sorted(regulatory_identifiers(left) & regulatory_identifiers(right))
    shared_anchors = sorted(_number_anchors(left) & _number_anchors(right))
    signals = {
        "same_canonical_url": same_url,
        "same_published_date": same_published,
        "same_effective_date": same_effective,
        "authority_match": authority_match,
        "title_similarity": round(title_similarity, 3),
        "shared_regulatory_identifiers": shared_identifiers,
        "shared_numeric_anchors": shared_anchors,
    }

    if authority_match and shared_identifiers:
        return {"decision": "automatic_duplicate", "confidence": 0.98, "signals": signals}
    if same_url and authority_match and same_published:
        return {"decision": "automatic_duplicate", "confidence": 0.97, "signals": signals}
    if same_url and authority_match and same_effective and shared_anchors and title_similarity >= 0.65:
        return {"decision": "automatic_duplicate", "confidence": 0.94, "signals": signals}
    if (
        authority_match
        and same_published
        and shared_anchors
        and title_similarity >= SEMANTIC_AUTO_TITLE_SIMILARITY
    ):
        return {
            "decision": "automatic_duplicate",
            "confidence": round(min(0.96, 0.70 + title_similarity / 2), 3),
            "signals": signals,
        }
    if same_url:
        return {"decision": "review_required", "confidence": 0.75, "signals": signals}
    if (
        authority_match
        and same_published
        and shared_anchors
        and title_similarity >= SEMANTIC_REVIEW_TITLE_SIMILARITY
    ):
        return {
            "decision": "review_required",
            "confidence": round(min(0.89, 0.55 + title_similarity / 2), 3),
            "signals": signals,
        }
    return None


def _semantic_clusters(candidates: list[dict]) -> tuple[list[list[dict]], list[dict]]:
    parent = list(range(len(candidates)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left_index: int, right_index: int) -> None:
        left_root = find(left_index)
        right_root = find(right_index)
        if left_root != right_root:
            parent[right_root] = left_root

    pair_matches: list[dict] = []
    for left_index, left in enumerate(candidates):
        for right_index in range(left_index + 1, len(candidates)):
            right = candidates[right_index]
            match = _semantic_match(left["semantic_event"], right["semantic_event"])
            if match is None:
                continue
            pair = {
                "event_ids": [left["event_id"], right["event_id"]],
                **match,
            }
            pair_matches.append(pair)
            if match["decision"] == "automatic_duplicate":
                union(left_index, right_index)

    grouped: dict[int, list[dict]] = {}
    for index, candidate in enumerate(candidates):
        grouped.setdefault(find(index), []).append(candidate)
    return list(grouped.values()), pair_matches


def _review_identity(record: dict, *, include_evidence: bool = True) -> dict:
    context = record.get("review_context")
    context = context if isinstance(context, dict) else {}
    evidence = record.get("review_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    identity = {
        "reviewed_level": record.get("reviewed_level"),
        "title": normalized(context.get("title")),
        "jurisdiction": normalized(context.get("jurisdiction")),
        "authority": normalized(context.get("authority")),
        "source_title": normalized(context.get("source_title")),
        "source_url": canonical_url(evidence.get("source_url") or context.get("source_url")),
    }
    if include_evidence:
        identity.update({
            "published_date": normalized(evidence.get("published_date")),
            "effective_date": normalized(evidence.get("effective_date")),
            "deadline": normalized(evidence.get("deadline")),
        })
    return identity


def _review_fingerprint(record: dict) -> str:
    rendered = json.dumps(
        _review_identity(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _score_state(record: dict) -> str:
    event_id = record.get("event_id")
    breakdown = record.get("score_breakdown")
    if not isinstance(breakdown, dict) or set(breakdown) != SCORE_DIMENSIONS:
        raise ValueError(f"existing record {event_id}: score_breakdown must contain all five dimensions")
    values = []
    for dimension in sorted(SCORE_DIMENSIONS):
        value = breakdown.get(dimension)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 2):
            raise ValueError(f"existing record {event_id}: {dimension} must be null or an integer from 0 to 2")
        values.append(value)
    non_null = [value for value in values if value is not None]
    score = record.get("score")
    if len(non_null) == len(values):
        calculated = sum(non_null)
        if score is not None and score != calculated:
            raise ValueError(
                f"existing record {event_id}: score must equal score_breakdown total {calculated}"
            )
        return "complete"
    if score is not None:
        raise ValueError(f"existing record {event_id}: score requires a complete score_breakdown")
    return "partial" if non_null else "blank"


def _record_identifiers(record: dict) -> set[str]:
    identifiers = {record.get("event_id")}
    aliases = record.get("semantic_aliases")
    if isinstance(aliases, list):
        identifiers.update(item for item in aliases if isinstance(item, str) and item.strip())
    return {item for item in identifiers if isinstance(item, str) and item.strip()}


def _merge_runs(left: object, right: object) -> list[str]:
    merged: list[str] = []
    for value in (left, right):
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, str) and item not in merged:
                merged.append(item)
    return merged


def _merge_audit_entries(fresh: list, existing: object, key) -> list:
    result = list(fresh)
    seen = {key(item) for item in result if isinstance(item, dict)}
    if not isinstance(existing, list):
        return result
    for item in existing:
        if not isinstance(item, dict):
            continue
        identity = key(item)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(item)
    return result


def build_incremental_diff_report(scaffold: dict) -> dict:
    """Return an actionable, machine-readable report for one incremental merge."""
    audit = scaffold.get("incremental_merge")
    if not isinstance(audit, dict):
        raise ValueError("incremental diff requires an incremental_merge object")
    records = scaffold.get("records")
    if not isinstance(records, list):
        raise ValueError("incremental diff requires a records array")

    categories: dict[str, list[dict]] = {
        "preserved_complete": [],
        "preserved_partial": [],
        "new_unscored": [],
        "reset_changed": [],
        "score_conflicts": [],
        "retained_existing_only": [],
    }
    status_categories = {
        "new_unscored": "new_unscored",
        "evidence_changed_requires_review": "reset_changed",
        "reviewed_level_changed_requires_review": "reset_changed",
        "existing_score_conflict_requires_review": "score_conflicts",
        "retained_existing_only": "retained_existing_only",
    }
    incomplete_ids: list[str] = []
    semantic_alias_ids: list[str] = []
    review_details = {
        item.get("event_id"): item
        for item in audit.get("review_queue", [])
        if isinstance(item, dict) and isinstance(item.get("event_id"), str)
    }
    for record in records:
        if not isinstance(record, dict):
            continue
        event_id = record.get("event_id")
        if not isinstance(event_id, str):
            continue
        state = _score_state(record)
        status = record.get("merge_status")
        detail = {
            "event_id": event_id,
            "merge_status": status,
            "reviewed_level": record.get("reviewed_level"),
            "source_runs": record.get("source_runs", []),
        }
        if event_id in review_details:
            detail["review_reason"] = review_details[event_id].get("reason")
        category = status_categories.get(status)
        if category is None and status in {
            "preserved_complete",
            "preserved_partial",
            "preserved_blank",
            "preserved_legacy_score",
            "preserved_via_semantic_alias",
        }:
            category = "preserved_complete" if state == "complete" else "preserved_partial"
        if category:
            categories[category].append(detail)
        if state != "complete":
            incomplete_ids.append(event_id)
        if status == "preserved_via_semantic_alias":
            semantic_alias_ids.append(event_id)

    semantic_queue = scaffold.get("semantic_duplicate_review_queue")
    semantic_queue = semantic_queue if isinstance(semantic_queue, list) else []
    blockers: list[dict] = []
    for blocker_type, category in (
        ("new_events_require_scoring", "new_unscored"),
        ("changed_events_require_rescoring", "reset_changed"),
        ("existing_score_conflicts_require_review", "score_conflicts"),
    ):
        event_ids = [item["event_id"] for item in categories[category]]
        if event_ids:
            blockers.append({"type": blocker_type, "event_ids": event_ids})
    remaining_incomplete = sorted(set(incomplete_ids) - {
        event_id
        for category in ("new_unscored", "reset_changed", "score_conflicts")
        for event_id in (item["event_id"] for item in categories[category])
    })
    if remaining_incomplete:
        blockers.append({
            "type": "incomplete_score_breakdowns",
            "event_ids": remaining_incomplete,
        })
    if semantic_queue:
        blockers.append({
            "type": "semantic_duplicate_review_pending",
            "event_id_groups": [
                item.get("event_ids", []) for item in semantic_queue if isinstance(item, dict)
            ],
        })

    ready = not blockers
    return {
        "incremental_diff_version": 1,
        "summary": {
            category: len(items) for category, items in categories.items()
        } | {
            "semantic_alias_match_count": len(semantic_alias_ids),
            "pending_semantic_duplicate_review_count": len(semantic_queue),
        },
        "categories": categories,
        "semantic_alias_match_event_ids": semantic_alias_ids,
        "calibration_gate": {
            "ready": ready,
            "decision": "calibration_allowed" if ready else "human_review_required",
            "blocking_record_count": len(set(incomplete_ids)),
            "blockers": blockers,
        },
    }


def format_incremental_diff_summary(report: dict) -> str:
    """Render a compact terminal summary without hiding actionable event IDs."""
    summary = report["summary"]
    gate = report["calibration_gate"]
    lines = [
        "INCREMENTAL DIFF: " + ("READY" if gate["ready"] else "REVIEW REQUIRED"),
        (
            f"preserved={summary['preserved_complete']} complete/"
            f"{summary['preserved_partial']} partial"
            f" | new={summary['new_unscored']}"
            f" | reset={summary['reset_changed']}"
            f" | conflicts={summary['score_conflicts']}"
            f" | retained={summary['retained_existing_only']}"
        ),
    ]
    for blocker in gate["blockers"]:
        identifiers = blocker.get("event_ids") or blocker.get("event_id_groups") or []
        lines.append(f"- {blocker['type']}: {json.dumps(identifiers, ensure_ascii=False)}")
    return "\n".join(lines)


def merge_existing_scaffold(fresh: dict, existing: dict) -> dict:
    """Merge a fresh scaffold with prior human work without silently reusing changed evidence."""
    if not isinstance(existing, dict):
        raise ValueError("existing calibration scaffold root must be an object")
    existing_records = existing.get("records")
    if not isinstance(existing_records, list):
        raise ValueError("existing calibration scaffold records must be an array")

    existing_by_identifier: dict[str, set[int]] = {}
    score_states: dict[int, str] = {}
    for index, record in enumerate(existing_records):
        if not isinstance(record, dict):
            raise ValueError(f"existing records[{index}] must be an object")
        event_id = record.get("event_id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError(f"existing records[{index}].event_id must be nonblank")
        score_states[index] = _score_state(record)
        for identifier in _record_identifiers(record):
            existing_by_identifier.setdefault(identifier, set()).add(index)

    preserved_indices: set[int] = set()
    merged_records: list[dict] = []
    merge_review_queue: list[dict] = []
    counts = {
        "preserved_complete_count": 0,
        "preserved_partial_count": 0,
        "new_unscored_count": 0,
        "reset_changed_count": 0,
        "retained_existing_only_count": 0,
        "semantic_alias_match_count": 0,
        "conflict_count": 0,
    }

    for fresh_record in fresh.get("records", []):
        identifiers = _record_identifiers(fresh_record)
        matching_indices: set[int] = set()
        for identifier in identifiers:
            matching_indices.update(existing_by_identifier.get(identifier, set()))
        record = dict(fresh_record)
        record["review_fingerprint"] = _review_fingerprint(record)
        if not matching_indices:
            record["merge_status"] = "new_unscored"
            counts["new_unscored_count"] += 1
            merged_records.append(record)
            continue

        candidates = [existing_records[index] for index in sorted(matching_indices)]
        signatures = {
            json.dumps({
                "reviewed_level": item.get("reviewed_level"),
                "score_breakdown": item.get("score_breakdown"),
                "score": item.get("score"),
            }, sort_keys=True)
            for item in candidates
        }
        if len(signatures) != 1:
            preserved_indices.update(matching_indices)
            record["merge_status"] = "existing_score_conflict_requires_review"
            counts["conflict_count"] += 1
            merge_review_queue.append({
                "event_id": record["event_id"],
                "reason": "multiple_existing_scores_for_semantic_cluster",
                "existing_event_ids": [item.get("event_id") for item in candidates],
            })
            merged_records.append(record)
            continue

        existing_index = next(
            (
                index
                for index in sorted(matching_indices)
                if existing_records[index].get("event_id") == record.get("event_id")
            ),
            sorted(matching_indices)[0],
        )
        prior = existing_records[existing_index]
        preserved_indices.update(matching_indices)
        matched_via_alias = prior.get("event_id") != record.get("event_id")
        if prior.get("reviewed_level") != record.get("reviewed_level"):
            record["merge_status"] = "reviewed_level_changed_requires_review"
            counts["reset_changed_count"] += 1
            merge_review_queue.append({
                "event_id": record["event_id"],
                "reason": "reviewed_level_changed",
                "previous_level": prior.get("reviewed_level"),
                "current_level": record.get("reviewed_level"),
            })
            merged_records.append(record)
            continue

        prior_fingerprint = prior.get("review_fingerprint")
        if isinstance(prior_fingerprint, str) and prior_fingerprint:
            evidence_unchanged = prior_fingerprint == record["review_fingerprint"]
            migration = False
        else:
            evidence_unchanged = (
                _review_identity(prior, include_evidence=False)
                == _review_identity(record, include_evidence=False)
            )
            migration = evidence_unchanged
        if not evidence_unchanged:
            record["merge_status"] = "evidence_changed_requires_review"
            counts["reset_changed_count"] += 1
            merge_review_queue.append({
                "event_id": record["event_id"],
                "reason": "review_evidence_fingerprint_changed",
                "previous_event_id": prior.get("event_id"),
                "previous_fingerprint": prior_fingerprint,
                "current_fingerprint": record["review_fingerprint"],
            })
            merged_records.append(record)
            continue

        if matched_via_alias:
            counts["semantic_alias_match_count"] += 1

        record["reviewer"] = prior.get("reviewer", record.get("reviewer"))
        record["score_breakdown"] = dict(prior["score_breakdown"])
        if prior.get("score") is not None:
            record["score"] = prior["score"]
        record["source_runs"] = _merge_runs(record.get("source_runs"), prior.get("source_runs"))
        state = score_states[existing_index]
        if state == "complete":
            counts["preserved_complete_count"] += 1
        elif state == "partial":
            counts["preserved_partial_count"] += 1
        record["merge_status"] = (
            "preserved_via_semantic_alias"
            if matched_via_alias
            else "preserved_legacy_score" if migration else f"preserved_{state}"
        )
        merged_records.append(record)

    for index, prior in enumerate(existing_records):
        if index in preserved_indices:
            continue
        retained = dict(prior)
        retained.setdefault("record_origin", "existing_only")
        retained["merge_status"] = "retained_existing_only"
        retained.setdefault("review_fingerprint", _review_fingerprint(retained))
        merged_records.append(retained)
        counts["retained_existing_only_count"] += 1

    fresh["records"] = merged_records
    fresh["calibration_scaffold_version"] = 2
    fresh["incremental_merge"] = {
        "mode": "preserve_human_scores_fail_closed",
        **counts,
        "review_queue": merge_review_queue,
    }
    fresh["excluded_level_conflicts"] = _merge_audit_entries(
        fresh.get("excluded_level_conflicts", []),
        existing.get("excluded_level_conflicts"),
        lambda item: item.get("event_id"),
    )
    fresh["excluded_semantic_duplicates"] = _merge_audit_entries(
        fresh.get("excluded_semantic_duplicates", []),
        existing.get("excluded_semantic_duplicates"),
        lambda item: (item.get("event_id"), item.get("canonical_event_id")),
    )
    fresh["excluded_semantic_level_conflicts"] = _merge_audit_entries(
        fresh.get("excluded_semantic_level_conflicts", []),
        existing.get("excluded_semantic_level_conflicts"),
        lambda item: tuple(item.get("event_ids", [])),
    )
    fresh["semantic_duplicate_review_queue"] = _merge_audit_entries(
        fresh.get("semantic_duplicate_review_queue", []),
        existing.get("semantic_duplicate_review_queue"),
        lambda item: tuple(item.get("event_ids", [])),
    )

    completed = 0
    level_counts = {level: 0 for level in LEVEL_ORDER}
    for record in merged_records:
        state = _score_state(record)
        if state == "complete":
            completed += 1
        level = record.get("reviewed_level")
        if level in level_counts:
            level_counts[level] += 1
    retained_observations = sum(
        max(1, len(record.get("source_runs", [])))
        for record in merged_records
        if record.get("merge_status") == "retained_existing_only"
    )
    sample = fresh["sample"]
    sample["source_observation_count"] += retained_observations
    sample["unique_event_count"] += counts["retained_existing_only_count"]
    sample["record_count"] = len(merged_records)
    sample["completed_score_breakdown_count"] = completed
    sample["pending_score_breakdown_count"] = len(merged_records) - completed
    sample["reviewed_level_distribution"] = level_counts
    sample["excluded_level_conflict_count"] = len(fresh["excluded_level_conflicts"])
    sample["excluded_semantic_duplicate_count"] = len(fresh["excluded_semantic_duplicates"])
    sample["excluded_semantic_level_conflict_count"] = len(
        fresh["excluded_semantic_level_conflicts"]
    )
    sample["pending_semantic_duplicate_review_count"] = len(
        fresh["semantic_duplicate_review_queue"]
    )
    sample["pending_semantic_duplicate_record_count"] = len({
        event_id
        for item in fresh["semantic_duplicate_review_queue"]
        for event_id in item.get("event_ids", [])
        if isinstance(event_id, str)
    })
    if existing.get("sample", {}).get("independent_watch_observation_count") is not None:
        sample["independent_watch_observation_count"] = existing["sample"][
            "independent_watch_observation_count"
        ]

    pending = sample["pending_score_breakdown_count"] or merge_review_queue
    if pending:
        fresh["review_status"] = "score_breakdown_in_progress"
    elif existing.get("review_status") in {"score_breakdown_complete", "calibration_review_complete"}:
        fresh["review_status"] = existing["review_status"]
    else:
        fresh["review_status"] = "score_breakdown_complete"
    fresh["incremental_diff"] = build_incremental_diff_report(fresh)
    return fresh


def scaffold_calibration(manifest: dict, labels_directory: Path) -> dict:
    """Return a blank five-dimension worksheet for independently reviewed positives."""
    files = manifest.get("files")
    if not isinstance(files, list) or not files or any(not isinstance(item, str) for item in files):
        raise ValueError("manifest.files must be a non-empty string array")
    if len(files) != len(set(files)):
        raise ValueError("manifest.files must not contain duplicates")

    observations: dict[str, list[dict]] = {}
    for label_filename in files:
        run = _run_name(label_filename)
        data = json.loads((labels_directory / label_filename).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{run}: label root must be an object")
        if data.get("review_status") != "independently_reviewed":
            raise ValueError(f"{run}: labels must be independently_reviewed")
        reviewer = data.get("reviewed_by")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError(f"{run}: reviewed_by must be a nonblank string")
        source_records = data.get("records")
        if not isinstance(source_records, list):
            raise ValueError(f"{run}: records must be an array")
        for index, source in enumerate(source_records):
            if not isinstance(source, dict):
                raise ValueError(f"{run}: records[{index}] must be an object")
            if not source.get("should_include"):
                continue
            source_event_id = source.get("event_id")
            level = source.get("level")
            if not isinstance(source_event_id, str) or not source_event_id.strip():
                raise ValueError(f"{run}: included records[{index}].event_id must be nonblank")
            if level not in LEVEL_ORDER:
                raise ValueError(f"{run}: included record {source_event_id} has invalid level")
            context = source.get("review_context")
            normalized_context = context if isinstance(context, dict) else {}
            observations.setdefault(source_event_id, []).append({
                "reviewer": reviewer,
                "reviewed_level": level,
                "review_context": normalized_context,
                "semantic_event": _semantic_event(source, normalized_context),
                "source_run": run,
            })

    eligible: list[dict] = []
    conflicts: list[dict] = []
    for event_id, event_observations in observations.items():
        levels = {item["reviewed_level"] for item in event_observations}
        if len(levels) != 1:
            conflicts.append({
                "event_id": event_id,
                "reason": "reviewed_level_changed_across_runs",
                "observations": [
                    {"source_run": item["source_run"], "reviewed_level": item["reviewed_level"]}
                    for item in event_observations
                ],
            })
            continue
        selected = event_observations[-1]
        eligible.append({
            "event_id": event_id,
            "observations": event_observations,
            "selected": selected,
            "semantic_event": selected["semantic_event"],
        })

    clusters, pair_matches = _semantic_clusters(eligible)
    automatic_pairs = {
        frozenset(pair["event_ids"]): pair
        for pair in pair_matches
        if pair["decision"] == "automatic_duplicate"
    }
    review_pairs = [pair for pair in pair_matches if pair["decision"] == "review_required"]
    auto_root_by_event: dict[str, str] = {}
    for cluster in clusters:
        canonical_id = cluster[0]["event_id"]
        for item in cluster:
            auto_root_by_event[item["event_id"]] = canonical_id
    review_queue: list[dict] = []
    pending_review_roots: set[str] = set()
    seen_review_roots: set[frozenset[str]] = set()
    for pair in review_pairs:
        left_root = auto_root_by_event[pair["event_ids"][0]]
        right_root = auto_root_by_event[pair["event_ids"][1]]
        root_pair = frozenset((left_root, right_root))
        if len(root_pair) < 2 or root_pair in seen_review_roots:
            continue
        seen_review_roots.add(root_pair)
        pending_review_roots.update(root_pair)
        review_queue.append({
            "event_ids": sorted(root_pair),
            "reason": "semantic_duplicate_requires_review",
            "confidence": pair["confidence"],
            "signals": pair["signals"],
        })

    records: list[dict] = []
    semantic_duplicates: list[dict] = []
    semantic_level_conflicts: list[dict] = []
    level_counts = {level: 0 for level in LEVEL_ORDER}
    for cluster in clusters:
        canonical = cluster[0]
        canonical_id = canonical["event_id"]
        if canonical_id in pending_review_roots:
            continue
        cluster_levels = {item["selected"]["reviewed_level"] for item in cluster}
        if len(cluster_levels) != 1:
            semantic_level_conflicts.append({
                "canonical_event_id": canonical_id,
                "event_ids": [item["event_id"] for item in cluster],
                "reason": "reviewed_level_changed_across_semantic_duplicates",
                "reviewed_levels": sorted(cluster_levels),
            })
            continue
        selected = canonical["selected"]
        level = selected["reviewed_level"]
        level_counts[level] += 1
        merged_runs = [
            observation["source_run"]
            for item in cluster
            for observation in item["observations"]
        ]
        record = {
            "event_id": canonical_id,
            "reviewer": selected["reviewer"],
            "reviewed_level": level,
            "score_breakdown": {dimension: None for dimension in sorted(SCORE_DIMENSIONS)},
            "review_context": selected["review_context"],
            "review_evidence": {
                key: value
                for key, value in selected["semantic_event"].items()
                if key != "id"
            },
            "source_runs": merged_runs,
        }
        aliases = [item["event_id"] for item in cluster[1:]]
        if aliases:
            record["semantic_aliases"] = aliases
        record["review_fingerprint"] = _review_fingerprint(record)
        records.append(record)
        for duplicate in cluster[1:]:
            pair = automatic_pairs.get(frozenset((canonical_id, duplicate["event_id"])))
            semantic_duplicates.append({
                "event_id": duplicate["event_id"],
                "canonical_event_id": canonical_id,
                "reason": "high_confidence_semantic_duplicate",
                "confidence": pair["confidence"] if pair else None,
                "signals": pair["signals"] if pair else {"transitive_cluster_match": True},
                "source_runs": [item["source_run"] for item in duplicate["observations"]],
            })

    return {
        "calibration_scaffold_version": 2,
        "review_status": "score_breakdown_pending",
        "generated_scores_excluded": True,
        "instructions": (
            "Resolve every excluded level conflict and every semantic duplicate review item, then review "
            "the cited evidence independently and replace every null score dimension with an integer from "
            "0 to 2. Do not consult the generated report score. Remove review_context, source_runs, and "
            "semantic_aliases if a minimal calibrate input is desired."
        ),
        "sample": {
            "source_observation_count": sum(len(items) for items in observations.values()),
            "unique_event_count": len(observations),
            "record_count": len(records),
            "excluded_level_conflict_count": len(conflicts),
            "excluded_semantic_duplicate_count": len(semantic_duplicates),
            "excluded_semantic_level_conflict_count": len(semantic_level_conflicts),
            "pending_semantic_duplicate_review_count": len(review_queue),
            "pending_semantic_duplicate_record_count": len(pending_review_roots),
            "reviewed_level_distribution": level_counts,
        },
        "excluded_level_conflicts": conflicts,
        "excluded_semantic_duplicates": semantic_duplicates,
        "excluded_semantic_level_conflicts": semantic_level_conflicts,
        "semantic_duplicate_review_queue": review_queue,
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Manifest containing reviewed label filenames")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--existing",
        type=Path,
        help="Existing reviewed worksheet whose valid human scores should be merged fail-closed",
    )
    parser.add_argument("--diff-output", type=Path, help="Write the incremental diff as JSON")
    parser.add_argument(
        "--require-calibration-ready",
        action="store_true",
        help="Return exit code 3 when the incremental diff still requires human review",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite an existing worksheet")
    args = parser.parse_args(argv)
    if (args.diff_output or args.require_calibration_ready) and not args.existing:
        print("ERROR: --diff-output and --require-calibration-ready require --existing", file=sys.stderr)
        return 2
    if args.output and args.diff_output and args.output.resolve() == args.diff_output.resolve():
        print("ERROR: --output and --diff-output must use different paths", file=sys.stderr)
        return 2
    if args.output and args.output.exists() and not args.force:
        print(f"ERROR: output already exists; use --force to replace it: {args.output}", file=sys.stderr)
        return 1
    if args.diff_output and args.diff_output.exists() and not args.force:
        print(
            f"ERROR: diff output already exists; use --force to replace it: {args.diff_output}",
            file=sys.stderr,
        )
        return 1
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest root must be an object")
        result = scaffold_calibration(manifest, args.manifest.parent)
        if args.existing:
            existing = json.loads(args.existing.read_text(encoding="utf-8"))
            result = merge_existing_scaffold(result, existing)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        atomic_write_text(args.output, rendered)
        message = f"WROTE: {args.output} | records={result['sample']['record_count']}"
        if "incremental_merge" in result:
            audit = result["incremental_merge"]
            message += (
                f" | preserved={audit['preserved_complete_count']}"
                f" | new={audit['new_unscored_count']}"
                f" | reset={audit['reset_changed_count']}"
                f" | retained={audit['retained_existing_only_count']}"
            )
        print(message)
    else:
        print(rendered, end="")
    if args.existing:
        diff_report = result["incremental_diff"]
        if args.diff_output:
            atomic_write_text(
                args.diff_output,
                json.dumps(diff_report, ensure_ascii=False, indent=2) + "\n",
            )
            print(f"WROTE DIFF: {args.diff_output}")
        print(format_incremental_diff_summary(diff_report))
        if args.require_calibration_ready and not diff_report["calibration_gate"]["ready"]:
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
