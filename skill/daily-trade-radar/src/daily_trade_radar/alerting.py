"""Build deduplicated alerts from verified, risk-scored radar events."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.request import Request, urlopen

from .snapshots.filesystem import atomic_write_text
from .validation import validate


LEVEL_RANK = {"watch": 0, "low": 1, "medium": 2, "high": 3}


def _signature(event: dict[str, Any]) -> str:
    identity = {key: event.get(key) for key in (
        "id", "source_url", "published_at", "published_date", "effective_at",
        "effective_date", "deadline_at", "deadline", "summary",
    )}
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_alert_batch(
    report: dict[str, Any], *, min_level: str = "high", require_applicability_match: bool = False,
    seen_signatures: set[str] | None = None,
) -> dict[str, Any]:
    errors = validate(report)
    if errors:
        raise ValueError("alert input failed validation: " + "; ".join(errors[:5]))
    if min_level not in LEVEL_RANK:
        raise ValueError(f"invalid alert level: {min_level}")
    seen = seen_signatures or set()
    alerts: list[dict[str, Any]] = []
    suppressed: list[dict[str, str]] = []
    for event in report.get("events", []):
        event_id = str(event.get("id", ""))
        reason = None
        if event.get("status") == "unconfirmed" or event.get("score_breakdown", {}).get("evidence", 0) < 1:
            reason = "not_verified"
        elif LEVEL_RANK.get(str(event.get("level")), -1) < LEVEL_RANK[min_level]:
            reason = "below_level"
        elif require_applicability_match and event.get("applicability", {}).get("status") != "matched":
            reason = "not_applicable"
        signature = _signature(event)
        if reason is None and signature in seen:
            reason = "already_alerted"
        if reason:
            suppressed.append({"event_id": event_id, "reason": reason})
            continue
        alerts.append({
            "event_id": event_id, "signature": signature, "level": event["level"],
            "status": event["status"], "title": event["title"], "impact": event["impact"],
            "action": event["action"], "source_title": event["source_title"],
            "source_url": event["source_url"], "applicability": event.get("applicability"),
        })
    return {
        "schema_version": "1.0", "report_date": report.get("report_date"),
        "cutoff": report.get("cutoff"), "min_level": min_level,
        "require_applicability_match": require_applicability_match,
        "alert_count": len(alerts), "alerts": alerts, "suppressed": suppressed,
    }


def load_state(path: Path | None) -> set[str]:
    if path is None or not path.exists():
        return set()
    value = json.loads(path.read_text(encoding="utf-8"))
    signatures = value.get("signatures") if isinstance(value, dict) else None
    if not isinstance(signatures, list) or any(not isinstance(item, str) for item in signatures):
        raise ValueError("alert state must contain a signatures array")
    return set(signatures)


def save_state(path: Path, signatures: set[str]) -> None:
    atomic_write_text(path, json.dumps({"schema_version": "1.0", "signatures": sorted(signatures)}, indent=2) + "\n")


def deliver_webhook(
    batch: dict[str, Any], webhook: str, *, timeout: float = 15,
    opener: Callable[..., Any] = urlopen,
) -> int:
    if not webhook.startswith("https://"):
        raise ValueError("webhook must use https")
    body = json.dumps(batch, ensure_ascii=False).encode("utf-8")
    request = Request(webhook, data=body, headers={"Content-Type": "application/json", "User-Agent": "DailyTradeRadar/0.4"}, method="POST")
    with opener(request, timeout=timeout) as response:
        status = int(getattr(response, "status", response.getcode()))
    if not 200 <= status < 300:
        raise ValueError(f"webhook returned HTTP {status}")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--min-level", choices=tuple(LEVEL_RANK), default="high")
    parser.add_argument("--require-applicability-match", action="store_true")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--webhook")
    parser.add_argument("--send", action="store_true", help="explicitly deliver to --webhook")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        seen = load_state(args.state)
        batch = build_alert_batch(
            report, min_level=args.min_level,
            require_applicability_match=args.require_applicability_match,
            seen_signatures=seen,
        )
        delivered = False
        if args.send and batch["alert_count"]:
            if not args.webhook:
                raise ValueError("--send requires --webhook")
            deliver_webhook(batch, args.webhook)
            delivered = True
        if args.state and delivered:
            save_state(args.state, seen | {item["signature"] for item in batch["alerts"]})
        atomic_write_text(args.output, json.dumps(batch, ensure_ascii=False, indent=2) + "\n")
        print(f"WROTE: {args.output} ({batch['alert_count']} alert(s))")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
