"""Typed acquisition tasks and evidence receipts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit


SOURCE_TYPES = {"official_updates", "current_policy", "dashboard", "discovery_lead"}
RESULTS = {"no_relevant_update", "candidate_found", "verified_event", "login_required", "blocked", "not_applicable"}
RETRIEVAL_METHODS = {"browser_public", "browser_authenticated", "manual", "http", "rss", "atom", "sitemap"}
TASK_ID_PATTERN = re.compile(r"[0-9a-f]{24}")


def require_datetime_offset(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO 8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO 8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset")
    return value


def require_url(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a direct http(s) URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be a direct http(s) URL")
    return value


def stable_task_id(
    platform: str,
    seller_market: str,
    program: str,
    source_type: str,
    url: str,
    window_start: str,
) -> str:
    payload = "\n".join((platform.casefold(), seller_market.casefold(), program.casefold(), source_type, url, window_start))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class AcquisitionTask:
    task_id: str
    platform: str
    seller_market: str
    program: str
    source_type: str
    url: str
    window_start: str
    requires_auth: bool = False
    route_verification_required: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not TASK_ID_PATTERN.fullmatch(self.task_id):
            raise ValueError("task_id must be a 24-character lowercase hexadecimal digest")
        if not isinstance(self.source_type, str) or self.source_type not in SOURCE_TYPES:
            raise ValueError("source_type is invalid")
        if not isinstance(self.requires_auth, bool) or not isinstance(self.route_verification_required, bool):
            raise ValueError("task authentication and route-verification flags must be booleans")
        if not isinstance(self.notes, str):
            raise ValueError("notes must be a string")
        require_url(self.url, "url")
        require_datetime_offset(self.window_start, "window_start")
        for field in ("platform", "seller_market", "program"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} must not be blank")
        expected_id = stable_task_id(
            self.platform, self.seller_market, self.program, self.source_type, self.url, self.window_start
        )
        if self.task_id != expected_id:
            raise ValueError("task_id does not match the task identity fields")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcquisitionTask":
        return cls(**value)


@dataclass(frozen=True)
class AcquisitionReceipt:
    task_id: str
    platform: str
    seller_market: str
    program: str
    source_type: str
    requested_url: str
    final_url: str
    result: str
    checked_at: str
    retrieval_method: str
    attempts: int
    notes: str
    route_verified: bool = False
    http_status: int | None = None
    content_hash: str | None = None
    content_ref: str | None = None
    error_type: str | None = None
    snapshot: dict[str, Any] | None = None
    authenticated_content_persisted: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, str) or not TASK_ID_PATTERN.fullmatch(self.task_id):
            raise ValueError("task_id must be a 24-character lowercase hexadecimal digest")
        if not isinstance(self.source_type, str) or self.source_type not in SOURCE_TYPES:
            raise ValueError("source_type is invalid")
        if not isinstance(self.result, str) or self.result not in RESULTS:
            raise ValueError("result is invalid")
        if not isinstance(self.retrieval_method, str) or self.retrieval_method not in RETRIEVAL_METHODS:
            raise ValueError("retrieval_method is invalid")
        for field in ("platform", "seller_market", "program"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} must not be blank")
        require_url(self.requested_url, "requested_url")
        require_url(self.final_url, "final_url")
        require_datetime_offset(self.checked_at, "checked_at")
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int) or self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.http_status is not None and (
            isinstance(self.http_status, bool) or not isinstance(self.http_status, int) or not 100 <= self.http_status <= 599
        ):
            raise ValueError("http_status must be an integer from 100 to 599")
        if not isinstance(self.route_verified, bool) or not isinstance(self.authenticated_content_persisted, bool):
            raise ValueError("receipt safety flags must be booleans")
        if not isinstance(self.notes, str):
            raise ValueError("notes must be a string")
        if self.content_hash is not None and (
            not isinstance(self.content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", self.content_hash)
        ):
            raise ValueError("content_hash must be a SHA-256 hex digest")
        if self.content_ref is not None:
            if not isinstance(self.content_ref, str):
                raise ValueError("content_ref must be a portable store-relative POSIX path")
            ref = PurePosixPath(self.content_ref)
            if ref.is_absolute() or ".." in ref.parts or "\\" in self.content_ref:
                raise ValueError("content_ref must be a portable store-relative POSIX path")
        if self.retrieval_method == "browser_authenticated" and self.content_ref is not None:
            raise ValueError("authenticated browser content must not have a content_ref")
        if self.retrieval_method == "browser_authenticated" and self.authenticated_content_persisted:
            raise ValueError("authenticated browser content must not be persisted")
        if self.error_type is not None and not isinstance(self.error_type, str):
            raise ValueError("error_type must be a string or null")
        if self.snapshot is not None and not isinstance(self.snapshot, dict):
            raise ValueError("snapshot must be an object or null")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcquisitionReceipt":
        return cls(**value)


def validate_receipt_for_task(receipt: AcquisitionReceipt, task: AcquisitionTask) -> None:
    """Fail closed when receipt scope or route fields do not match its manifest task."""
    comparisons = {
        "task_id": (receipt.task_id, task.task_id),
        "platform": (receipt.platform, task.platform),
        "seller_market": (receipt.seller_market, task.seller_market),
        "program": (receipt.program, task.program),
        "source_type": (receipt.source_type, task.source_type),
        "requested_url": (receipt.requested_url, task.url),
    }
    mismatches = [name for name, (actual, expected) in comparisons.items() if actual != expected]
    if mismatches:
        raise ValueError(f"receipt does not match manifest task: {', '.join(mismatches)}")
