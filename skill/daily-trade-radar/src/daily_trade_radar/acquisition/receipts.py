"""Create evidence receipts from browser, manual, feed, or HTTP content."""

from __future__ import annotations

import hashlib
import unicodedata

from .cache import AcquisitionCache
from .models import AcquisitionReceipt, AcquisitionTask


def normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).replace("\u00a0", " ")
    return "\n".join(line.strip() for line in normalized.splitlines() if line.strip())


def create_receipt(
    task: AcquisitionTask,
    checked_at: str,
    result: str,
    retrieval_method: str,
    notes: str,
    content: str | None = None,
    final_url: str | None = None,
    http_status: int | None = None,
    attempts: int = 1,
    error_type: str | None = None,
    snapshot: dict | None = None,
    cache: AcquisitionCache | None = None,
    route_verified: bool = False,
) -> AcquisitionReceipt:
    normalized = normalize_evidence_text(content or "")
    content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest() if normalized else None
    content_ref = None
    authenticated = retrieval_method == "browser_authenticated"
    if normalized and cache is not None and not authenticated:
        stored_hash, content_ref = cache.put_content(normalized)
        if stored_hash != content_hash:
            raise ValueError("content cache hash mismatch")
    receipt = AcquisitionReceipt(
        task_id=task.task_id,
        platform=task.platform,
        seller_market=task.seller_market,
        program=task.program,
        source_type=task.source_type,
        requested_url=task.url,
        final_url=final_url or task.url,
        result=result,
        checked_at=checked_at,
        retrieval_method=retrieval_method,
        attempts=attempts,
        notes=notes,
        route_verified=route_verified,
        http_status=http_status,
        content_hash=content_hash,
        content_ref=content_ref,
        error_type=error_type,
        snapshot=snapshot,
        authenticated_content_persisted=False,
    )
    if cache is not None:
        cache.save_receipt(receipt)
    return receipt
