"""Adapter protocol for one bounded acquisition task."""

from __future__ import annotations

from typing import Protocol

from ..models import AcquisitionReceipt, AcquisitionTask


class AcquisitionAdapter(Protocol):
    def acquire(self, task: AcquisitionTask, checked_at: str) -> AcquisitionReceipt:
        """Attempt one manifest task and return an auditable receipt."""
