"""Receipts for content already opened manually or in the in-app browser."""

from __future__ import annotations

from ..cache import AcquisitionCache
from ..models import AcquisitionReceipt, AcquisitionTask
from ..receipts import create_receipt


def manual_receipt(
    task: AcquisitionTask,
    checked_at: str,
    result: str,
    notes: str,
    content: str | None = None,
    final_url: str | None = None,
    cache: AcquisitionCache | None = None,
    snapshot: dict | None = None,
    route_verified: bool = False,
) -> AcquisitionReceipt:
    return create_receipt(
        task,
        checked_at,
        result,
        "manual",
        notes,
        content=content,
        final_url=final_url,
        cache=cache,
        snapshot=snapshot,
        route_verified=route_verified,
    )


def browser_receipt(
    task: AcquisitionTask,
    checked_at: str,
    result: str,
    notes: str,
    visible_text: str | None = None,
    final_url: str | None = None,
    authenticated: bool = False,
    cache: AcquisitionCache | None = None,
    snapshot: dict | None = None,
    route_verified: bool = False,
) -> AcquisitionReceipt:
    return create_receipt(
        task,
        checked_at,
        result,
        "browser_authenticated" if authenticated else "browser_public",
        notes,
        content=visible_text,
        final_url=final_url,
        cache=cache,
        snapshot=snapshot,
        route_verified=route_verified,
    )
