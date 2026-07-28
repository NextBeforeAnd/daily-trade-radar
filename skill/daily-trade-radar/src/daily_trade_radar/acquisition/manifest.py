"""Build acquisition manifests from the platform registry."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from typing import Any, Iterable

from ..platforms import get_platform
from .models import AcquisitionTask, require_datetime_offset, stable_task_id


def calculate_manifest_id(
    created_at: str,
    window_start: str,
    cutoff: str,
    tasks: Iterable[AcquisitionTask],
    planning_gaps: Iterable[dict[str, str]] = (),
) -> str:
    payload = {
        "created_at": created_at,
        "window_start": window_start,
        "cutoff": cutoff,
        "tasks": [task.to_dict() for task in tasks],
        "planning_gaps": list(planning_gaps),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class AcquisitionManifest:
    manifest_id: str
    created_at: str
    window_start: str
    cutoff: str
    tasks: tuple[AcquisitionTask, ...]
    planning_gaps: tuple[dict[str, str], ...] = ()

    def __post_init__(self) -> None:
        require_datetime_offset(self.created_at, "created_at")
        require_datetime_offset(self.window_start, "window_start")
        require_datetime_offset(self.cutoff, "cutoff")
        if datetime.fromisoformat(self.window_start) > datetime.fromisoformat(self.cutoff):
            raise ValueError("window_start must not be after cutoff")
        if (datetime.fromisoformat(self.cutoff) - datetime.fromisoformat(self.window_start)).total_seconds() < 7 * 86400:
            raise ValueError("platform acquisition window must be at least 7 days")
        if not self.tasks and not self.planning_gaps:
            raise ValueError("manifest must contain at least one task or planning gap")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("manifest task ids must be unique")
        for index, gap in enumerate(self.planning_gaps):
            if not isinstance(gap, dict) or set(gap) != {"platform", "seller_market", "program", "source_type", "reason"}:
                raise ValueError(f"planning_gaps[{index}] has invalid fields")
            if gap["source_type"] not in {"official_updates", "current_policy", "dashboard"}:
                raise ValueError(f"planning_gaps[{index}].source_type is invalid")
            if any(not isinstance(value, str) or not value.strip() for value in gap.values()):
                raise ValueError(f"planning_gaps[{index}] values must be nonblank strings")
        expected_id = calculate_manifest_id(
            self.created_at, self.window_start, self.cutoff, self.tasks, self.planning_gaps
        )
        if self.manifest_id != expected_id:
            raise ValueError("manifest_id does not match manifest contents")

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "created_at": self.created_at,
            "window_start": self.window_start,
            "cutoff": self.cutoff,
            "tasks": [task.to_dict() for task in self.tasks],
            "planning_gaps": list(self.planning_gaps),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AcquisitionManifest":
        return cls(
            manifest_id=value["manifest_id"],
            created_at=value["created_at"],
            window_start=value["window_start"],
            cutoff=value["cutoff"],
            tasks=tuple(AcquisitionTask.from_dict(item) for item in value["tasks"]),
            planning_gaps=tuple(value.get("planning_gaps", [])),
        )


def build_platform_manifest(
    platforms: Iterable[str],
    seller_market: str,
    program: str,
    window_start: str,
    cutoff: str,
    created_at: str | None = None,
) -> AcquisitionManifest:
    require_datetime_offset(window_start, "window_start")
    require_datetime_offset(cutoff, "cutoff")
    created = created_at or datetime.now().astimezone().isoformat(timespec="seconds")
    tasks: list[AcquisitionTask] = []
    planning_gaps: list[dict[str, str]] = []
    seen_platforms: set[str] = set()
    for platform_name in platforms:
        config = get_platform(platform_name)
        if config is None:
            raise ValueError(f"unregistered platform: {platform_name}")
        if config.id in seen_platforms:
            continue
        seen_platforms.add(config.id)
        for source_type, reason in sorted(config.source_profile["known_gaps"].items()):
            planning_gaps.append({
                "platform": config.display_name,
                "seller_market": seller_market,
                "program": program,
                "source_type": source_type,
                "reason": reason,
            })
        for route in config.official_routes:
            source_type = str(route["source_type"])
            url = str(route["url"])
            route_markets = {str(market).casefold() for market in route.get("markets", ["*"])}
            market_matches = "*" in route_markets or seller_market.casefold() in route_markets
            route_is_conditional = route.get("verification_status") != "verified"
            task_id = stable_task_id(config.display_name, seller_market, program, source_type, url, window_start)
            tasks.append(AcquisitionTask(
                task_id=task_id,
                platform=config.display_name,
                seller_market=seller_market,
                program=program,
                source_type=source_type,
                url=url,
                window_start=window_start,
                requires_auth=source_type == "dashboard",
                route_verification_required=bool(route.get("verify_before_use")) or route_is_conditional or not market_matches,
                notes=(
                    f"Registered route {route.get('route_id', 'unknown')} for markets "
                    f"{', '.join(route.get('markets', ['*']))}; opening evidence is still required."
                    + (" Seller-market route mismatch must be resolved before citation." if not market_matches else "")
                ),
            ))
    tasks.sort(key=lambda item: (item.platform.casefold(), item.source_type, item.url))
    planning_gaps.sort(key=lambda item: (item["platform"].casefold(), item["source_type"]))
    digest = calculate_manifest_id(created, window_start, cutoff, tasks, planning_gaps)
    return AcquisitionManifest(
        manifest_id=digest,
        created_at=created,
        window_start=window_start,
        cutoff=cutoff,
        tasks=tuple(tasks),
        planning_gaps=tuple(planning_gaps),
    )
