"""Convert acquisition receipts into draft platform coverage-ledger rows."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Iterable

from .manifest import AcquisitionManifest
from .models import AcquisitionReceipt, AcquisitionTask, validate_receipt_for_task


POSITIVE_RESULTS = {"no_relevant_update", "candidate_found", "verified_event"}


def _latest_receipts(receipts: Iterable[AcquisitionReceipt]) -> dict[str, AcquisitionReceipt]:
    latest: dict[str, AcquisitionReceipt] = {}
    for receipt in receipts:
        previous = latest.get(receipt.task_id)
        if previous is None or datetime.fromisoformat(receipt.checked_at) > datetime.fromisoformat(previous.checked_at):
            latest[receipt.task_id] = receipt
    return latest


def _access_result(receipts: list[AcquisitionReceipt]) -> str:
    if any(item.retrieval_method == "browser_authenticated" and item.result in POSITIVE_RESULTS for item in receipts):
        return "checked_authenticated"
    if any(item.result == "login_required" for item in receipts):
        return "login_required"
    if any(item.result == "blocked" for item in receipts):
        return "blocked"
    if any(item.result in POSITIVE_RESULTS | {"not_applicable"} for item in receipts):
        return "public_checked"
    return "not_checked"


def _source_entry(receipt: AcquisitionReceipt) -> dict:
    entry = {
        "source_type": receipt.source_type,
        "url": receipt.final_url,
        "result": receipt.result,
        "checked_at": receipt.checked_at,
        "notes": receipt.notes,
        "acquisition_receipt": {
            "task_id": receipt.task_id,
            "retrieval_method": receipt.retrieval_method,
            "attempts": receipt.attempts,
            "http_status": receipt.http_status,
            "content_hash": receipt.content_hash,
            "content_ref": receipt.content_ref,
            "error_type": receipt.error_type,
            "route_verified": receipt.route_verified,
        },
    }
    if receipt.snapshot is not None:
        entry["snapshot"] = receipt.snapshot
    return entry


def build_coverage_ledger(
    manifest: AcquisitionManifest,
    receipts: Iterable[AcquisitionReceipt],
) -> list[dict]:
    tasks_by_id = {task.task_id: task for task in manifest.tasks}
    checked_receipts: list[AcquisitionReceipt] = []
    for receipt in receipts:
        task = tasks_by_id.get(receipt.task_id)
        if task is None:
            raise ValueError(f"receipt task is not present in manifest: {receipt.task_id}")
        validate_receipt_for_task(receipt, task)
        checked_receipts.append(receipt)
    receipts_by_task = _latest_receipts(checked_receipts)
    groups: dict[tuple[str, str, str], list[AcquisitionTask]] = defaultdict(list)
    for task in manifest.tasks:
        groups[(task.platform, task.seller_market, task.program)].append(task)
    declared_gaps: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for gap in manifest.planning_gaps:
        key = (gap["platform"], gap["seller_market"], gap["program"])
        declared_gaps[key].append(gap)
        groups.setdefault(key, [])

    ledger: list[dict] = []
    for (platform, seller_market, program), tasks in sorted(groups.items()):
        group_receipts = [receipts_by_task[task.task_id] for task in tasks if task.task_id in receipts_by_task]
        gaps: list[str] = []
        for gap in declared_gaps[(platform, seller_market, program)]:
            gaps.append(f"Declared {gap['source_type']} source gap: {gap['reason']}")
        for task in tasks:
            receipt = receipts_by_task.get(task.task_id)
            if receipt is None:
                gaps.append(f"No acquisition receipt for {task.source_type}: {task.url}")
                continue
            if task.route_verification_required and not receipt.route_verified:
                gaps.append(f"Official country route still requires verification: {task.url}")
            if task.source_type in {"official_updates", "current_policy"} and receipt.result in POSITIVE_RESULTS and receipt.snapshot is None:
                gaps.append(f"Public source opened without required snapshot: {receipt.final_url}")
        checked_at = max(
            (receipt.checked_at for receipt in group_receipts),
            default=manifest.cutoff,
            key=datetime.fromisoformat,
        )
        ledger.append({
            "platform": platform,
            "seller_market": seller_market,
            "program": program,
            "lookback_start": min((task.window_start for task in tasks), default=manifest.window_start),
            "public_update_checked": any(item.source_type == "official_updates" for item in group_receipts),
            "current_policy_checked": any(item.source_type == "current_policy" for item in group_receipts),
            "dashboard_checked": any(item.source_type == "dashboard" for item in group_receipts),
            "access_result": _access_result(group_receipts),
            "checked_at": checked_at,
            "sources_checked": [_source_entry(item) for item in sorted(group_receipts, key=lambda value: value.checked_at)],
            "verified_event_ids": [],
            "gaps": gaps,
        })
    return ledger
