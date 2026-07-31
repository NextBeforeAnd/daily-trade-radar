"""Source-health inventory, bounded public probes, and run postmortems."""

from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .acquisition.adapters.http import HttpAdapter
from .acquisition.manifest import AcquisitionManifest, build_platform_manifest
from .acquisition.models import AcquisitionReceipt, AcquisitionTask, stable_task_id, validate_receipt_for_task
from .acquisition.receipts import create_receipt
from .platforms import get_platform, load_registry
from .snapshots.filesystem import atomic_write_text


AUDIT_STATES = {
    "ok", "no_relevant_update", "partial", "blocked", "login_required", "timeout",
    "rate_limited", "schema_drift", "not_configured", "not_checked",
}
SEVERE_STATES = {"blocked", "login_required", "timeout", "rate_limited", "schema_drift"}


def _source_id(*values: str) -> str:
    payload = "\n".join(value.casefold() for value in values)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _fix_hint(state: str, task: AcquisitionTask | None = None) -> str:
    hints = {
        "ok": "No access fix required; continue substantive source review.",
        "no_relevant_update": "No access fix required; retain the checked URL and snapshot evidence.",
        "partial": "Complete route verification, candidate review, or the required public-page snapshot.",
        "blocked": "Retry through the in-app browser and record the observed access boundary.",
        "login_required": "Use an existing authorized read-only browser session; do not bypass authentication.",
        "timeout": "Retry with a bounded timeout or use the in-app browser; do not treat this as no update.",
        "rate_limited": "Retry later with bounded rate limiting; do not reuse the failed result as coverage.",
        "schema_drift": "Inspect the source response and update the parser or registered route before reuse.",
        "not_configured": "Add and verify an official route or preserve the declared coverage gap.",
        "not_checked": "Open the planned route and create a receipt before claiming coverage.",
    }
    hint = hints[state]
    if task is not None and task.requires_auth and state == "not_checked":
        return "Check this dashboard through an existing authorized read-only browser session."
    return hint


def _state_for_receipt(task: AcquisitionTask, receipt: AcquisitionReceipt) -> tuple[str, str]:
    error = (receipt.error_type or "").casefold()
    if "schema" in error or "parse" in error or "decode" in error:
        return "schema_drift", receipt.notes or "Source response no longer matched the expected structure."
    if receipt.http_status == 429 or "rate" in error or "429" in error:
        return "rate_limited", receipt.notes or "Source rate limit was reached."
    if "timeout" in error or "timedout" in error:
        return "timeout", receipt.notes or "Source did not respond inside the configured deadline."
    if receipt.result == "blocked":
        return "blocked", receipt.notes or "Access was blocked."
    if receipt.result == "login_required":
        return "login_required", receipt.notes or "Authentication gate was observed."
    if receipt.result == "not_applicable":
        return "partial", receipt.notes or "Configured route was not applicable and needs verification."
    if receipt.result == "candidate_found":
        return "partial", receipt.notes or "Candidate content still requires substantive review."
    if task.route_verification_required and not receipt.route_verified:
        return "partial", "The route opened but its market or official-entry verification is incomplete."
    if task.source_type in {"official_updates", "current_policy"} and receipt.snapshot is None:
        return "partial", "Public source was checked but the required snapshot is missing."
    if receipt.result == "no_relevant_update":
        return "no_relevant_update", receipt.notes or "Source was checked and no relevant update was found."
    return "ok", receipt.notes or "Source was checked successfully."


def _record_for_task(task: AcquisitionTask, receipt: AcquisitionReceipt | None) -> dict[str, Any]:
    if receipt is None:
        state, detail = "not_checked", "No acquisition receipt exists for this planned route."
        checked_at = None
        run_outcome = "skipped"
    else:
        state, detail = _state_for_receipt(task, receipt)
        checked_at = receipt.checked_at
        run_outcome = receipt.result
    return {
        "source_id": task.task_id,
        "platform": task.platform,
        "seller_market": task.seller_market,
        "program": task.program,
        "source_type": task.source_type,
        "url": task.url,
        "audit_state": state,
        "run_outcome": run_outcome,
        "checked_at": checked_at,
        "details": detail,
        "fix_hint": _fix_hint(state, task),
        "task_id": task.task_id,
    }


def _gap_record(gap: dict[str, str]) -> dict[str, Any]:
    source_id = _source_id(gap["platform"], gap["seller_market"], gap["program"], gap["source_type"], "gap")
    return {
        "source_id": source_id,
        "platform": gap["platform"],
        "seller_market": gap["seller_market"],
        "program": gap["program"],
        "source_type": gap["source_type"],
        "url": None,
        "audit_state": "not_configured",
        "run_outcome": "declared_gap",
        "checked_at": None,
        "details": gap["reason"],
        "fix_hint": _fix_hint("not_configured"),
        "task_id": None,
    }


