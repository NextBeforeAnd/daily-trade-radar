"""Validated JSON profiles for repeatable radar runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


PROFILE_VERSION = "1.0"


def _path(base: Path, value: object, field: str) -> Path | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"profile.{field} must be a nonblank path")
    path = Path(value.strip())
    return path if path.is_absolute() else (base / path).resolve()


@dataclass(frozen=True)
class RadarProfile:
    source_path: Path
    name: str
    scope: dict[str, Any]
    candidate_report: Path | None
    previous_report: Path | None
    catalog: Path | None
    output_directory: Path
    output_basename: str
    formats: tuple[str, ...]
    threshold: float
    review_threshold: float
    language_mode: str
    alert_min_level: str
    alert_require_match: bool
    alert_state_file: Path | None
    alert_webhook: str | None


def load_profile(path: Path) -> RadarProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("profile must be a JSON object")
    allowed = {
        "schema_version", "name", "scope", "candidate_report", "previous_report",
        "catalog", "output", "deduplication", "quality", "alerts",
    }
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"profile contains unknown fields: {', '.join(sorted(unknown))}")
    if payload.get("schema_version") != PROFILE_VERSION:
        raise ValueError(f"profile.schema_version must be {PROFILE_VERSION!r}")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("profile.name must be a nonblank string")
    scope = payload.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("profile.scope must be an object")
    output = payload.get("output", {})
    dedupe = payload.get("deduplication", {})
    alerts = payload.get("alerts", {})
    quality = payload.get("quality", {})
    if not all(isinstance(item, dict) for item in (output, dedupe, quality, alerts)):
        raise ValueError("profile.output, deduplication, quality, and alerts must be objects")
    base = path.resolve().parent
    directory = _path(base, output.get("directory", "radar-run"), "output.directory")
    assert directory is not None
    basename = output.get("basename", "daily-trade-radar")
    if not isinstance(basename, str) or not basename.strip() or any(char in basename for char in "\\/:"):
        raise ValueError("profile.output.basename must be a safe nonblank filename stem")
    formats = output.get("formats", ["markdown"])
    if not isinstance(formats, list) or not formats or any(item not in {"markdown", "docx"} for item in formats):
        raise ValueError("profile.output.formats must contain markdown and/or docx")
    threshold = dedupe.get("threshold", 0.82)
    review_threshold = dedupe.get("review_threshold", 0.65)
    if isinstance(threshold, bool) or isinstance(review_threshold, bool):
        raise ValueError("profile deduplication thresholds must be numbers")
    if not all(isinstance(value, (int, float)) for value in (threshold, review_threshold)):
        raise ValueError("profile deduplication thresholds must be numbers")
    if not 0 <= float(review_threshold) <= float(threshold) <= 1:
        raise ValueError("profile requires 0 <= review_threshold <= threshold <= 1")
    language_mode = quality.get("language_mode", "warn")
    if language_mode not in {"off", "warn", "strict"}:
        raise ValueError("profile.quality.language_mode must be off, warn, or strict")
    min_level = alerts.get("min_level", "high")
    if min_level not in {"watch", "low", "medium", "high"}:
        raise ValueError("profile.alerts.min_level is invalid")
    require_match = alerts.get("require_applicability_match", payload.get("catalog") is not None)
    if not isinstance(require_match, bool):
        raise ValueError("profile.alerts.require_applicability_match must be boolean")
    webhook = alerts.get("webhook")
    if webhook is not None and (not isinstance(webhook, str) or not webhook.startswith("https://")):
        raise ValueError("profile.alerts.webhook must be an https URL")
    return RadarProfile(
        source_path=path.resolve(), name=name.strip(), scope=scope,
        candidate_report=_path(base, payload.get("candidate_report"), "candidate_report"),
        previous_report=_path(base, payload.get("previous_report"), "previous_report"),
        catalog=_path(base, payload.get("catalog"), "catalog"),
        output_directory=directory, output_basename=basename.strip(), formats=tuple(dict.fromkeys(formats)),
        threshold=float(threshold), review_threshold=float(review_threshold),
        language_mode=language_mode,
        alert_min_level=min_level, alert_require_match=require_match,
        alert_state_file=_path(base, alerts.get("state_file"), "alerts.state_file"),
        alert_webhook=webhook,
    )
