"""Storage contract for platform-page snapshots."""

from __future__ import annotations

from typing import Protocol


class SnapshotStore(Protocol):
    backend_name: str

    def capture(self, platform: str, url: str, content: str, captured_at: str) -> dict:
        """Persist a capture and return report-safe snapshot metadata."""

    def load_latest(self, platform: str, url: str) -> dict | None:
        """Return the latest stored snapshot record for a platform page."""


def create_snapshot_store(backend: str, root, **options) -> SnapshotStore:
    normalized = backend.casefold().strip()
    if normalized == "filesystem":
        from .filesystem import FilesystemSnapshotStore

        return FilesystemSnapshotStore(root, **options)
    if normalized == "sqlite":
        from .sqlite import SQLiteSnapshotStore

        return SQLiteSnapshotStore(root, **options)
    if normalized == "git":
        from .git import GitSnapshotStore

        return GitSnapshotStore(root, **options)
    if normalized == "s3":
        from .s3 import S3SnapshotStore

        return S3SnapshotStore(root, **options)
    raise ValueError(f"unsupported snapshot backend: {backend}")
