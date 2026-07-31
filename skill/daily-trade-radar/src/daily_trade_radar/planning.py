"""Build and validate deterministic, evidence-aware research plans."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from .acquisition.models import require_datetime_offset
from .acquisition.manifest import AcquisitionManifest, build_platform_manifest
from .platforms import get_platform, load_registry
from .snapshots.filesystem import atomic_write_text


SCHEMA_VERSION = "1.0"
DEFAULT_REGIONS = ("China", "United States", "European Union")
TRACK_KINDS = {
    "official_updates",
    "effective_deadlines",
    "product_scope",
    "marketplace_policy",
    "discovery_leads",
}
FRESHNESS_MODES = {"reporting_window", "upcoming_30_days", "platform_lookback", "lead_lookback"}
EVIDENCE_REQUIREMENTS = {"primary", "platform_owned", "lead_only"}
SOURCE_TYPES = {
    "official_publication",
    "current_rule",
    "official_updates",
    "current_policy",
    "dashboard",
    "discovery_lead",
}
AUTHORITY_MAP = {
    "china": ("Ministry of Commerce", "General Administration of Customs", "State Taxation Administration", "SAMR"),
    "cn": ("Ministry of Commerce", "General Administration of Customs", "State Taxation Administration", "SAMR"),
    "united states": ("Federal Register", "BIS", "OFAC", "USTR", "CBP"),
    "usa": ("Federal Register", "BIS", "OFAC", "USTR", "CBP"),
    "us": ("Federal Register", "BIS", "OFAC", "USTR", "CBP"),
    "european union": ("European Commission", "EUR-Lex", "Access2Markets"),
    "eu": ("European Commission", "EUR-Lex", "Access2Markets"),
}


def _nonblank(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value.strip()


def _strings(value: object, field: str, *, default: Iterable[str] = ()) -> tuple[str, ...]:
    if value is None:
        value = list(default)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be an array of nonblank strings")
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        normalized = item.strip()
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return tuple(result)


def _validate_hs_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        digits = re.sub(r"[.\s-]", "", value)
        if not digits.isdigit() or not 4 <= len(digits) <= 10:
            raise ValueError(f"invalid HS code {value!r}; expected 4-10 digits")
        if digits not in normalized:
            normalized.append(digits)
    return tuple(normalized)


def _authorities(regions: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    for region in regions:
        mapped = AUTHORITY_MAP.get(region.casefold(), (f"{region} responsible trade and product authorities",))
        for authority in mapped:
            if authority not in values:
                values.append(authority)
    return tuple(values)


def _track_id(kind: str, identity: object) -> str:
    payload = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{kind.replace('_', '-')}-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def _plan_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class PlatformScope:
    platform: str
    seller_market: str
    program: str

    def __post_init__(self) -> None:
        config = get_platform(self.platform)
        if config is None:
            raise ValueError(f"unregistered platform: {self.platform}")
        object.__setattr__(self, "platform", config.display_name)
        _nonblank(self.seller_market, "seller_market")
        _nonblank(self.program, "program")

    @classmethod
    def from_value(cls, value: object) -> "PlatformScope":
        if isinstance(value, str):
            return cls(value, "unknown", "unknown")
        if not isinstance(value, dict):
            raise ValueError("platforms entries must be platform names or objects")
        unknown = set(value) - {"platform", "seller_market", "program"}
        if unknown:
            raise ValueError(f"platform scope has unknown fields: {', '.join(sorted(unknown))}")
        return cls(
            platform=_nonblank(value.get("platform"), "platform"),
            seller_market=_nonblank(value.get("seller_market", "unknown"), "seller_market"),
            program=_nonblank(value.get("program", "unknown"), "program"),
        )


@dataclass(frozen=True)
class ResearchTrack:
    track_id: str
    kind: str
    label: str
    weight: float
    freshness_mode: str
    evidence_requirement: str
    regions: tuple[str, ...]
    authorities: tuple[str, ...]
    products: tuple[str, ...]
    hs_codes: tuple[str, ...]
    platforms: tuple[str, ...]
    seller_markets: tuple[str, ...]
    programs: tuple[str, ...]
    source_types: tuple[str, ...]
    source_urls: tuple[str, ...]
    queries: tuple[str, ...]
    notes: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.track_id):
            raise ValueError("track_id must be lowercase kebab-case")
        if self.kind not in TRACK_KINDS:
            raise ValueError(f"invalid research track kind: {self.kind}")
        if self.freshness_mode not in FRESHNESS_MODES:
            raise ValueError(f"invalid freshness_mode: {self.freshness_mode}")
        if self.evidence_requirement not in EVIDENCE_REQUIREMENTS:
            raise ValueError(f"invalid evidence_requirement: {self.evidence_requirement}")
        if isinstance(self.weight, bool) or not isinstance(self.weight, (int, float)) or not 0 < self.weight <= 1:
            raise ValueError("track weight must be greater than 0 and at most 1")
        _nonblank(self.label, "label")
        if not self.queries:
            raise ValueError("research track must include at least one query")
        for field in (
            "regions", "authorities", "products", "hs_codes", "platforms",
            "seller_markets", "programs", "source_types", "source_urls", "queries",
        ):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{field} must contain nonblank strings")
        if any(source_type not in SOURCE_TYPES for source_type in self.source_types):
            raise ValueError("research track contains an invalid source type")
        for url in self.source_urls:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("source_urls must contain direct http(s) URLs")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for field in (
            "regions", "authorities", "products", "hs_codes", "platforms",
            "seller_markets", "programs", "source_types", "source_urls", "queries",
        ):
            value[field] = list(value[field])
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResearchTrack":
        expected = {field.name for field in cls.__dataclass_fields__.values()}
        if set(value) != expected:
            raise ValueError("research track fields do not match schema")
        converted = dict(value)
        for field in (
            "regions", "authorities", "products", "hs_codes", "platforms",
            "seller_markets", "programs", "source_types", "source_urls", "queries",
        ):
            if not isinstance(converted[field], list):
                raise ValueError(f"{field} must be an array")
            converted[field] = tuple(converted[field])
        return cls(**converted)


@dataclass(frozen=True)
class ResearchPlan:
    schema_version: str
    plan_id: str
    created_at: str
    window_start: str
    cutoff: str
    deadline_end: str
    language: str
    scope: dict[str, Any]
    tracks: tuple[ResearchTrack, ...]
    manifest_requests: tuple[dict[str, str], ...]

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported research plan schema_version: {self.schema_version}")
        for field in ("created_at", "window_start", "cutoff", "deadline_end"):
            require_datetime_offset(getattr(self, field), field)
        start = datetime.fromisoformat(self.window_start)
        cutoff = datetime.fromisoformat(self.cutoff)
        deadline = datetime.fromisoformat(self.deadline_end)
        if start > cutoff:
            raise ValueError("window_start must not be after cutoff")
        if deadline <= cutoff:
            raise ValueError("deadline_end must be after cutoff")
        _nonblank(self.language, "language")
        if not isinstance(self.scope, dict):
            raise ValueError("scope must be an object")
        if not self.tracks:
            raise ValueError("research plan must contain tracks")
        ids = [track.track_id for track in self.tracks]
        if len(ids) != len(set(ids)):
            raise ValueError("research track ids must be unique")
        kinds = {track.kind for track in self.tracks}
        required = {"official_updates", "effective_deadlines", "discovery_leads"}
        if not required <= kinds:
            raise ValueError(f"research plan is missing required tracks: {', '.join(sorted(required - kinds))}")
        for track in self.tracks:
            expected = {
                "official_updates": "primary",
                "effective_deadlines": "primary",
                "product_scope": "primary",
                "marketplace_policy": "platform_owned",
                "discovery_leads": "lead_only",
            }[track.kind]
            if track.evidence_requirement != expected:
                raise ValueError(f"{track.kind} track must require {expected} evidence")
        platform_scope = self.scope.get("platforms", [])
        if not isinstance(platform_scope, list):
            raise ValueError("scope.platforms must be an array")
        expected_platforms = {item["platform"] for item in platform_scope if isinstance(item, dict)}
        planned_platforms = {platform for track in self.tracks if track.kind == "marketplace_policy" for platform in track.platforms}
        if expected_platforms != planned_platforms:
            raise ValueError("marketplace policy tracks must exactly cover scoped platforms")
        if (self.scope.get("products") or self.scope.get("hs_codes")) and "product_scope" not in kinds:
            raise ValueError("product or HS-code scope requires a product_scope track")
        for request in self.manifest_requests:
            if set(request) != {"platform", "seller_market", "program", "window_start", "cutoff"}:
                raise ValueError("manifest request fields do not match schema")
            for field, value in request.items():
                _nonblank(value, f"manifest_requests.{field}")
            require_datetime_offset(request["window_start"], "manifest_requests.window_start")
            require_datetime_offset(request["cutoff"], "manifest_requests.cutoff")
            if (datetime.fromisoformat(request["cutoff"]) - datetime.fromisoformat(request["window_start"])).total_seconds() < 7 * 86400:
                raise ValueError("platform manifest request window must be at least 7 days")
        expected_id = _plan_id(self._identity_payload())
        if self.plan_id != expected_id:
            raise ValueError("plan_id does not match research plan contents")

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "created_at": self.created_at,
            "window_start": self.window_start,
            "cutoff": self.cutoff,
            "deadline_end": self.deadline_end,
            "language": self.language,
            "scope": self.scope,
            "tracks": [track.to_dict() for track in self.tracks],
            "manifest_requests": list(self.manifest_requests),
        }

    def to_dict(self) -> dict[str, Any]:
        return {"plan_id": self.plan_id, **self._identity_payload()}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ResearchPlan":
        expected = {
            "schema_version", "plan_id", "created_at", "window_start", "cutoff",
            "deadline_end", "language", "scope", "tracks", "manifest_requests",
        }
        if set(value) != expected:
            raise ValueError("research plan fields do not match schema")
        if not isinstance(value["tracks"], list) or not isinstance(value["manifest_requests"], list):
            raise ValueError("tracks and manifest_requests must be arrays")
        return cls(
            schema_version=value["schema_version"],
            plan_id=value["plan_id"],
            created_at=value["created_at"],
            window_start=value["window_start"],
            cutoff=value["cutoff"],
            deadline_end=value["deadline_end"],
            language=value["language"],
            scope=value["scope"],
            tracks=tuple(ResearchTrack.from_dict(item) for item in value["tracks"]),
            manifest_requests=tuple(value["manifest_requests"]),
        )


def _subject_terms(products: tuple[str, ...], hs_codes: tuple[str, ...], keywords: tuple[str, ...]) -> str:
    values = (*products, *(f"HS {code}" for code in hs_codes), *keywords)
    return " ".join(values) if values else "trade customs sanctions tariffs product compliance"


def build_research_plan(scope_value: dict[str, Any], *, now: datetime | None = None) -> ResearchPlan:
    if not isinstance(scope_value, dict):
        raise ValueError("scope input must be a JSON object")
    allowed = {
        "created_at", "window_start", "cutoff", "deadline_end", "language", "regions",
        "products", "hs_codes", "keywords", "priority_themes", "platforms",
    }
    unknown = set(scope_value) - allowed
    if unknown:
        raise ValueError(f"scope input has unknown fields: {', '.join(sorted(unknown))}")
    current = now or datetime.now().astimezone()
    if current.tzinfo is None or current.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    cutoff = scope_value.get("cutoff") or current.isoformat(timespec="seconds")
    require_datetime_offset(cutoff, "cutoff")
    cutoff_dt = datetime.fromisoformat(cutoff)
    window_start = scope_value.get("window_start") or (cutoff_dt - timedelta(hours=24)).isoformat(timespec="seconds")
    deadline_end = scope_value.get("deadline_end") or (cutoff_dt + timedelta(days=30)).isoformat(timespec="seconds")
    created_at = scope_value.get("created_at") or current.isoformat(timespec="seconds")
    for field, value in (("window_start", window_start), ("deadline_end", deadline_end), ("created_at", created_at)):
        require_datetime_offset(value, field)
    regions = _strings(scope_value.get("regions"), "regions", default=DEFAULT_REGIONS)
    if not regions:
        raise ValueError("regions must not be empty")
    products = _strings(scope_value.get("products"), "products")
    hs_codes = _validate_hs_codes(_strings(scope_value.get("hs_codes"), "hs_codes"))
    keywords = _strings(scope_value.get("keywords"), "keywords")
    priority_themes = _strings(scope_value.get("priority_themes"), "priority_themes")
    raw_platforms = scope_value.get("platforms")
    if raw_platforms is None and "platforms" not in scope_value:
        raw_platforms = [load_registry()[key].display_name for key in sorted(load_registry())]
    if not isinstance(raw_platforms, list):
        raise ValueError("platforms must be an array")
    platform_scopes: list[PlatformScope] = []
    seen_platforms: set[str] = set()
    for raw in raw_platforms:
        platform = PlatformScope.from_value(raw)
        if platform.platform.casefold() in seen_platforms:
            raise ValueError(f"duplicate platform scope: {platform.platform}")
        seen_platforms.add(platform.platform.casefold())
        platform_scopes.append(platform)
    language = _nonblank(scope_value.get("language", "zh-CN"), "language")
    subject = _subject_terms(products, hs_codes, (*keywords, *priority_themes))
    authorities = _authorities(regions)
    tracks: list[ResearchTrack] = []

    official_identity = {"regions": regions, "subject": subject, "window": window_start}
    tracks.append(ResearchTrack(
        track_id=_track_id("official_updates", official_identity), kind="official_updates",
        label="Official publications inside the reporting window", weight=1.0,
        freshness_mode="reporting_window", evidence_requirement="primary",
        regions=regions, authorities=authorities, products=products, hs_codes=hs_codes,
        platforms=(), seller_markets=(), programs=(),
        source_types=("official_publication",), source_urls=(),
        queries=tuple(f"{authority} {subject} announcement rule consultation published" for authority in authorities),
        notes="Open and read every cited primary publication; record publication and effective dates separately.",
    ))
    deadline_identity = {"regions": regions, "subject": subject, "deadline_end": deadline_end}
    tracks.append(ResearchTrack(
        track_id=_track_id("effective_deadlines", deadline_identity), kind="effective_deadlines",
        label="Rules taking effect, expiring, or reaching a deadline", weight=1.0,
        freshness_mode="upcoming_30_days", evidence_requirement="primary",
        regions=regions, authorities=authorities, products=products, hs_codes=hs_codes,
        platforms=(), seller_markets=(), programs=(),
        source_types=("current_rule", "official_publication"), source_urls=(),
        queries=tuple(f"{authority} {subject} effective deadline expires consultation {deadline_end[:10]}" for authority in authorities),
        notes="Verify the exact year, timezone, scope, and operative text on the current official rule.",
    ))
    if products or hs_codes:
        identity = {"products": products, "hs_codes": hs_codes, "regions": regions}
        tracks.append(ResearchTrack(
            track_id=_track_id("product_scope", identity), kind="product_scope",
            label="Product and HS-code applicability", weight=0.9,
            freshness_mode="reporting_window", evidence_requirement="primary",
            regions=regions, authorities=authorities, products=products, hs_codes=hs_codes,
            platforms=(), seller_markets=(), programs=(),
            source_types=("official_publication", "current_rule"), source_urls=(),
            queries=tuple(f"{region} {subject} customs classification product requirement" for region in regions),
            notes="Do not infer applicability from a product name alone; verify codes, exclusions, and jurisdiction.",
        ))

    platform_window = min(datetime.fromisoformat(window_start), cutoff_dt - timedelta(days=7)).isoformat(timespec="seconds")
    manifest_requests: list[dict[str, str]] = []
    for platform_scope in platform_scopes:
        config = get_platform(platform_scope.platform)
        assert config is not None
        routes = tuple(str(route["url"]) for route in config.official_routes)
        policy_terms = " ".join(config.policy_areas)
        identity = asdict(platform_scope)
        tracks.append(ResearchTrack(
            track_id=_track_id("marketplace_policy", identity), kind="marketplace_policy",
            label=f"{config.display_name} policy monitoring", weight=1.0,
            freshness_mode="platform_lookback", evidence_requirement="platform_owned",
            regions=(), authorities=(), products=products, hs_codes=hs_codes,
            platforms=(config.display_name,), seller_markets=(platform_scope.seller_market,),
            programs=(platform_scope.program,),
            source_types=tuple(sorted({str(route["source_type"]) for route in config.official_routes})),
            source_urls=routes,
            queries=(
                f"{config.display_name} {platform_scope.seller_market} {platform_scope.program} seller policy update",
                f"{config.display_name} {platform_scope.seller_market} {policy_terms}",
            ),
            notes="Use registered routes, create acquisition receipts, and require platform-owned confirmation before promotion.",
        ))
        manifest_requests.append({
            "platform": config.display_name,
            "seller_market": platform_scope.seller_market,
            "program": platform_scope.program,
            "window_start": platform_window,
            "cutoff": cutoff,
        })

    discovery_identity = {"regions": regions, "subject": subject, "platforms": [item.platform for item in platform_scopes]}
    tracks.append(ResearchTrack(
        track_id=_track_id("discovery_leads", discovery_identity), kind="discovery_leads",
        label="Secondary-source leads requiring primary confirmation", weight=0.4,
        freshness_mode="lead_lookback", evidence_requirement="lead_only",
        regions=regions, authorities=(), products=products, hs_codes=hs_codes,
        platforms=tuple(item.platform for item in platform_scopes),
        seller_markets=tuple(item.seller_market for item in platform_scopes),
        programs=tuple(item.program for item in platform_scopes),
        source_types=("discovery_lead",), source_urls=(),
        queries=tuple(f"{region} {subject} trade compliance logistics seller update" for region in regions),
        notes="Leads may enter only the unconfirmed watchlist until a primary or platform-owned source is opened.",
    ))

    normalized_scope = {
        "regions": list(regions), "products": list(products), "hs_codes": list(hs_codes),
        "keywords": list(keywords), "priority_themes": list(priority_themes),
        "platforms": [asdict(item) for item in platform_scopes],
    }
    identity_payload = {
        "schema_version": SCHEMA_VERSION, "created_at": created_at, "window_start": window_start,
        "cutoff": cutoff, "deadline_end": deadline_end, "language": language,
        "scope": normalized_scope, "tracks": [track.to_dict() for track in tracks],
        "manifest_requests": manifest_requests,
    }
    return ResearchPlan(
        schema_version=SCHEMA_VERSION, plan_id=_plan_id(identity_payload), created_at=created_at,
        window_start=window_start, cutoff=cutoff, deadline_end=deadline_end, language=language,
        scope=normalized_scope, tracks=tuple(tracks), manifest_requests=tuple(manifest_requests),
    )


def build_acquisition_manifests(plan: ResearchPlan) -> tuple[AcquisitionManifest, ...]:
    """Materialize the plan's marketplace requests through the existing registry workflow."""
    return tuple(
        build_platform_manifest(
            [request["platform"]], request["seller_market"], request["program"],
            request["window_start"], request["cutoff"], plan.created_at,
        )
        for request in plan.manifest_requests
    )


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return normalized or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def write_acquisition_manifests(plan: ResearchPlan, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for manifest, request in zip(build_acquisition_manifests(plan), plan.manifest_requests):
        name = "-".join(_slug(request[field]) for field in ("platform", "seller_market", "program"))
        path = directory / f"{name}.manifest.json"
        atomic_write_text(path, json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")
        paths.append(path)
    return paths


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scope", type=Path, help="build a plan from a scope JSON object")
    mode.add_argument("--validate", type=Path, help="validate an existing research plan")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest-dir", type=Path, help="also write registry-driven marketplace manifests")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        plan = build_research_plan(_load(args.scope)) if args.scope else ResearchPlan.from_dict(_load(args.validate))
        if args.manifest_dir:
            write_acquisition_manifests(plan, args.manifest_dir)
        content = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2) + "\n"
        if args.output:
            atomic_write_text(args.output, content)
        else:
            print(content, end="")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
