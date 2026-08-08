#!/usr/bin/env python3
"""Validate Daily Trade Radar event JSON."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from .platforms.registry import canonical_platform_id, get_platform, normalize_name, platforms_in_scope
from .scoring import LEVELS, SCORE_DIMENSIONS, level_for_score


ROOT_FIELDS = {
    "report_date": str,
    "timezone": str,
    "cutoff": str,
    "language": str,
    "scope": list,
    "coverage_gaps": list,
    "events": list,
}
OPTIONAL_ROOT_FIELDS = {
    "window_start": (str, type(None)),
    "coverage_ledger": list,
}
EVENT_FIELDS = {
    "id": str,
    "title": str,
    "status": str,
    "level": str,
    "score": int,
    "score_breakdown": dict,
    "jurisdiction": str,
    "authority": str,
    "published_date": (str, type(None)),
    "effective_date": (str, type(None)),
    "deadline": (str, type(None)),
    "products_or_channels": list,
    "summary": str,
    "impact": str,
    "action": str,
    "rationale": str,
    "source_title": str,
    "source_url": str,
    "retrieved_date": str,
}
OPTIONAL_EVENT_FIELDS = {
    "published_at": (str, type(None)),
    "effective_at": (str, type(None)),
    "deadline_at": (str, type(None)),
    "source_timezone": (str, type(None)),
    "level_override": (dict, type(None)),
    "hs_codes": list,
    "applicability": dict,
}
APPLICABILITY_FIELDS = {
    "organization": str,
    "status": str,
    "matched_items": list,
    "reason": str,
}
APPLICABILITY_STATUSES = {"matched", "needs_review", "no_match"}
APPLICABILITY_MATCH_FIELDS = {
    "sku": str,
    "name": str,
    "basis": list,
    "matched_hs_codes": list,
    "matched_terms": list,
}
APPLICABILITY_BASES = {"hs_prefix", "product_keyword"}
LEVEL_OVERRIDE_FIELDS = {
    "level": str,
    "reason": str,
}
STATUSES = {"new", "effective", "deadline", "ongoing", "unconfirmed"}
PLATFORM_POLICY_FIELDS = {
    "platform": str,
    "seller_market": str,
    "program": str,
    "policy_area": str,
    "change_type": str,
    "seller_scope": str,
    "previous_state": (str, type(None)),
    "new_state": str,
    "enforcement_consequence": str,
    "backend_verification_required": bool,
}
POLICY_AREAS = {
    "onboarding_kyc",
    "listing_product_compliance",
    "pricing_promotions",
    "fees_commissions",
    "fulfillment_logistics",
    "returns_refunds_aftersales",
    "payments_settlement_tax",
    "content_ads_affiliate",
    "data_privacy_security",
    "account_health_enforcement",
    "api_feature_deprecation",
    "other",
}
CHANGE_TYPES = {
    "new_rule",
    "rule_change",
    "enforcement_change",
    "fee_change",
    "feature_change",
    "deadline",
    "clarification",
}
ACTION_ITEM_FIELDS = {
    "owner": str,
    "action": str,
    "deadline": str,
    "completion_evidence": str,
}
COVERAGE_LEDGER_FIELDS = {
    "platform": str,
    "seller_market": str,
    "program": str,
    "lookback_start": str,
    "public_update_checked": bool,
    "current_policy_checked": bool,
    "dashboard_checked": bool,
    "access_result": str,
    "checked_at": str,
    "sources_checked": list,
    "verified_event_ids": list,
    "gaps": list,
}
ACCESS_RESULTS = {"public_checked", "login_required", "blocked", "checked_authenticated", "not_checked", "not_applicable"}
SOURCE_CHECK_FIELDS = {
    "source_type": str,
    "url": str,
    "result": str,
    "checked_at": str,
    "notes": str,
}
SOURCE_TYPES = {"official_updates", "current_policy", "dashboard", "discovery_lead"}
SOURCE_RESULTS = {
    "no_relevant_update",
    "candidate_found",
    "verified_event",
    "login_required",
    "blocked",
    "not_applicable",
}
ACQUISITION_RECEIPT_FIELDS = {
    "task_id": str,
    "retrieval_method": str,
    "attempts": int,
    "http_status": (int, type(None)),
    "content_hash": (str, type(None)),
    "content_ref": (str, type(None)),
    "error_type": (str, type(None)),
    "route_verified": bool,
}
RETRIEVAL_METHODS = {"browser_public", "browser_authenticated", "manual", "http", "rss", "atom", "sitemap"}
SNAPSHOT_FIELDS = {
    "snapshot_id": str,
    "captured_at": str,
    "content_hash": str,
    "previous_snapshot_id": (str, type(None)),
    "change_status": str,
    "diff_summary": str,
    "snapshot_path": str,
    "diff_path": (str, type(None)),
}
SNAPSHOT_OPTIONAL_FIELDS = {
    "storage_backend": str,
    "snapshot_ref": str,
    "diff_ref": (str, type(None)),
    "index_recovered": bool,
}
SNAPSHOT_GIT_FIELDS = {
    "git_commit": str,
    "git_tree": str,
}
SNAPSHOT_BACKENDS = {"filesystem", "sqlite", "git", "s3"}
SNAPSHOT_STATUSES = {"first_seen", "unchanged", "changed"}
SNAPSHOT_REQUIRED_RESULTS = {"no_relevant_update", "candidate_found", "verified_event"}


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("root must be a JSON object")
    return value


def valid_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def valid_datetime_offset(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    for key, expected in ROOT_FIELDS.items():
        if key not in data:
            errors.append(f"root: missing {key}")
        elif not isinstance(data[key], expected):
            errors.append(f"root.{key}: wrong type")
    for key, expected in OPTIONAL_ROOT_FIELDS.items():
        if key in data and not isinstance(data[key], expected):
            errors.append(f"root.{key}: wrong type")

    if isinstance(data.get("report_date"), str) and not valid_date(data["report_date"]):
        errors.append("root.report_date: use YYYY-MM-DD")
    for field in ("window_start", "cutoff"):
        value = data.get(field)
        if isinstance(value, str) and not valid_datetime_offset(value):
            errors.append(f"root.{field}: use ISO 8601 date-time with a UTC offset")

    coverage_ledger = data.get("coverage_ledger")
    ledger_platforms: set[str] = set()
    if isinstance(coverage_ledger, list):
        for ledger_index, entry in enumerate(coverage_ledger):
            ledger_label = f"coverage_ledger[{ledger_index}]"
            if not isinstance(entry, dict):
                errors.append(f"{ledger_label}: must be an object")
                continue
            for key, expected in COVERAGE_LEDGER_FIELDS.items():
                value = entry.get(key)
                if key not in entry:
                    errors.append(f"{ledger_label}: missing {key}")
                elif not isinstance(value, expected):
                    errors.append(f"{ledger_label}.{key}: wrong type")
                elif isinstance(value, str) and not value.strip():
                    errors.append(f"{ledger_label}.{key}: must not be blank")
            if entry.get("access_result") not in ACCESS_RESULTS:
                errors.append(f"{ledger_label}.access_result: invalid value")
            platform = entry.get("platform")
            if isinstance(platform, str):
                ledger_platforms.add(canonical_platform_id(platform) or normalize_name(platform))
            checked_at = entry.get("checked_at")
            lookback_start = entry.get("lookback_start")
            checked_dt = None
            lookback_dt = None
            if isinstance(checked_at, str) and not valid_datetime_offset(checked_at):
                errors.append(f"{ledger_label}.checked_at: use ISO 8601 date-time with a UTC offset")
            elif isinstance(checked_at, str):
                checked_dt = datetime.fromisoformat(checked_at)
            if isinstance(lookback_start, str) and not valid_datetime_offset(lookback_start):
                errors.append(f"{ledger_label}.lookback_start: use ISO 8601 date-time with a UTC offset")
            elif isinstance(lookback_start, str):
                lookback_dt = datetime.fromisoformat(lookback_start)
            if checked_dt is not None and lookback_dt is not None:
                if lookback_dt > checked_dt:
                    errors.append(f"{ledger_label}.lookback_start: must not be after checked_at")
                elif (checked_dt - lookback_dt).total_seconds() < 7 * 24 * 60 * 60:
                    errors.append(f"{ledger_label}.lookback_start: platform lookback must be at least 7 days")
            gaps = entry.get("gaps")
            if isinstance(gaps, list) and any(not isinstance(gap, str) or not gap.strip() for gap in gaps):
                errors.append(f"{ledger_label}.gaps: entries must be non-blank strings")
            verified_event_ids = entry.get("verified_event_ids")
            if isinstance(verified_event_ids, list) and any(
                not isinstance(event_id, str) or not event_id.strip() for event_id in verified_event_ids
            ):
                errors.append(f"{ledger_label}.verified_event_ids: entries must be non-blank strings")
            sources = entry.get("sources_checked")
            source_types: set[str] = set()
            source_results: set[str] = set()
            if isinstance(sources, list):
                if not sources:
                    errors.append(f"{ledger_label}.sources_checked: must be a non-empty array")
                for source_index, source in enumerate(sources):
                    source_label = f"{ledger_label}.sources_checked[{source_index}]"
                    if not isinstance(source, dict):
                        errors.append(f"{source_label}: must be an object")
                        continue
                    for key, expected in SOURCE_CHECK_FIELDS.items():
                        value = source.get(key)
                        if key not in source:
                            errors.append(f"{source_label}: missing {key}")
                        elif not isinstance(value, expected):
                            errors.append(f"{source_label}.{key}: wrong type")
                        elif isinstance(value, str) and not value.strip():
                            errors.append(f"{source_label}.{key}: must not be blank")
                    source_type = source.get("source_type")
                    if source_type not in SOURCE_TYPES:
                        errors.append(f"{source_label}.source_type: invalid value")
                    elif isinstance(source_type, str):
                        source_types.add(source_type)
                    result = source.get("result")
                    if result not in SOURCE_RESULTS:
                        errors.append(f"{source_label}.result: invalid value")
                    elif isinstance(result, str):
                        source_results.add(result)
                    source_checked_at = source.get("checked_at")
                    if isinstance(source_checked_at, str) and not valid_datetime_offset(source_checked_at):
                        errors.append(f"{source_label}.checked_at: use ISO 8601 date-time with a UTC offset")
                    source_url = source.get("url")
                    if isinstance(source_url, str):
                        parsed = urlparse(source_url)
                        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                            errors.append(f"{source_label}.url: use a direct http(s) URL")
                    acquisition_receipt = source.get("acquisition_receipt")
                    if acquisition_receipt is not None:
                        if not isinstance(acquisition_receipt, dict):
                            errors.append(f"{source_label}.acquisition_receipt: must be an object")
                        else:
                            for key, expected in ACQUISITION_RECEIPT_FIELDS.items():
                                value = acquisition_receipt.get(key)
                                if key not in acquisition_receipt:
                                    errors.append(f"{source_label}.acquisition_receipt: missing {key}")
                                elif not isinstance(value, expected):
                                    errors.append(f"{source_label}.acquisition_receipt.{key}: wrong type")
                            method = acquisition_receipt.get("retrieval_method")
                            if method not in RETRIEVAL_METHODS:
                                errors.append(f"{source_label}.acquisition_receipt.retrieval_method: invalid value")
                            attempts = acquisition_receipt.get("attempts")
                            if isinstance(attempts, bool):
                                errors.append(f"{source_label}.acquisition_receipt.attempts: wrong type")
                            elif isinstance(attempts, int) and attempts < 1:
                                errors.append(f"{source_label}.acquisition_receipt.attempts: must be at least 1")
                            task_id = acquisition_receipt.get("task_id")
                            if isinstance(task_id, str) and not re.fullmatch(r"[0-9a-f]{24}", task_id):
                                errors.append(
                                    f"{source_label}.acquisition_receipt.task_id: use a 24-character lowercase hexadecimal digest"
                                )
                            http_status = acquisition_receipt.get("http_status")
                            if isinstance(http_status, bool) or (
                                isinstance(http_status, int) and not 100 <= http_status <= 599
                            ):
                                errors.append(
                                    f"{source_label}.acquisition_receipt.http_status: use an integer from 100 to 599 or null"
                                )
                            content_hash = acquisition_receipt.get("content_hash")
                            if isinstance(content_hash, str) and not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                                errors.append(f"{source_label}.acquisition_receipt.content_hash: use a lowercase SHA-256 hex digest")
                            content_ref = acquisition_receipt.get("content_ref")
                            if isinstance(content_ref, str):
                                content_path = Path(content_ref)
                                if content_path.is_absolute() or ".." in content_path.parts or "\\" in content_ref:
                                    errors.append(
                                        f"{source_label}.acquisition_receipt.content_ref: use a portable relative POSIX path"
                                    )
                            if method == "browser_authenticated" and content_ref is not None:
                                errors.append(
                                    f"{source_label}.acquisition_receipt.content_ref: authenticated content must not be persisted"
                                )
                    snapshot = source.get("snapshot")
                    snapshot_required = (
                        source_type in {"official_updates", "current_policy"}
                        and result in SNAPSHOT_REQUIRED_RESULTS
                    )
                    if snapshot_required and not isinstance(snapshot, dict):
                        errors.append(f"{source_label}.snapshot: required for an opened public policy page")
                    if snapshot is not None:
                        if not isinstance(snapshot, dict):
                            errors.append(f"{source_label}.snapshot: must be an object")
                        else:
                            for key, expected in SNAPSHOT_FIELDS.items():
                                value = snapshot.get(key)
                                if key not in snapshot:
                                    errors.append(f"{source_label}.snapshot: missing {key}")
                                elif not isinstance(value, expected):
                                    errors.append(f"{source_label}.snapshot.{key}: wrong type")
                                elif isinstance(value, str) and not value.strip():
                                    errors.append(f"{source_label}.snapshot.{key}: must not be blank")
                            for key, expected in SNAPSHOT_OPTIONAL_FIELDS.items():
                                if key in snapshot and not isinstance(snapshot[key], expected):
                                    errors.append(f"{source_label}.snapshot.{key}: wrong type")
                            portable_fields = set(SNAPSHOT_OPTIONAL_FIELDS) & snapshot.keys()
                            if portable_fields and portable_fields != set(SNAPSHOT_OPTIONAL_FIELDS):
                                missing = set(SNAPSHOT_OPTIONAL_FIELDS) - portable_fields
                                errors.append(
                                    f"{source_label}.snapshot: portable storage metadata missing "
                                    f"{', '.join(sorted(missing))}"
                                )
                            git_fields = set(SNAPSHOT_GIT_FIELDS) & snapshot.keys()
                            backend = snapshot.get("storage_backend")
                            if isinstance(backend, str) and backend not in SNAPSHOT_BACKENDS:
                                errors.append(f"{source_label}.snapshot.storage_backend: invalid value")
                            if (git_fields and git_fields != set(SNAPSHOT_GIT_FIELDS)) or (
                                backend == "git" and git_fields != set(SNAPSHOT_GIT_FIELDS)
                            ):
                                missing = set(SNAPSHOT_GIT_FIELDS) - git_fields
                                errors.append(
                                    f"{source_label}.snapshot: Git provenance missing "
                                    f"{', '.join(sorted(missing))}"
                                )
                            if backend != "git" and git_fields:
                                errors.append(f"{source_label}.snapshot: Git provenance requires storage_backend git")
                            for key, expected in SNAPSHOT_GIT_FIELDS.items():
                                if key in snapshot and not isinstance(snapshot[key], expected):
                                    errors.append(f"{source_label}.snapshot.{key}: wrong type")
                                elif isinstance(snapshot.get(key), str) and not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", snapshot[key]):
                                    errors.append(f"{source_label}.snapshot.{key}: use a Git object ID")
                            snapshot_ref = snapshot.get("snapshot_ref")
                            diff_ref = snapshot.get("diff_ref")
                            for ref_name, ref_value in (("snapshot_ref", snapshot_ref), ("diff_ref", diff_ref)):
                                if isinstance(ref_value, str):
                                    ref_path = Path(ref_value)
                                    if ref_path.is_absolute() or ".." in ref_path.parts or "\\" in ref_value:
                                        errors.append(
                                            f"{source_label}.snapshot.{ref_name}: use a portable relative POSIX path"
                                        )
                            status = snapshot.get("change_status")
                            previous_id = snapshot.get("previous_snapshot_id")
                            if status not in SNAPSHOT_STATUSES:
                                errors.append(f"{source_label}.snapshot.change_status: invalid value")
                            if status == "first_seen" and previous_id is not None:
                                errors.append(f"{source_label}.snapshot.previous_snapshot_id: first_seen must not have a previous snapshot")
                            if status in {"unchanged", "changed"} and not isinstance(previous_id, str):
                                errors.append(f"{source_label}.snapshot.previous_snapshot_id: {status} requires a previous snapshot")
                            captured_at = snapshot.get("captured_at")
                            if isinstance(captured_at, str) and not valid_datetime_offset(captured_at):
                                errors.append(f"{source_label}.snapshot.captured_at: use ISO 8601 date-time with a UTC offset")
                            content_hash = snapshot.get("content_hash")
                            if isinstance(content_hash, str) and not re.fullmatch(r"[0-9a-f]{64}", content_hash):
                                errors.append(f"{source_label}.snapshot.content_hash: use a lowercase SHA-256 hex digest")
            check_requirements = {
                "public_update_checked": "official_updates",
                "current_policy_checked": "current_policy",
                "dashboard_checked": "dashboard",
            }
            for check_field, source_type in check_requirements.items():
                if entry.get(check_field) is True and source_type not in source_types:
                    errors.append(f"{ledger_label}.{check_field}: requires a {source_type} source entry")
            if entry.get("access_result") == "login_required":
                has_login_attempt = isinstance(sources, list) and any(
                    isinstance(source, dict)
                    and source.get("source_type") == "dashboard"
                    and source.get("result") == "login_required"
                    for source in sources
                )
                if not has_login_attempt:
                    errors.append(f"{ledger_label}.access_result: login_required requires a dashboard access attempt")
            if entry.get("access_result") == "blocked":
                has_blocked_attempt = isinstance(sources, list) and any(
                    isinstance(source, dict) and source.get("result") == "blocked"
                    for source in sources
                )
                if not has_blocked_attempt:
                    errors.append(f"{ledger_label}.access_result: blocked requires a blocked source attempt")

    for platform in platforms_in_scope(data.get("scope", [])):
        if platform.id not in ledger_platforms:
            errors.append(f"root.coverage_ledger: missing entry for platform named in scope: {platform.id}")

    seen_ids: set[str] = set()
    for index, event in enumerate(data.get("events", [])):
        label = f"events[{index}]"
        if not isinstance(event, dict):
            errors.append(f"{label}: must be an object")
            continue
        for key, expected in EVENT_FIELDS.items():
            if key not in event:
                errors.append(f"{label}: missing {key}")
            elif not isinstance(event[key], expected):
                errors.append(f"{label}.{key}: wrong type")
        for key, expected in OPTIONAL_EVENT_FIELDS.items():
            if key in event and not isinstance(event[key], expected):
                errors.append(f"{label}.{key}: wrong type")
        event_id = event.get("id")
        if isinstance(event_id, str):
            if not event_id.strip():
                errors.append(f"{label}.id: must not be blank")
            elif event_id in seen_ids:
                errors.append(f"{label}.id: duplicate {event_id}")
            seen_ids.add(event_id)
        if event.get("status") not in STATUSES:
            errors.append(f"{label}.status: invalid value")
        if event.get("level") not in LEVELS:
            errors.append(f"{label}.level: invalid value")
        score = event.get("score")
        if isinstance(score, bool):
            errors.append(f"{label}.score: wrong type")
        elif isinstance(score, int) and not 0 <= score <= 10:
            errors.append(f"{label}.score: must be 0..10")
        score_breakdown = event.get("score_breakdown")
        dimension_values: dict[str, int] = {}
        if isinstance(score_breakdown, dict):
            missing_dimensions = SCORE_DIMENSIONS - score_breakdown.keys()
            extra_dimensions = score_breakdown.keys() - SCORE_DIMENSIONS
            for dimension in sorted(missing_dimensions):
                errors.append(f"{label}.score_breakdown: missing {dimension}")
            for dimension in sorted(extra_dimensions):
                errors.append(f"{label}.score_breakdown: unexpected {dimension}")
            for dimension in sorted(SCORE_DIMENSIONS & score_breakdown.keys()):
                value = score_breakdown[dimension]
                if isinstance(value, bool) or not isinstance(value, int):
                    errors.append(f"{label}.score_breakdown.{dimension}: must be an integer 0..2")
                elif not 0 <= value <= 2:
                    errors.append(f"{label}.score_breakdown.{dimension}: must be 0..2")
                else:
                    dimension_values[dimension] = value
        if len(dimension_values) == len(SCORE_DIMENSIONS) and isinstance(score, int) and not isinstance(score, bool):
            calculated_score = sum(dimension_values.values())
            if score != calculated_score:
                errors.append(
                    f"{label}.score: must equal score_breakdown total {calculated_score}, got {score}"
                )

            expected_level = level_for_score(calculated_score)
            actual_level = event.get("level")
            override = event.get("level_override")
            if actual_level != expected_level:
                if not isinstance(override, dict):
                    errors.append(
                        f"{label}.level: score {calculated_score} requires {expected_level}; "
                        "supply level_override with a reason for an exception"
                    )
                else:
                    for key, expected in LEVEL_OVERRIDE_FIELDS.items():
                        value = override.get(key)
                        if key not in override:
                            errors.append(f"{label}.level_override: missing {key}")
                        elif not isinstance(value, expected):
                            errors.append(f"{label}.level_override.{key}: wrong type")
                        elif not value.strip():
                            errors.append(f"{label}.level_override.{key}: must not be blank")
                    unexpected_override = override.keys() - LEVEL_OVERRIDE_FIELDS.keys()
                    for key in sorted(unexpected_override):
                        errors.append(f"{label}.level_override: unexpected {key}")
                    if override.get("level") != actual_level:
                        errors.append(f"{label}.level_override.level: must match event level")
                    if override.get("level") not in LEVELS:
                        errors.append(f"{label}.level_override.level: invalid value")
            elif override is not None:
                errors.append(f"{label}.level_override: remove it when level already follows the score")

            if dimension_values.get("evidence") == 0 and actual_level != "watch":
                errors.append(f"{label}.level: evidence 0 requires watch and cannot be overridden")
        if event.get("status") == "unconfirmed" and event.get("level") != "watch":
            errors.append(f"{label}: unconfirmed events must use watch level")
        for field in ("published_date", "effective_date", "deadline", "retrieved_date"):
            value = event.get(field)
            if isinstance(value, str) and not valid_date(value):
                errors.append(f"{label}.{field}: use YYYY-MM-DD")
        for field in ("published_at", "effective_at", "deadline_at"):
            value = event.get(field)
            if isinstance(value, str) and not valid_datetime_offset(value):
                errors.append(f"{label}.{field}: use ISO 8601 date-time with a UTC offset")
        source_timezone = event.get("source_timezone")
        if isinstance(source_timezone, str) and not source_timezone.strip():
            errors.append(f"{label}.source_timezone: must not be blank")
        hs_codes = event.get("hs_codes")
        if isinstance(hs_codes, list):
            for hs_index, hs_code in enumerate(hs_codes):
                digits = re.sub(r"[.\s-]", "", hs_code) if isinstance(hs_code, str) else ""
                if not digits.isdigit() or not 4 <= len(digits) <= 10:
                    errors.append(f"{label}.hs_codes[{hs_index}]: expected 4-10 digits")
        applicability = event.get("applicability")
        if isinstance(applicability, dict):
            for key, expected in APPLICABILITY_FIELDS.items():
                if key not in applicability:
                    errors.append(f"{label}.applicability: missing {key}")
                elif not isinstance(applicability[key], expected):
                    errors.append(f"{label}.applicability.{key}: wrong type")
            if applicability.get("status") not in APPLICABILITY_STATUSES:
                errors.append(f"{label}.applicability.status: invalid value")
            for field in ("organization", "reason"):
                value = applicability.get(field)
                if isinstance(value, str) and not value.strip():
                    errors.append(f"{label}.applicability.{field}: must not be blank")
            matched_items = applicability.get("matched_items")
            if applicability.get("status") == "matched" and isinstance(matched_items, list) and not matched_items:
                errors.append(f"{label}.applicability.matched_items: matched status requires evidence")
            if applicability.get("status") in {"needs_review", "no_match"} and matched_items:
                errors.append(f"{label}.applicability.matched_items: non-matched status cannot contain matches")
            if isinstance(matched_items, list):
                for match_index, match in enumerate(matched_items):
                    match_label = f"{label}.applicability.matched_items[{match_index}]"
                    if not isinstance(match, dict):
                        errors.append(f"{match_label}: must be an object")
                        continue
                    unexpected = match.keys() - APPLICABILITY_MATCH_FIELDS.keys()
                    for key in sorted(unexpected):
                        errors.append(f"{match_label}: unexpected {key}")
                    for key, expected in APPLICABILITY_MATCH_FIELDS.items():
                        if key not in match:
                            errors.append(f"{match_label}: missing {key}")
                        elif not isinstance(match[key], expected):
                            errors.append(f"{match_label}.{key}: wrong type")
                    for field in ("sku", "name"):
                        value = match.get(field)
                        if isinstance(value, str) and not value.strip():
                            errors.append(f"{match_label}.{field}: must not be blank")
                    basis = match.get("basis")
                    if isinstance(basis, list):
                        if not basis or any(item not in APPLICABILITY_BASES for item in basis):
                            errors.append(f"{match_label}.basis: invalid or empty match basis")
                    for field in ("matched_hs_codes", "matched_terms"):
                        values = match.get(field)
                        if isinstance(values, list) and any(not isinstance(item, str) or not item.strip() for item in values):
                            errors.append(f"{match_label}.{field}: must contain nonblank strings")
        url = event.get("source_url")
        if isinstance(url, str):
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append(f"{label}.source_url: use a direct http(s) URL")
        if event.get("level") != "watch" and not event.get("source_title", "").strip():
            errors.append(f"{label}.source_title: required for main-table events")
        platform_policy = event.get("platform_policy")
        action_items = event.get("action_items")
        if (platform_policy is None) != (action_items is None):
            errors.append(f"{label}: platform_policy and action_items must be supplied together")
        if platform_policy is not None:
            if not isinstance(platform_policy, dict):
                errors.append(f"{label}.platform_policy: must be an object")
            else:
                for key, expected in PLATFORM_POLICY_FIELDS.items():
                    value = platform_policy.get(key)
                    if key not in platform_policy:
                        errors.append(f"{label}.platform_policy: missing {key}")
                    elif not isinstance(value, expected):
                        errors.append(f"{label}.platform_policy.{key}: wrong type")
                    elif isinstance(value, str) and not value.strip():
                        errors.append(f"{label}.platform_policy.{key}: must not be blank")
                if platform_policy.get("policy_area") not in POLICY_AREAS:
                    errors.append(f"{label}.platform_policy.policy_area: invalid value")
                if platform_policy.get("change_type") not in CHANGE_TYPES:
                    errors.append(f"{label}.platform_policy.change_type: invalid value")
                registered_platform = get_platform(platform_policy.get("platform"))
                registry_status = platform_policy.get("registry_status")
                verification_required = platform_policy.get("official_entry_verification_required")
                if registered_platform is None:
                    if registry_status != "custom":
                        errors.append(
                            f"{label}.platform_policy.registry_status: unregistered platforms must use custom"
                        )
                    if verification_required is not True:
                        errors.append(
                            f"{label}.platform_policy.official_entry_verification_required: "
                            "unregistered platforms must require official-entry verification"
                        )
                else:
                    if registry_status not in {None, "registered"}:
                        errors.append(f"{label}.platform_policy.registry_status: registered platform cannot use custom")
                    if verification_required not in {None, False}:
                        errors.append(
                            f"{label}.platform_policy.official_entry_verification_required: "
                            "registered platform must not require custom-entry verification"
                        )
                if dimension_values.get("business_exposure") == 2:
                    seller_market = str(platform_policy.get("seller_market", "")).strip().casefold()
                    program = str(platform_policy.get("program", "")).strip().casefold()
                    seller_scope = str(platform_policy.get("seller_scope", "")).strip().casefold()
                    products = event.get("products_or_channels")
                    has_exposure_dimension = (
                        program not in {"", "unknown"}
                        or seller_scope not in {"", "unknown"}
                        or isinstance(products, list) and any(str(item).strip() for item in products)
                    )
                    if seller_market in {"", "unknown"} or not has_exposure_dimension:
                        errors.append(
                            f"{label}.score_breakdown.business_exposure: 2 requires a known seller market "
                            "and an affected program, scope, product, or channel"
                        )
        if action_items is not None:
            if not isinstance(action_items, list) or not action_items:
                errors.append(f"{label}.action_items: must be a non-empty array")
            else:
                for action_index, item in enumerate(action_items):
                    action_label = f"{label}.action_items[{action_index}]"
                    if not isinstance(item, dict):
                        errors.append(f"{action_label}: must be an object")
                        continue
                    for key, expected in ACTION_ITEM_FIELDS.items():
                        value = item.get(key)
                        if key not in item:
                            errors.append(f"{action_label}: missing {key}")
                        elif not isinstance(value, expected):
                            errors.append(f"{action_label}.{key}: wrong type")
                        elif isinstance(value, str) and not value.strip():
                            errors.append(f"{action_label}.{key}: must not be blank")
    if isinstance(coverage_ledger, list):
        event_by_id = {
            event.get("id"): event
            for event in data.get("events", [])
            if isinstance(event, dict) and isinstance(event.get("id"), str)
        }
        for ledger_index, entry in enumerate(coverage_ledger):
            if not isinstance(entry, dict):
                continue
            ledger_label = f"coverage_ledger[{ledger_index}]"
            ledger_platform = entry.get("platform")
            for event_id in entry.get("verified_event_ids", []):
                if not isinstance(event_id, str):
                    continue
                event = event_by_id.get(event_id)
                if event is None:
                    errors.append(f"{ledger_label}.verified_event_ids: unknown event id {event_id}")
                    continue
                policy = event.get("platform_policy")
                if not isinstance(policy, dict):
                    errors.append(f"{ledger_label}.verified_event_ids: {event_id} is not a platform-policy event")
                elif isinstance(ledger_platform, str):
                    ledger_platform_id = canonical_platform_id(ledger_platform) or normalize_name(ledger_platform)
                    event_platform_id = canonical_platform_id(policy.get("platform")) or normalize_name(policy.get("platform"))
                    if event_platform_id != ledger_platform_id:
                        errors.append(f"{ledger_label}.verified_event_ids: {event_id} belongs to a different platform")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args(argv)
    try:
        data = load_json(args.input)
        errors = validate(data)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PASS: {len(data['events'])} events validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