def _report(records: list[dict[str, Any]], *, mode: str, generated_at: str) -> dict[str, Any]:
    records.sort(key=lambda item: (
        item["platform"].casefold(), item["seller_market"].casefold(),
        item["program"].casefold(), item["source_type"], item["url"] or "",
    ))
    counts = Counter(record["audit_state"] for record in records)
    if counts.keys() & SEVERE_STATES:
        overall = "degraded"
    elif any(state in counts for state in {"partial", "not_checked", "not_configured"}):
        overall = "incomplete"
    else:
        overall = "healthy"
    return {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "mode": mode,
        "overall_status": overall,
        "summary": {state: counts.get(state, 0) for state in sorted(AUDIT_STATES)},
        "sources": records,
    }


def derive_source_health(
    manifests: Iterable[AcquisitionManifest],
    receipts: Iterable[AcquisitionReceipt],
    *,
    generated_at: str | None = None,
    mode: str = "postmortem",
) -> dict[str, Any]:
    manifest_list = list(manifests)
    if not manifest_list:
        raise ValueError("at least one acquisition manifest is required")
    tasks: dict[str, AcquisitionTask] = {}
    gaps: dict[str, dict[str, str]] = {}
    for manifest in manifest_list:
        for task in manifest.tasks:
            existing = tasks.get(task.task_id)
            if existing is not None and existing != task:
                raise ValueError(f"conflicting manifest task identity: {task.task_id}")
            tasks[task.task_id] = task
        for gap in manifest.planning_gaps:
            key = _source_id(gap["platform"], gap["seller_market"], gap["program"], gap["source_type"], "gap")
            gaps[key] = gap
    latest: dict[str, AcquisitionReceipt] = {}
    for receipt in receipts:
        task = tasks.get(receipt.task_id)
        if task is None:
            raise ValueError(f"receipt task is absent from supplied manifests: {receipt.task_id}")
        validate_receipt_for_task(receipt, task)
        previous = latest.get(receipt.task_id)
        if previous is None or datetime.fromisoformat(receipt.checked_at) > datetime.fromisoformat(previous.checked_at):
            latest[receipt.task_id] = receipt
    records = [_record_for_task(task, latest.get(task_id)) for task_id, task in tasks.items()]
    records.extend(_gap_record(gap) for gap in gaps.values())
    timestamp = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return _report(records, mode=mode, generated_at=timestamp)


def inventory_source_health(
    platforms: Iterable[str] | None = None,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    registry = load_registry()
    selected = []
    if platforms:
        seen: set[str] = set()
        for name in platforms:
            config = get_platform(name)
            if config is None:
                raise ValueError(f"unregistered platform: {name}")
            if config.id not in seen:
                selected.append(config)
                seen.add(config.id)
    else:
        selected = [registry[key] for key in sorted(registry)]
    records: list[dict[str, Any]] = []
    for config in selected:
        seller_market = config.seller_markets[0]
        program = config.programs[0]
        for route in config.official_routes:
            task = AcquisitionTask(
                task_id=stable_task_id(
                    config.display_name, seller_market, program, str(route["source_type"]),
                    str(route["url"]), "2000-01-01T00:00:00+00:00",
                ),
                platform=config.display_name,
                seller_market=seller_market,
                program=program,
                source_type=str(route["source_type"]),
                url=str(route["url"]),
                window_start="2000-01-01T00:00:00+00:00",
                requires_auth=str(route["source_type"]) == "dashboard",
                route_verification_required=route.get("verification_status") != "verified" or bool(route.get("verify_before_use")),
                notes="Registry inventory only.",
            )
            # Inventory IDs are not acquisition task IDs, so render the record directly.
            records.append({
                "source_id": _source_id(config.display_name, str(route["source_type"]), str(route["url"])),
                "platform": config.display_name, "seller_market": seller_market, "program": program,
                "source_type": str(route["source_type"]), "url": str(route["url"]),
                "audit_state": "not_checked", "run_outcome": "inventory_only", "checked_at": None,
                "details": "Registered route is available but has not been probed in this command.",
                "fix_hint": _fix_hint("not_checked", task), "task_id": None,
            })
        for source_type, reason in config.source_profile["known_gaps"].items():
            records.append(_gap_record({
                "platform": config.display_name, "seller_market": seller_market, "program": program,
                "source_type": source_type, "reason": reason,
            }))
    timestamp = generated_at or datetime.now().astimezone().isoformat(timespec="seconds")
    return _report(records, mode="inventory", generated_at=timestamp)


def probe_source_health(
    platforms: Iterable[str] | None = None,
    *,
    checked_at: str | None = None,
    timeout: float = 10.0,
    workers: int = 4,
    opener=None,
) -> dict[str, Any]:
    if timeout <= 0 or workers < 1:
        raise ValueError("probe timeout and worker count must be positive")
    timestamp = checked_at or datetime.now().astimezone().isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("checked_at must include a UTC offset")
    registry = load_registry()
    if platforms:
        selected = []
        seen: set[str] = set()
        for name in platforms:
            config = get_platform(name)
            if config is None:
                raise ValueError(f"unregistered platform: {name}")
            if config.id not in seen:
                selected.append(config)
                seen.add(config.id)
    else:
        selected = [registry[key] for key in sorted(registry)]
    manifests = [
        build_platform_manifest(
            [config.display_name], config.seller_markets[0], config.programs[0],
            (parsed - timedelta(days=7)).isoformat(timespec="seconds"), timestamp, timestamp,
        )
        for config in selected
    ]
    tasks = [task for manifest in manifests for task in manifest.tasks if not task.requires_auth]
    receipts: list[AcquisitionReceipt] = []

    def run(task: AcquisitionTask) -> AcquisitionReceipt:
        arguments: dict[str, Any] = {"timeout": timeout, "max_attempts": 1}
        if opener is not None:
            arguments["opener"] = opener
        return HttpAdapter(**arguments).acquire(task, timestamp, refresh=True)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, task): task for task in tasks}
        for future in as_completed(futures):
            task = futures[future]
            try:
                receipts.append(future.result())
            except Exception as exc:  # isolate one probe so the remaining source audit still completes
                receipts.append(create_receipt(
                    task, timestamp, "blocked", "http",
                    f"Probe failed with {type(exc).__name__}.", error_type=type(exc).__name__,
                ))
    return derive_source_health(manifests, receipts, generated_at=timestamp, mode="probe")


