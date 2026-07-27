#!/usr/bin/env python3
"""Validate Daily Trade Radar event JSON using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


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
}
STATUSES = {"new", "effective", "deadline", "ongoing", "unconfirmed"}
LEVELS = {"high", "medium", "low", "watch"}
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
SNAPSHOT_STATUSES = {"first_seen", "unchanged", "changed"}
SNAPSHOT_REQUIRED_RESULTS = {"no_relevant_update", "candidate_found", "verified_event"}
MONITORED_PLATFORM_ALIASES = {
    "tiktok shop": {"tiktok shop"},
    "temu": {"temu"},
    "shopify": {"shopify"},
    "jumia": {"jumia"},
    "amazon": {"amazon"},
    "aliexpress": {"aliexpress", "速卖通"},
}


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
                ledger_platforms.add(platform.strip().casefold())
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

    scope_text = " ".join(item for item in data.get("scope", []) if isinstance(item, str)).casefold()
    for platform, aliases in MONITORED_PLATFORM_ALIASES.items():
        named_in_scope = any(alias in scope_text for alias in aliases)
        represented = platform in ledger_platforms or any(alias in ledger_platforms for alias in aliases)
        if named_in_scope and not represented:
            errors.append(f"root.coverage_ledger: missing entry for platform named in scope: {platform}")

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
        if isinstance(score, int) and not 0 <= score <= 10:
            errors.append(f"{label}.score: must be 0..10")
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
                elif isinstance(ledger_platform, str) and policy.get("platform", "").casefold() != ledger_platform.casefold():
                    errors.append(f"{ledger_label}.verified_event_ids: {event_id} belongs to a different platform")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
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
