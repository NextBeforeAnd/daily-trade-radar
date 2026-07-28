"""Transactional SQLite backend for portable platform-page snapshot history."""

from __future__ import annotations

from datetime import datetime
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3

from .filesystem import SNAPSHOT_VERSION, canonical_url, diff_details, normalize_content, timestamp_slug


DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


class SQLiteSnapshotStore:
    backend_name = "sqlite"

    def __init__(self, root: Path, timeout: float = 5.0):
        if timeout <= 0:
            raise ValueError("SQLite timeout must be positive")
        requested = Path(root).resolve()
        self.db_path = requested if requested.suffix.casefold() in DATABASE_SUFFIXES else requested / "snapshots.sqlite3"
        self.root = self.db_path.parent
        self.timeout = timeout
        self._initialize()

    def _initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=self.timeout, isolation_level=None)
        try:
            connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            connection.executescript(
                """
            CREATE TABLE IF NOT EXISTS snapshots (
                page_key TEXT NOT NULL,
                snapshot_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                captured_epoch REAL NOT NULL,
                content_hash TEXT NOT NULL,
                previous_snapshot_id TEXT,
                change_status TEXT NOT NULL,
                diff_summary TEXT NOT NULL,
                content TEXT NOT NULL,
                diff_text TEXT,
                schema_version INTEGER NOT NULL,
                PRIMARY KEY (page_key, snapshot_id)
            );
            CREATE TABLE IF NOT EXISTS pages (
                page_key TEXT PRIMARY KEY,
                platform TEXT NOT NULL,
                url TEXT NOT NULL,
                latest_snapshot_id TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS snapshots_page_time
                ON snapshots (page_key, captured_epoch, snapshot_id);
            """
            )
        finally:
            connection.close()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=self.timeout, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    @staticmethod
    def _page_key(platform: str, canonical: str) -> str:
        return hashlib.sha256(f"{platform.casefold()}\n{canonical}".encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        return {
            "schema_version": row["schema_version"],
            "snapshot_id": row["snapshot_id"],
            "platform": row["platform"],
            "url": row["url"],
            "captured_at": row["captured_at"],
            "content_hash": row["content_hash"],
            "previous_snapshot_id": row["previous_snapshot_id"],
            "change_status": row["change_status"],
            "diff_summary": row["diff_summary"],
            "content": row["content"],
        }

    def _metadata(self, record: dict, page_key: str, has_diff: bool) -> dict:
        snapshot_id = record["snapshot_id"]
        database = str(self.db_path)
        snapshot_ref = f"{self.db_path.name}/snapshots/{page_key}/{snapshot_id}"
        diff_ref = f"{self.db_path.name}/diffs/{page_key}/{snapshot_id}" if has_diff else None
        return {
            "snapshot_id": snapshot_id,
            "captured_at": record["captured_at"],
            "content_hash": record["content_hash"],
            "previous_snapshot_id": record.get("previous_snapshot_id"),
            "change_status": record["change_status"],
            "diff_summary": record["diff_summary"],
            "snapshot_path": f"{database}#snapshot/{page_key}/{snapshot_id}",
            "diff_path": f"{database}#diff/{page_key}/{snapshot_id}" if has_diff else None,
            "storage_backend": self.backend_name,
            "snapshot_ref": snapshot_ref,
            "diff_ref": diff_ref,
            "index_recovered": False,
        }

    def _latest_row(self, connection: sqlite3.Connection, page_key: str) -> sqlite3.Row | None:
        return connection.execute(
            """
            SELECT snapshots.*
            FROM pages
            JOIN snapshots
              ON snapshots.page_key = pages.page_key
             AND snapshots.snapshot_id = pages.latest_snapshot_id
            WHERE pages.page_key = ?
            """,
            (page_key,),
        ).fetchone()

    def load_latest(self, platform: str, url: str) -> dict | None:
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("platform must not be blank")
        canonical = canonical_url(url)
        page_key = self._page_key(platform, canonical)
        with closing(self._connect()) as connection:
            row = self._latest_row(connection, page_key)
        return self._record(row) if row is not None else None

    def capture(self, platform: str, url: str, content: str, captured_at: str) -> dict:
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("platform must not be blank")
        if not isinstance(captured_at, str):
            raise ValueError("captured_at must be ISO 8601")
        try:
            parsed_time = datetime.fromisoformat(captured_at)
        except ValueError as exc:
            raise ValueError("captured_at must be ISO 8601") from exc
        if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
            raise ValueError("captured_at must include a UTC offset")

        canonical = canonical_url(url)
        normalized = normalize_content(content)
        if not normalized:
            raise ValueError("captured content is empty after normalization")
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        page_key = self._page_key(platform, canonical)
        snapshot_id = f"{timestamp_slug(captured_at)}-{content_hash[:12]}"
        captured_epoch = parsed_time.timestamp()

        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous_row = self._latest_row(connection, page_key)
            previous = self._record(previous_row) if previous_row is not None else None
            if previous_row is not None and captured_epoch < previous_row["captured_epoch"]:
                raise ValueError("captured_at must not be earlier than the latest SQLite snapshot")
            if previous and previous["snapshot_id"] == snapshot_id and previous["content_hash"] == content_hash:
                connection.commit()
                return self._metadata(previous, page_key, bool(previous_row["diff_text"]))

            previous_id = previous["snapshot_id"] if previous else None
            if previous is None:
                change_status = "first_seen"
                diff_summary = "First captured snapshot; no historical baseline is available."
                diff_text = None
            elif previous["content_hash"] == content_hash:
                change_status = "unchanged"
                diff_summary = "No normalized page-text change from the previous snapshot."
                diff_text = None
            else:
                change_status = "changed"
                diff_summary, diff_text = diff_details(previous["content"], normalized)

            connection.execute(
                """
                INSERT INTO snapshots (
                    page_key, snapshot_id, platform, url, captured_at, captured_epoch,
                    content_hash, previous_snapshot_id, change_status, diff_summary,
                    content, diff_text, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page_key, snapshot_id, platform, canonical, captured_at, captured_epoch,
                    content_hash, previous_id, change_status, diff_summary,
                    normalized, diff_text, SNAPSHOT_VERSION,
                ),
            )
            connection.execute(
                """
                INSERT INTO pages (page_key, platform, url, latest_snapshot_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(page_key) DO UPDATE SET
                    platform = excluded.platform,
                    url = excluded.url,
                    latest_snapshot_id = excluded.latest_snapshot_id
                """,
                (page_key, platform, canonical, snapshot_id),
            )
            connection.commit()
            record = {
                "snapshot_id": snapshot_id,
                "captured_at": captured_at,
                "content_hash": content_hash,
                "previous_snapshot_id": previous_id,
                "change_status": change_status,
                "diff_summary": diff_summary,
            }
            return self._metadata(record, page_key, diff_text is not None)
