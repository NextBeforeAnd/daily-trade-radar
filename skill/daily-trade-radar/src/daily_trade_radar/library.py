"""Persistent local history for validated radar reports and event sightings."""

from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable

from .snapshots.filesystem import atomic_write_text
from .validation import validate


SCHEMA_VERSION = "1.0"


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _report_key(report: dict[str, Any]) -> str:
    identity = {
        "report_date": report.get("report_date"),
        "cutoff": report.get("cutoff"),
        "scope": report.get("scope"),
    }
    return hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:24]


def _content_hash(report: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(report).encode("utf-8")).hexdigest()


def connect_library(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reports (
            report_key TEXT PRIMARY KEY,
            report_date TEXT NOT NULL,
            cutoff TEXT NOT NULL,
            language TEXT NOT NULL,
            scope_json TEXT NOT NULL,
            source_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            ingested_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS events (
            report_key TEXT NOT NULL REFERENCES reports(report_key) ON DELETE CASCADE,
            event_id TEXT NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            level TEXT NOT NULL,
            jurisdiction TEXT NOT NULL,
            authority TEXT NOT NULL,
            published_date TEXT,
            effective_date TEXT,
            deadline TEXT,
            products TEXT NOT NULL,
            summary TEXT NOT NULL,
            impact TEXT NOT NULL,
            action TEXT NOT NULL,
            source_title TEXT NOT NULL,
            source_url TEXT NOT NULL,
            platform TEXT,
            event_json TEXT NOT NULL,
            PRIMARY KEY (report_key, event_id)
        );
        CREATE INDEX IF NOT EXISTS events_event_id ON events(event_id);
        CREATE INDEX IF NOT EXISTS reports_cutoff ON reports(cutoff);
        """
    )
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES ('schema_version', ?)",
        (SCHEMA_VERSION,),
    )
    try:
        connection.execute(
            """CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
                report_key UNINDEXED, event_id UNINDEXED, title, summary, impact,
                action, jurisdiction, authority, products, source_title
            )"""
        )
        connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('fts5', 'enabled')")
    except sqlite3.OperationalError:
        connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES ('fts5', 'unavailable')")
    return connection


def _is_fts_enabled(connection: sqlite3.Connection) -> bool:
    row = connection.execute("SELECT value FROM metadata WHERE key = 'fts5'").fetchone()
    return bool(row and row[0] == "enabled")


def load_report(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("events"), list):
        raise ValueError(f"{path}: expected a radar object with an events array")
    errors = validate(value)
    if errors:
        preview = "; ".join(errors[:5])
        suffix = f"; plus {len(errors) - 5} more" if len(errors) > 5 else ""
        raise ValueError(f"{path}: report validation failed: {preview}{suffix}")
    return value


def ingest_report(
    connection: sqlite3.Connection,
    report: dict[str, Any],
    source_path: Path,
    *,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    timestamp = ingested_at or datetime.now().astimezone().isoformat(timespec="seconds")
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("ingested_at must include a UTC offset")
    key = _report_key(report)
    report_date = str(report["report_date"])
    cutoff = str(report["cutoff"])
    language = str(report.get("language", "zh-CN"))
    scope_json = _canonical(report.get("scope", []))
    source = str(source_path.resolve())
    event_rows: list[tuple[Any, ...]] = []
    for event in report["events"]:
        policy = event.get("platform_policy") if isinstance(event.get("platform_policy"), dict) else {}
        products = " | ".join(str(item) for item in event.get("products_or_channels", []))
        event_rows.append((
            key, event["id"], event["title"], event["status"], event["level"], event["jurisdiction"],
            event["authority"], event.get("published_date"), event.get("effective_date"), event.get("deadline"),
            products, event["summary"], event["impact"], event["action"], event["source_title"],
            event["source_url"], policy.get("platform"), _canonical(event),
        ))
    with connection:
        connection.execute("DELETE FROM reports WHERE report_key = ?", (key,))
        if _is_fts_enabled(connection):
            connection.execute("DELETE FROM event_fts WHERE report_key = ?", (key,))
        connection.execute(
            """INSERT INTO reports(
                report_key, report_date, cutoff, language, scope_json, source_path, content_hash, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (key, report_date, cutoff, language, scope_json, source, _content_hash(report), timestamp),
        )
        connection.executemany(
            """INSERT INTO events(
                report_key, event_id, title, status, level, jurisdiction, authority,
                published_date, effective_date, deadline, products, summary, impact,
                action, source_title, source_url, platform, event_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            event_rows,
        )
        if _is_fts_enabled(connection):
            connection.executemany(
                """INSERT INTO event_fts(
                    report_key, event_id, title, summary, impact, action,
                    jurisdiction, authority, products, source_title
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (row[0], row[1], row[2], row[11], row[12], row[13], row[5], row[6], row[10], row[14])
                    for row in event_rows
                ],
            )
    return {"report_key": key, "report_date": report_date, "event_count": len(event_rows), "source_path": source}


def _report_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(path.rglob("*.json"))
    raise ValueError(f"input path does not exist: {path}")


def ingest_path(
    database: Path,
    input_path: Path,
    *,
    ingested_at: str | None = None,
) -> dict[str, Any]:
    paths = _report_paths(input_path)
    if not paths:
        raise ValueError(f"input path contains no JSON files: {input_path}")
    imported: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    with closing(connect_library(database)) as connection:
        for path in paths:
            try:
                report = load_report(path)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                if input_path.is_file():
                    raise
                skipped.append({"path": str(path.resolve()), "reason": str(exc)})
                continue
            imported.append(ingest_report(connection, report, path, ingested_at=ingested_at))
    return {
        "schema_version": SCHEMA_VERSION,
        "database": str(database.resolve()),
        "imported_count": len(imported),
        "event_count": sum(item["event_count"] for item in imported),
        "imported": imported,
        "skipped": skipped,
    }


def _like_event_ids(connection: sqlite3.Connection, query: str, limit: int) -> list[str]:
    pattern = f"%{query}%"
    rows = connection.execute(
        """SELECT DISTINCT event_id FROM events
           WHERE title LIKE ? COLLATE NOCASE OR summary LIKE ? COLLATE NOCASE
              OR impact LIKE ? COLLATE NOCASE OR action LIKE ? COLLATE NOCASE
              OR jurisdiction LIKE ? COLLATE NOCASE OR authority LIKE ? COLLATE NOCASE
              OR products LIKE ? COLLATE NOCASE OR source_title LIKE ? COLLATE NOCASE
           LIMIT ?""",
        (*([pattern] * 8), limit),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _fts_expression(query: str) -> str:
    tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"*' for token in tokens)


def _matching_event_ids(connection: sqlite3.Connection, query: str, limit: int) -> list[str]:
    ids: list[str] = []
    if _is_fts_enabled(connection):
        expression = _fts_expression(query)
        if expression:
            try:
                ids.extend(str(row[0]) for row in connection.execute(
                    "SELECT DISTINCT event_id FROM event_fts WHERE event_fts MATCH ? LIMIT ?",
                    (expression, limit),
                ).fetchall())
            except sqlite3.OperationalError:
                pass
    for event_id in _like_event_ids(connection, query, limit):
        if event_id not in ids:
            ids.append(event_id)
    return ids[:limit]


def event_history(connection: sqlite3.Connection, event_id: str) -> dict[str, Any] | None:
    rows = connection.execute(
        """SELECT e.event_json, r.report_date, r.cutoff, r.source_path, r.report_key
           FROM events e JOIN reports r ON r.report_key = e.report_key
           WHERE e.event_id = ? ORDER BY r.cutoff, r.report_date""",
        (event_id,),
    ).fetchall()
    if not rows:
        return None
    sightings = [
        {
            "report_key": row["report_key"],
            "report_date": row["report_date"],
            "cutoff": row["cutoff"],
            "source_path": row["source_path"],
            "event": json.loads(row["event_json"]),
        }
        for row in rows
    ]
    return {
        "event_id": event_id,
        "first_seen": sightings[0]["report_date"],
        "last_seen": sightings[-1]["report_date"],
        "sighting_count": len(sightings),
        "latest": sightings[-1],
        "sightings": sightings,
    }


def search_library(database: Path, query: str, *, limit: int = 20) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("search query must not be blank")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer from 1 to 100")
    if not database.exists():
        raise ValueError(f"library database does not exist: {database}")
    with closing(connect_library(database)) as connection:
        event_ids = _matching_event_ids(connection, query.strip(), limit)
        results = [history for event_id in event_ids if (history := event_history(connection, event_id)) is not None]
        fts = _is_fts_enabled(connection)
    results.sort(key=lambda item: (item["last_seen"], item["event_id"]), reverse=True)
    return {
        "schema_version": SCHEMA_VERSION,
        "database": str(database.resolve()),
        "query": query.strip(),
        "fts5": fts,
        "result_count": len(results),
        "results": results,
    }


def show_event(database: Path, event_id: str) -> dict[str, Any]:
    if not database.exists():
        raise ValueError(f"library database does not exist: {database}")
    with closing(connect_library(database)) as connection:
        history = event_history(connection, event_id)
    if history is None:
        raise ValueError(f"event id not found in library: {event_id}")
    return {"schema_version": SCHEMA_VERSION, "database": str(database.resolve()), **history}


def library_stats(database: Path) -> dict[str, Any]:
    if not database.exists():
        raise ValueError(f"library database does not exist: {database}")
    with closing(connect_library(database)) as connection:
        reports = connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
        sightings = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        events = connection.execute("SELECT COUNT(DISTINCT event_id) FROM events").fetchone()[0]
        earliest, latest = connection.execute("SELECT MIN(report_date), MAX(report_date) FROM reports").fetchone()
        fts = _is_fts_enabled(connection)
    return {
        "schema_version": SCHEMA_VERSION,
        "database": str(database.resolve()),
        "report_count": reports,
        "unique_event_count": events,
        "sighting_count": sightings,
        "earliest_report_date": earliest,
        "latest_report_date": latest,
        "fts5": fts,
    }


def _write(value: dict[str, Any], output: Path | None, *, as_json: bool = True) -> None:
    if as_json:
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    elif "results" in value:
        lines = [f"Library search: {value['query']} ({value['result_count']} result(s))"]
        for result in value["results"]:
            event = result["latest"]["event"]
            lines.append(
                f"- {event['title']} [{result['event_id']}] | {result['first_seen']}..{result['last_seen']} "
                f"| sightings={result['sighting_count']}"
            )
        content = "\n".join(lines) + "\n"
    else:
        content = "\n".join(f"{key}: {item}" for key, item in value.items() if key != "schema_version") + "\n"
    if output:
        atomic_write_text(output, content)
    else:
        print(content, end="")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("ingest", help="index one validated report or a directory of reports")
    ingest.add_argument("input", type=Path)
    ingest.add_argument("--db", type=Path, required=True)
    ingest.add_argument("--ingested-at")
    ingest.add_argument("--output", type=Path)
    search = commands.add_parser("search", help="search indexed event history")
    search.add_argument("query")
    search.add_argument("--db", type=Path, required=True)
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")
    search.add_argument("--output", type=Path)
    show = commands.add_parser("show", help="show every sighting for an exact event id")
    show.add_argument("event_id")
    show.add_argument("--db", type=Path, required=True)
    show.add_argument("--output", type=Path)
    stats = commands.add_parser("stats", help="summarize the local history library")
    stats.add_argument("--db", type=Path, required=True)
    stats.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ingest":
            value = ingest_path(args.db, args.input, ingested_at=args.ingested_at)
            _write(value, args.output)
        elif args.command == "search":
            value = search_library(args.db, args.query, limit=args.limit)
            _write(value, args.output, as_json=args.json or args.output is not None)
        elif args.command == "show":
            _write(show_event(args.db, args.event_id), args.output)
        else:
            _write(library_stats(args.db), args.output)
        return 0
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
