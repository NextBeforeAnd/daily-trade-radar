#!/usr/bin/env python3
"""Match and compare current radar events with a previous JSON report."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


MATERIAL_FIELDS = (
    "jurisdiction",
    "authority",
    "published_date",
    "effective_date",
    "deadline",
    "published_at",
    "effective_at",
    "deadline_at",
    "source_timezone",
    "source_url",
)
PLATFORM_MATERIAL_FIELDS = (
    "platform",
    "seller_market",
    "program",
    "policy_area",
    "change_type",
    "seller_scope",
    "previous_state",
    "new_state",
    "enforcement_consequence",
)
FACT_PATTERN = re.compile(
    r"\d{4}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?"
    r"|\b\d{6,10}\b"
    r"|\d+(?:[.,]\d+)?\s*(?:%|％|percent|percentage points?|个百分点|欧元|美元|元|days?|天|日|个月|months?|years?|年)"
    r"|[一二三四五六七八九十百千万]+(?:欧元|美元|元|天|日|个月|年)",
    flags=re.IGNORECASE,
)
OBLIGATION_TERMS = {
    "禁止",
    "不得",
    "必须",
    "应当",
    "要求",
    "允许",
    "豁免",
    "暂停",
    "恢复",
    "prohibit",
    "prohibited",
    "must",
    "required",
    "requirement",
    "may not",
    "allowed",
    "exempt",
    "exemption",
    "cancelled",
    "suspended",
    "resumed",
}
TRACKING_QUERY_KEYS = {"from", "source", "ref", "ref_", "spm", "scm"}
UNKNOWN_SCOPE_VALUES = {"", "unknown", "global", "not stated", "n/a", "none"}
SCOPE_ALIASES = {
    "us": "united states",
    "usa": "united states",
    "u s": "united states",
    "united states of america": "united states",
    "eu": "european union",
    "e u": "european union",
    "prc": "china",
    "cn": "china",
    "uk": "united kingdom",
    "u k": "united kingdom",
}
MATCH_WEIGHTS = {
    "title": 0.30,
    "authority": 0.12,
    "jurisdiction": 0.10,
    "products_or_channels": 0.12,
    "source_url": 0.14,
    "regulatory_identifiers": 0.12,
    "platform_scope": 0.10,
}
IDENTIFIER_CONFLICT_SCORE_CEILING = 0.79
IDENTIFIER_PATTERN = re.compile(
    r"\b(?:celex|docket|document|notice|regulation|directive|decision|rule)"
    r"\s*(?:no\.?|number|id|:)?\s*(?=[a-z0-9./()_-]*\d)[a-z0-9][a-z0-9./()_-]{2,}\b"
    r"|(?:公告|令|通知)\s*(?:第)?[0-9]{2,4}(?:\s*年|[-/])?[0-9]*\s*号?",
    flags=re.IGNORECASE,
)


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError(f"{path}: expected an object with an events array")
    return data


def normalized(value: object) -> str:
    text = str(value or "").casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def canonical_scope(value: object) -> str:
    scope = normalized(value)
    return SCOPE_ALIASES.get(scope, scope)


def known_scope(value: object) -> str | None:
    scope = canonical_scope(value)
    return None if scope in UNKNOWN_SCOPE_VALUES else scope


def platform_policy(event: dict) -> dict:
    value = event.get("platform_policy")
    return value if isinstance(value, dict) else {}


def scope_conflicts(left: dict, right: dict) -> list[str]:
    conflicts: list[str] = []
    pairs = [
        ("jurisdiction", left.get("jurisdiction"), right.get("jurisdiction")),
        ("platform", platform_policy(left).get("platform"), platform_policy(right).get("platform")),
        ("seller_market", platform_policy(left).get("seller_market"), platform_policy(right).get("seller_market")),
    ]
    for field, left_value, right_value in pairs:
        left_scope = known_scope(left_value)
        right_scope = known_scope(right_value)
        if left_scope and right_scope and left_scope != right_scope:
            conflicts.append(field)
    return conflicts


def canonical_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return normalized(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return normalized(text)
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        lowered = key.casefold()
        if lowered.startswith("utm_") or lowered in TRACKING_QUERY_KEYS:
            continue
        query.append((key, item))
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), path, urlencode(sorted(query)), ""))


def text_similarity(left: object, right: object) -> float | None:
    left_text = normalized(left)
    right_text = normalized(right)
    if not left_text or not right_text:
        return None
    return SequenceMatcher(None, left_text, right_text).ratio()


def set_similarity(left: set[str], right: set[str]) -> float | None:
    if not left and not right:
        return None
    return len(left & right) / len(left | right)


def regulatory_identifiers(event: dict) -> set[str]:
    text = " ".join(str(event.get(field) or "") for field in ("title", "summary", "source_title"))
    return {normalized(match.group(0)) for match in IDENTIFIER_PATTERN.finditer(text)}


def platform_scope_similarity(left: dict, right: dict) -> float | None:
    left_policy = platform_policy(left)
    right_policy = platform_policy(right)
    comparisons: list[float] = []
    for field in ("platform", "seller_market", "program"):
        left_scope = known_scope(left_policy.get(field))
        right_scope = known_scope(right_policy.get(field))
        if left_scope and right_scope:
            comparisons.append(1.0 if left_scope == right_scope else 0.0)
    if not comparisons:
        return None
    return sum(comparisons) / len(comparisons)


def weighted_similarity(left: dict, right: dict) -> tuple[float, str, dict[str, float]]:
    if scope_conflicts(left, right):
        return 0.0, "scope_conflict", {}
    if left.get("id") and left.get("id") == right.get("id"):
        return 1.0, "exact_id", {"stable_id": 1.0}

    left_products = normalized_list(left.get("products_or_channels"))
    right_products = normalized_list(right.get("products_or_channels"))
    left_url = canonical_url(left.get("source_url"))
    right_url = canonical_url(right.get("source_url"))
    left_identifiers = regulatory_identifiers(left)
    right_identifiers = regulatory_identifiers(right)
    components: dict[str, float | None] = {
        "title": text_similarity(left.get("title"), right.get("title")),
        "authority": text_similarity(left.get("authority"), right.get("authority")),
        "jurisdiction": (
            1.0
            if known_scope(left.get("jurisdiction")) == known_scope(right.get("jurisdiction"))
            and known_scope(left.get("jurisdiction")) is not None
            else None
        ),
        "products_or_channels": set_similarity(left_products, right_products),
        "source_url": 1.0 if left_url and right_url and left_url == right_url else (0.0 if left_url and right_url else None),
        "regulatory_identifiers": set_similarity(left_identifiers, right_identifiers),
        "platform_scope": platform_scope_similarity(left, right),
    }
    available = {key: value for key, value in components.items() if value is not None}
    weight_total = sum(MATCH_WEIGHTS[key] for key in available)
    if not weight_total:
        return 0.0, "weighted_fields", {}
    score = sum(MATCH_WEIGHTS[key] * value for key, value in available.items()) / weight_total
    if left_identifiers and right_identifiers and not left_identifiers.intersection(right_identifiers):
        score = min(score, IDENTIFIER_CONFLICT_SCORE_CEILING)
    return score, "weighted_fields", {key: round(value, 3) for key, value in available.items()}


def confidence_for(score: float, threshold: float) -> str:
    if score >= 0.95:
        return "high"
    if score >= threshold:
        return "medium"
    return "low"


def normalized_list(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {normalized(item) for item in value if normalized(item)}


def factual_signals(value: object) -> tuple[tuple[str, ...], tuple[str, ...]]:
    text = str(value or "").casefold()
    facts = tuple(sorted(match.group(0).replace(" ", "") for match in FACT_PATTERN.finditer(text)))
    obligations = tuple(sorted(term for term in OBLIGATION_TERMS if term in text))
    return facts, obligations


def classify_change(
    current: dict,
    previous: dict,
    current_report_date: str | None = None,
    previous_report_date: str | None = None,
) -> tuple[str, list[str]]:
    """Classify a matched event without treating editorial rewrites as policy changes."""
    material_reasons: list[str] = []
    for field in MATERIAL_FIELDS:
        current_value = canonical_url(current.get(field)) if field == "source_url" else normalized(current.get(field))
        previous_value = canonical_url(previous.get(field)) if field == "source_url" else normalized(previous.get(field))
        if current_value != previous_value:
            material_reasons.append(field)

    if normalized_list(current.get("products_or_channels")) != normalized_list(previous.get("products_or_channels")):
        material_reasons.append("products_or_channels")

    current_policy = current.get("platform_policy")
    previous_policy = previous.get("platform_policy")
    if isinstance(current_policy, dict) and isinstance(previous_policy, dict):
        for field in PLATFORM_MATERIAL_FIELDS:
            if normalized(current_policy.get(field)) != normalized(previous_policy.get(field)):
                material_reasons.append(f"platform_policy.{field}")

    if factual_signals(current.get("summary")) != factual_signals(previous.get("summary")):
        material_reasons.append("summary_facts_or_obligation")

    if material_reasons:
        return "material_update", material_reasons

    current_status = current.get("status")
    previous_status = previous.get("status")
    operational_reasons: list[str] = []
    if current_status in {"effective", "deadline"} and current_status != previous_status:
        operational_reasons.append(f"status:{previous_status}->{current_status}")
    if current_report_date and current_report_date != previous_report_date:
        if current.get("effective_date") == current_report_date:
            operational_reasons.append("effective_date_reached")
        if current.get("deadline") == current_report_date:
            operational_reasons.append("deadline_reached")
    if operational_reasons:
        return "operational_refresh", operational_reasons

    return "duplicate_removed", []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.82)
    parser.add_argument("--review-threshold", type=float, default=0.65)
    args = parser.parse_args(argv)
    if not 0 <= args.review_threshold <= args.threshold <= 1:
        parser.error("require 0 <= review-threshold <= threshold <= 1")

    current = load(args.current)
    previous = load(args.previous)
    outcomes: dict[int, tuple[int, float, str, dict[str, float]]] = {}
    matches: list[dict] = []
    candidates: list[tuple[float, bool, int, int, str, dict[str, float]]] = []
    for current_index, event in enumerate(current["events"]):
        for previous_index, old in enumerate(previous["events"]):
            score, method, components = weighted_similarity(event, old)
            if score >= args.review_threshold:
                candidates.append((score, method == "exact_id", current_index, previous_index, method, components))
    candidates.sort(key=lambda item: (item[1], item[0]), reverse=True)

    used_current: set[int] = set()
    used_previous: set[int] = set()
    for score, _exact, current_index, previous_index, method, components in candidates:
        if current_index in used_current or previous_index in used_previous:
            continue
        outcomes[current_index] = (previous_index, score, method, components)
        used_current.add(current_index)
        used_previous.add(previous_index)

    kept: list[dict] = []
    for current_index, event in enumerate(current["events"]):
        outcome = outcomes.get(current_index)
        if outcome is None:
            kept.append(event)
            continue
        previous_index, score, method, components = outcome
        old = previous["events"][previous_index]
        review_required = score < args.threshold and method != "exact_id"
        if review_required:
            disposition = "review_required"
            reasons = ["low_confidence_match"]
        else:
            disposition, reasons = classify_change(
                event,
                old,
                current.get("report_date"),
                previous.get("report_date"),
            )
        matches.append({
            "current_id": event.get("id"),
            "previous_id": old.get("id"),
            "similarity": round(score, 3),
            "match_method": method,
            "match_confidence": confidence_for(score, args.threshold),
            "match_components": components,
            "review_required": review_required,
            "disposition": disposition,
            "change_reasons": reasons,
        })
        if disposition != "duplicate_removed":
            copy = dict(event)
            copy["deduplication_review"] = disposition
            copy["matched_previous_id"] = old.get("id")
            copy["deduplication_reasons"] = reasons
            kept.append(copy)

    current["events"] = kept
    current["deduplication"] = {
        "previous_report": str(args.previous),
        "threshold": args.threshold,
        "review_threshold": args.review_threshold,
        "matching_strategy": "one_to_one_weighted_v2",
        "matches": matches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    removed = sum(item["disposition"] == "duplicate_removed" for item in matches)
    material = sum(item["disposition"] == "material_update" for item in matches)
    operational = sum(item["disposition"] == "operational_refresh" for item in matches)
    review = sum(item["disposition"] == "review_required" for item in matches)
    print(
        f"WROTE: {args.output} ({removed} duplicates removed, "
        f"{material} material updates, {operational} operational refreshes, "
        f"{review} retained for review)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
