"""Build a focused re-research plan for one radar event."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from .deduplication import regulatory_identifiers
from .library import load_report, show_event
from .platforms import get_platform
from .snapshots.filesystem import atomic_write_text


def _identity(value: dict[str, Any]) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _event_from_report(path: Path, event_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    report = load_report(path)
    event = next((item for item in report["events"] if item.get("id") == event_id), None)
    if event is None:
        raise ValueError(f"event id not found in report: {event_id}")
    context = {
        "report_key": None,
        "report_date": report["report_date"],
        "cutoff": report["cutoff"],
        "source_path": str(path.resolve()),
        "event": event,
    }
    return event, {"event_id": event_id, "first_seen": report["report_date"], "last_seen": report["report_date"], "sighting_count": 1, "latest": context, "sightings": [context]}


def _primary_targets(event: dict[str, Any]) -> list[dict[str, str]]:
    targets = [{
        "source_type": "event_primary_source",
        "url": event["source_url"],
        "purpose": "Re-open the cited source and verify that the operative text, dates, and scope remain current.",
    }]
    policy = event.get("platform_policy") if isinstance(event.get("platform_policy"), dict) else {}
    config = get_platform(policy.get("platform"))
    if config is not None:
        for route in config.official_routes:
            target = {
                "source_type": str(route["source_type"]),
                "url": str(route["url"]),
                "purpose": "Check the registered platform-owned route for implementation changes and current applicability.",
            }
            if target["url"] not in {item["url"] for item in targets}:
                targets.append(target)
    return targets


def _queries(event: dict[str, Any]) -> list[str]:
    products = " ".join(str(item) for item in event.get("products_or_channels", []))
    base = " ".join(filter(None, (
        str(event.get("jurisdiction") or ""), str(event.get("authority") or ""),
        str(event.get("title") or ""), products,
    )))
    queries = [
        f"{base} official current consolidated text",
        f"{base} amendment corrigendum implementation guidance",
        f"{base} effective date deadline enforcement",
    ]
    for identifier in sorted(regulatory_identifiers(event)):
        queries.append(f'"{identifier}" amendment implementation official')
    policy = event.get("platform_policy") if isinstance(event.get("platform_policy"), dict) else {}
    if policy:
        queries.append(
            f"{policy.get('platform', '')} {policy.get('seller_market', '')} "
            f"{policy.get('program', '')} {policy.get('policy_area', '')} seller policy"
        )
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))


def build_drill_plan(
    event_id: str,
    *,
    report_path: Path | None = None,
    library_path: Path | None = None,
    created_at: str | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    if not isinstance(event_id, str) or not event_id.strip():
        raise ValueError("event_id must be a nonblank string")
    if report_path is None and library_path is None:
        raise ValueError("drill requires --report or --library")
    timestamp = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("created_at must include a UTC offset")
    if report_path is not None:
        event, history = _event_from_report(report_path, event_id)
        if library_path is not None and library_path.exists():
            try:
                history = show_event(library_path, event_id)
            except ValueError:
                pass
    else:
        assert library_path is not None
        history = show_event(library_path, event_id)
        event = history["latest"]["event"]
    evidence = event.get("score_breakdown", {}).get("evidence") if isinstance(event.get("score_breakdown"), dict) else None
    confirmation_mode = event.get("status") == "unconfirmed" or evidence == 0
    questions = [
        "What is the current operative text, and has it been amended, corrected, superseded, or withdrawn?",
        "What are the exact publication, effective, transition, expiry, and deadline timestamps and timezones?",
        "Which jurisdictions, products, HS codes, seller markets, programs, and business models are actually in scope?",
        "What filing, document, labeling, listing, fulfillment, payment, or account action is required?",
        "What enforcement consequence applies, and what official implementation guidance exists?",
        "What material facts changed since the earliest stored sighting?",
    ]
    policy = event.get("platform_policy") if isinstance(event.get("platform_policy"), dict) else {}
    if policy:
        questions.append("Does the platform-owned current policy or account notice confirm the same market and program scope?")
    history_summary = [
        {
            "report_date": sighting["report_date"],
            "cutoff": sighting["cutoff"],
            "source_path": sighting["source_path"],
            "status": sighting["event"].get("status"),
            "level": sighting["event"].get("level"),
            "published_date": sighting["event"].get("published_date"),
            "effective_date": sighting["event"].get("effective_date"),
            "deadline": sighting["event"].get("deadline"),
            "source_url": sighting["event"].get("source_url"),
            "summary": sighting["event"].get("summary"),
        }
        for sighting in history["sightings"]
    ]
    payload = {
        "schema_version": "1.0",
        "created_at": timestamp,
        "event_id": event_id,
        "mode": "confirmation" if confirmation_mode else "revalidation",
        "cache_policy": "force_refresh" if refresh else "normal_ttl_with_explicit_refresh_for_changed_sources",
        "baseline_event": event,
        "history": {
            "first_seen": history["first_seen"],
            "last_seen": history["last_seen"],
            "sighting_count": history["sighting_count"],
            "sightings": history_summary,
        },
        "research_questions": questions,
        "primary_targets": _primary_targets(event),
        "queries": _queries(event),
        "required_outputs": [
            "current_primary_source_snapshot",
            "material_change_comparison",
            "applicability_findings",
            "verified_dates_and_timezone",
            "owner_action_and_completion_evidence",
        ],
        "promotion_gate": {
            "eligible_before_research": False,
            "require_direct_primary_or_platform_owned_source": True,
            "require_scope_and_date_verification": True,
            "unconfirmed_must_remain_watch_until_gate_passes": True,
        },
        "evidence_boundary": "This drill plan schedules verification; it does not itself confirm or modify the event.",
    }
    return {"drill_id": _identity(payload), **payload}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("event_id")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--library", type=Path)
    parser.add_argument("--created-at")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = build_drill_plan(
            args.event_id, report_path=args.report, library_path=args.library,
            created_at=args.created_at, refresh=args.refresh,
        )
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            atomic_write_text(args.output, content)
        else:
            print(content, end="")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