def _load_json(path: Path) -> object:
    if path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f"{path}: JSON file exceeds the 10 MiB postmortem limit")
    return json.loads(path.read_text(encoding="utf-8"))


def load_postmortem(path: Path) -> tuple[list[AcquisitionManifest], list[AcquisitionReceipt]]:
    paths = [path] if path.is_file() else sorted(path.rglob("*.json")) if path.is_dir() else []
    if not paths:
        raise ValueError(f"postmortem path has no JSON files: {path}")
    manifests: list[AcquisitionManifest] = []
    receipts: list[AcquisitionReceipt] = []
    for item in paths:
        try:
            value = _load_json(item)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        if {"manifest_id", "created_at", "window_start", "cutoff", "tasks"} <= value.keys():
            manifests.append(AcquisitionManifest.from_dict(value))
        elif {"task_id", "requested_url", "result", "retrieval_method", "checked_at"} <= value.keys():
            receipts.append(AcquisitionReceipt.from_dict(value))
    if not manifests:
        raise ValueError(f"postmortem path contains no acquisition manifest: {path}")
    return manifests, receipts


def _render_text(report: dict[str, Any]) -> str:
    summary = ", ".join(f"{key}={value}" for key, value in report["summary"].items() if value)
    lines = [
        f"Daily Trade Radar source health: {report['overall_status']}",
        f"Mode: {report['mode']} | Generated: {report['generated_at']}",
        f"Summary: {summary or 'no sources'}",
    ]
    for source in report["sources"]:
        scope = f"{source['platform']} / {source['seller_market']} / {source['program']} / {source['source_type']}"
        lines.append(f"- [{source['audit_state'].upper()}] {scope}: {source['details']}")
        if source["audit_state"] != "ok":
            lines.append(f"  Fix: {source['fix_hint']}")
    return "\n".join(lines) + "\n"


def _read_manifest(path: Path) -> AcquisitionManifest:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return AcquisitionManifest.from_dict(value)


def _read_receipt(path: Path) -> AcquisitionReceipt:
    value = _load_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return AcquisitionReceipt.from_dict(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="run bounded public-route probes")
    mode.add_argument("--postmortem", type=Path, help="audit manifests and receipts under a run path")
    parser.add_argument("--platform", action="append", help="limit inventory or probes to a registered platform")
    parser.add_argument("--manifest", type=Path, action="append", default=[])
    parser.add_argument("--receipt", type=Path, action="append", default=[])
    parser.add_argument("--checked-at")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.postmortem:
            if args.manifest or args.receipt or args.platform:
                raise ValueError("--postmortem cannot be combined with --manifest, --receipt, or --platform")
            manifests, receipts = load_postmortem(args.postmortem)
            report = derive_source_health(manifests, receipts, generated_at=args.checked_at, mode="postmortem")
        elif args.manifest:
            if args.probe or args.platform:
                raise ValueError("--manifest cannot be combined with --probe or --platform")
            report = derive_source_health(
                [_read_manifest(path) for path in args.manifest],
                [_read_receipt(path) for path in args.receipt],
                generated_at=args.checked_at,
                mode="postmortem",
            )
        elif args.receipt:
            raise ValueError("--receipt requires at least one --manifest")
        elif args.probe:
            report = probe_source_health(
                args.platform, checked_at=args.checked_at, timeout=args.timeout, workers=args.workers,
            )
        else:
            report = inventory_source_health(args.platform, generated_at=args.checked_at)
        content = json.dumps(report, ensure_ascii=False, indent=2) + "\n" if args.json else _render_text(report)
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
