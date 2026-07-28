"""Git-versioned filesystem backend for public platform-page snapshots."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from .filesystem import FileLock, FilesystemSnapshotStore, atomic_write_text, normalize_content


MARKER_NAME = ".daily-trade-radar-snapshot-store.json"
MARKER = {
    "schema_version": 1,
    "store_type": "daily-trade-radar-git-snapshots",
    "content_policy": "public-platform-pages-only",
}


class GitSnapshotStore:
    """Store public snapshots as files and commit every capture to a dedicated Git repository."""

    backend_name = "git"

    def __init__(self, root: Path, lock_timeout: float = 5.0, git_executable: str = "git"):
        if lock_timeout <= 0:
            raise ValueError("Git snapshot lock timeout must be positive")
        self.root = Path(root).resolve()
        self.lock_timeout = lock_timeout
        self.git_executable = git_executable
        self.data_root = self.root / "snapshots"
        self._initialize_repository()
        self.filesystem = FilesystemSnapshotStore(self.data_root, lock_timeout=lock_timeout)

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = [
            self.git_executable,
            "-c", "core.autocrlf=false",
            "-c", "core.hooksPath=.git/daily-trade-radar-no-hooks",
            *args,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        except FileNotFoundError as exc:
            raise OSError(f"Git executable not found: {self.git_executable}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise OSError(f"Git command failed ({' '.join(args)}): {detail or result.returncode}")
        return result

    def _initialize_repository(self) -> None:
        if self.root.exists() and not self.root.is_dir():
            raise ValueError("Git snapshot store must be a directory")
        self.root.mkdir(parents=True, exist_ok=True)
        git_dir = self.root / ".git"
        marker_path = self.root / MARKER_NAME
        if git_dir.exists():
            if not marker_path.is_file():
                raise ValueError("refusing to use an unmarked Git repository as a snapshot store")
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError("invalid Git snapshot-store marker") from exc
            if marker != MARKER:
                raise ValueError("Git snapshot-store marker is incompatible")
            return
        if any(self.root.iterdir()):
            raise ValueError("refusing to initialize a Git snapshot store in a non-empty directory")
        if shutil.which(self.git_executable) is None:
            raise OSError(f"Git executable not found: {self.git_executable}")
        self._git("init", "--quiet")
        (git_dir / "daily-trade-radar-no-hooks").mkdir(exist_ok=True)
        atomic_write_text(marker_path, json.dumps(MARKER, ensure_ascii=False, indent=2) + "\n")
        atomic_write_text(self.root / ".gitattributes", "* text eol=lf\n")
        self._git("add", "--", MARKER_NAME, ".gitattributes")
        self._commit("Initialize Daily Trade Radar snapshot store")

    def _commit(self, message: str) -> None:
        self._git(
            "-c", "user.name=Daily Trade Radar",
            "-c", "user.email=snapshots@daily-trade-radar.invalid",
            "commit", "--quiet", "--no-gpg-sign", "--no-verify", "-m", message,
        )

    def _status(self) -> str:
        return self._git("status", "--porcelain=v1", "--untracked-files=all").stdout.strip()

    def _revision(self) -> tuple[str, str]:
        commit = self._git("rev-parse", "HEAD").stdout.strip()
        tree = self._git("rev-parse", "HEAD^{tree}").stdout.strip()
        return commit, tree

    def _metadata(self, metadata: dict) -> dict:
        commit, tree = self._revision()
        result = dict(metadata)
        result["storage_backend"] = self.backend_name
        result["snapshot_ref"] = f"snapshots/{metadata['snapshot_ref']}"
        if metadata.get("diff_ref") is not None:
            result["diff_ref"] = f"snapshots/{metadata['diff_ref']}"
        result["git_commit"] = commit
        result["git_tree"] = tree
        return result

    def load_latest(self, platform: str, url: str) -> dict | None:
        return self.filesystem.load_latest(platform, url)

    def capture(self, platform: str, url: str, content: str, captured_at: str) -> dict:
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("platform must not be blank")
        lock_path = self.root / ".git" / "daily-trade-radar-capture.lock"
        with FileLock(lock_path, timeout=self.lock_timeout):
            status = self._status()
            if status:
                raise ValueError("Git snapshot store has uncommitted changes; audit and resolve them before capture")
            previous = self.filesystem.load_latest(platform, url)
            if previous is not None:
                previous_time = datetime.fromisoformat(previous["captured_at"])
                try:
                    current_time = datetime.fromisoformat(captured_at)
                except (TypeError, ValueError) as exc:
                    raise ValueError("captured_at must be ISO 8601") from exc
                if current_time.tzinfo is None or current_time.utcoffset() is None:
                    raise ValueError("captured_at must include a UTC offset")
                if current_time < previous_time:
                    raise ValueError("captured_at must not be earlier than the latest Git snapshot")
                current_hash = hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()
                if current_time == previous_time and current_hash != previous.get("content_hash"):
                    raise ValueError("captured_at must advance when Git snapshot content changes")
            metadata = self.filesystem.capture(platform, url, content, captured_at)
            self._git("add", "--", "snapshots")
            staged = self._git("diff", "--cached", "--quiet", check=False)
            if staged.returncode not in {0, 1}:
                raise OSError("could not inspect staged Git snapshot changes")
            if staged.returncode == 1:
                safe_platform = re.sub(r"\s+", " ", platform).strip()[:80]
                self._commit(f"Snapshot {safe_platform}: {metadata['snapshot_id']}")
            if self._status():
                raise OSError("Git snapshot commit did not leave a clean repository")
            return self._metadata(metadata)

    def audit(self) -> dict:
        """Verify repository integrity, tracked files, content hashes, chains, and indexes."""
        errors: list[str] = []
        fsck = self._git("fsck", "--full", "--no-dangling", check=False)
        if fsck.returncode != 0:
            errors.append(f"git fsck failed: {(fsck.stderr or fsck.stdout).strip()}")
        status = self._status()
        if status:
            errors.append("working tree is not clean")

        snapshot_count = 0
        page_count = 0
        for page_dir in sorted(self.data_root.glob("*/*")) if self.data_root.exists() else []:
            if not page_dir.is_dir():
                continue
            page_count += 1
            records: list[tuple[datetime, str, dict, Path]] = []
            for path in page_dir.glob("*.json"):
                if path.name == "index.json":
                    continue
                snapshot_count += 1
                relative = path.relative_to(self.root).as_posix()
                tracked = self._git("ls-files", "--error-unmatch", "--", relative, check=False)
                if tracked.returncode != 0:
                    errors.append(f"untracked snapshot: {relative}")
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    captured = datetime.fromisoformat(record["captured_at"])
                    if captured.tzinfo is None or captured.utcoffset() is None:
                        raise ValueError("missing UTC offset")
                    content_hash = hashlib.sha256(normalize_content(record["content"]).encode("utf-8")).hexdigest()
                    if content_hash != record.get("content_hash"):
                        errors.append(f"content hash mismatch: {relative}")
                    if path.stem != record.get("snapshot_id"):
                        errors.append(f"snapshot filename/id mismatch: {relative}")
                    records.append((captured, path.name, record, path))
                except (KeyError, TypeError, ValueError, json.JSONDecodeError, OSError) as exc:
                    errors.append(f"invalid snapshot {relative}: {exc}")
            records.sort(key=lambda item: (item[0], item[1]))
            previous: dict | None = None
            for _captured, _name, record, path in records:
                expected_previous = previous.get("snapshot_id") if previous else None
                if record.get("previous_snapshot_id") != expected_previous:
                    errors.append(f"broken previous-snapshot chain: {path.relative_to(self.root).as_posix()}")
                expected_status = "first_seen" if previous is None else (
                    "unchanged" if previous.get("content_hash") == record.get("content_hash") else "changed"
                )
                if record.get("change_status") != expected_status:
                    errors.append(f"invalid change status: {path.relative_to(self.root).as_posix()}")
                previous = record
            index_path = page_dir / "index.json"
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
                latest_id = records[-1][2]["snapshot_id"] if records else None
                if index.get("latest_snapshot_id") != latest_id:
                    errors.append(f"stale page index: {index_path.relative_to(self.root).as_posix()}")
            except (OSError, json.JSONDecodeError, KeyError) as exc:
                errors.append(f"invalid page index {index_path.relative_to(self.root).as_posix()}: {exc}")

        commit, tree = self._revision()
        return {
            "valid": not errors,
            "storage_backend": self.backend_name,
            "repository": str(self.root),
            "head_commit": commit,
            "head_tree": tree,
            "page_count": page_count,
            "snapshot_count": snapshot_count,
            "errors": errors,
        }
