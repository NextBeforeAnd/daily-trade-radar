"""Content-addressed public evidence and task-receipt cache."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from ..snapshots.filesystem import atomic_write_text
from .models import AcquisitionReceipt, TASK_ID_PATTERN, require_datetime_offset


REUSABLE_RESULTS = {"no_relevant_update", "candidate_found", "verified_event"}


class AcquisitionCache:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _safe_target(self, path: Path) -> Path:
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError("cache path escapes the configured root")
        return resolved

    def put_content(self, content: str) -> tuple[str, str]:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        path = self._safe_target(self.root / "content" / "sha256" / digest[:2] / f"{digest}.txt")
        if not path.exists():
            atomic_write_text(path, content)
        return digest, path.relative_to(self.root).as_posix()

    def get_content(self, ref: str) -> str:
        path = Path(ref)
        resolved = (self.root / path).resolve()
        if path.is_absolute() or ".." in path.parts or not resolved.is_relative_to(self.root):
            raise ValueError("content ref must be store-relative")
        return resolved.read_text(encoding="utf-8")

    def _receipt_path(self, task_id: str) -> Path:
        if not isinstance(task_id, str) or not TASK_ID_PATTERN.fullmatch(task_id):
            raise ValueError("task_id must be a 24-character lowercase hexadecimal digest")
        return self._safe_target(self.root / "receipts" / f"{task_id}.json")

    def save_receipt(self, receipt: AcquisitionReceipt) -> str:
        path = self._receipt_path(receipt.task_id)
        content = json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2) + "\n"
        history_digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        history_path = self._safe_target(
            self.root / "receipt-history" / receipt.task_id / f"{history_digest}.json"
        )
        if not history_path.exists():
            atomic_write_text(history_path, content)
        atomic_write_text(path, content)
        return path.relative_to(self.root).as_posix()

    def load_receipt(
        self,
        task_id: str,
        *,
        reusable_only: bool = False,
        max_age_seconds: float | None = None,
        current_time: str | None = None,
    ) -> AcquisitionReceipt | None:
        path = self._receipt_path(task_id)
        if max_age_seconds is not None:
            if max_age_seconds < 0 or current_time is None:
                raise ValueError("non-negative max_age_seconds requires current_time")
            require_datetime_offset(current_time, "current_time")
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            receipt = AcquisitionReceipt.from_dict(value)
            if reusable_only and receipt.result not in REUSABLE_RESULTS:
                return None
            if max_age_seconds is not None:
                age = datetime.fromisoformat(current_time) - datetime.fromisoformat(receipt.checked_at)
                if age.total_seconds() < 0 or age.total_seconds() > max_age_seconds:
                    return None
            return receipt
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
