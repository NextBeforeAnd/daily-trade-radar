#!/usr/bin/env python3
"""Compare current radar events with a previous JSON report."""

from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from pathlib import Path


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


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise ValueError(f"{path}: expected an object with an events array")
    return data


def normalized(value: object) -> str:
    text = str(value or "").casefold()
    return " ".join(re.findall(r"[\w]+", text, flags=re.UNICODE))


def signature(event: dict) -> str:
    parts = [
        event.get("jurisdiction"),
        event.get("authority"),
        event.get("title"),
        " ".join(event.get("products_or_channels", [])),
    ]
    return normalized(" ".join(str(part or "") for part in parts))


def similarity(left: dict, right: dict) -> float:
    if left.get("id") and left.get("id") == right.get("id"):
        return 1.0
    if left.get("source_url") and left.get("source_url") == right.get("source_url"):
        return 0.99
    return SequenceMatcher(None, signature(left), signature(right)).ratio()


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
        if normalized(current.get(field)) != normalized(previous.get(field)):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=Path)
    parser.add_argument("--previous", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=0.82)
    args = parser.parse_args()

    current = load(args.current)
    previous = load(args.previous)
    kept: list[dict] = []
    matches: list[dict] = []

    for event in current["events"]:
        candidates = [(similarity(event, old), old) for old in previous["events"]]
        score, old = max(candidates, default=(0.0, {}), key=lambda pair: pair[0])
        if score < args.threshold:
            kept.append(event)
            continue
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
        "matches": matches,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(current, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    removed = sum(item["disposition"] == "duplicate_removed" for item in matches)
    material = sum(item["disposition"] == "material_update" for item in matches)
    operational = sum(item["disposition"] == "operational_refresh" for item in matches)
    print(
        f"WROTE: {args.output} ({removed} duplicates removed, "
        f"{material} material updates, {operational} operational refreshes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
