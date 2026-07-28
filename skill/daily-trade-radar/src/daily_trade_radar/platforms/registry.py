"""Load and query marketplace playbooks from bundled JSON configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any, Iterable


DATA_DIR = Path(__file__).resolve().parent / "data"
REQUIRED_FIELDS = {
    "id",
    "display_name",
    "aliases",
    "seller_markets",
    "programs",
    "official_routes",
    "dashboard_checks",
    "applicability_dimensions",
    "policy_areas",
    "notes",
    "source_profile",
}
ROUTE_TYPES = {"official_updates", "current_policy", "dashboard"}
ROUTE_ACCESS = {"public", "authenticated", "mixed"}
ROUTE_ROLES = {"discovery", "current_rule", "account_specific"}
ROUTE_VERIFICATION = {"verified", "conditional"}
ROLE_FOR_SOURCE_TYPE = {
    "official_updates": "discovery",
    "current_policy": "current_rule",
    "dashboard": "account_specific",
}


def normalize_name(value: object) -> str:
    return " ".join(re.findall(r"[\w]+", str(value or "").casefold(), flags=re.UNICODE))


@dataclass(frozen=True)
class PlatformConfig:
    id: str
    display_name: str
    aliases: tuple[str, ...]
    seller_markets: tuple[str, ...]
    programs: tuple[str, ...]
    official_routes: tuple[dict[str, Any], ...]
    dashboard_checks: tuple[str, ...]
    applicability_dimensions: tuple[str, ...]
    policy_areas: tuple[str, ...]
    notes: tuple[str, ...]
    source_profile: dict[str, Any]

    @property
    def normalized_names(self) -> frozenset[str]:
        return frozenset(normalize_name(value) for value in (self.id, self.display_name, *self.aliases))


def _string_tuple(data: dict[str, Any], field: str, path: Path) -> tuple[str, ...]:
    value = data.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{path}: {field} must be an array of nonblank strings")
    return tuple(item.strip() for item in value)


def _load_config(path: Path) -> PlatformConfig:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: root must be an object")
    missing = REQUIRED_FIELDS - data.keys()
    if missing:
        raise ValueError(f"{path}: missing {', '.join(sorted(missing))}")
    platform_id = data.get("id")
    display_name = data.get("display_name")
    if not isinstance(platform_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", platform_id):
        raise ValueError(f"{path}: id must be a lowercase kebab-case identifier")
    if not isinstance(display_name, str) or not display_name.strip():
        raise ValueError(f"{path}: display_name must be a nonblank string")
    routes = data.get("official_routes")
    if not isinstance(routes, list) or not routes:
        raise ValueError(f"{path}: official_routes must be a non-empty array")
    normalized_routes: list[dict[str, Any]] = []
    route_ids: set[str] = set()
    for index, route in enumerate(routes):
        if not isinstance(route, dict):
            raise ValueError(f"{path}: official_routes[{index}] must be an object")
        route_type = route.get("source_type")
        url = route.get("url")
        if route_type not in ROUTE_TYPES:
            raise ValueError(f"{path}: official_routes[{index}].source_type is invalid")
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            raise ValueError(f"{path}: official_routes[{index}].url must be http(s)")
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", route_id):
            raise ValueError(f"{path}: official_routes[{index}].route_id must be lowercase kebab-case")
        if route_id in route_ids:
            raise ValueError(f"{path}: duplicate route_id {route_id}")
        route_ids.add(route_id)
        if route.get("access") not in ROUTE_ACCESS:
            raise ValueError(f"{path}: official_routes[{index}].access is invalid")
        if route.get("evidence_role") not in ROUTE_ROLES:
            raise ValueError(f"{path}: official_routes[{index}].evidence_role is invalid")
        if route.get("evidence_role") != ROLE_FOR_SOURCE_TYPE[route_type]:
            raise ValueError(f"{path}: official_routes[{index}].evidence_role does not match source_type")
        if not isinstance(route.get("market_specific"), bool):
            raise ValueError(f"{path}: official_routes[{index}].market_specific must be boolean")
        markets = route.get("markets")
        if not isinstance(markets, list) or not markets or any(
            not isinstance(market, str) or not market.strip() for market in markets
        ):
            raise ValueError(f"{path}: official_routes[{index}].markets must be nonblank strings")
        verification = route.get("verification_status")
        if verification not in ROUTE_VERIFICATION:
            raise ValueError(f"{path}: official_routes[{index}].verification_status is invalid")
        verified_on = route.get("last_verified_on")
        if verification == "verified":
            try:
                date.fromisoformat(verified_on)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path}: official_routes[{index}].last_verified_on must be YYYY-MM-DD") from exc
        elif verified_on is not None:
            raise ValueError(f"{path}: conditional routes must use null last_verified_on")
        if verification == "conditional" and route.get("verify_before_use") is not True:
            raise ValueError(f"{path}: conditional routes require verify_before_use=true")
        normalized_routes.append(dict(route))
    source_profile = data.get("source_profile")
    if not isinstance(source_profile, dict):
        raise ValueError(f"{path}: source_profile must be an object")
    expected_types = source_profile.get("expected_source_types")
    if not isinstance(expected_types, list) or set(expected_types) != ROUTE_TYPES:
        raise ValueError(f"{path}: source_profile.expected_source_types must contain all source types")
    known_gaps = source_profile.get("known_gaps")
    if not isinstance(known_gaps, dict) or any(
        key not in ROUTE_TYPES or not isinstance(reason, str) or not reason.strip()
        for key, reason in known_gaps.items()
    ):
        raise ValueError(f"{path}: source_profile.known_gaps is invalid")
    actual_types = {route["source_type"] for route in normalized_routes}
    for route_type in ROUTE_TYPES:
        if route_type not in actual_types and route_type not in known_gaps:
            raise ValueError(f"{path}: missing route or declared source gap for {route_type}")
        if route_type in actual_types and route_type in known_gaps:
            raise ValueError(f"{path}: {route_type} cannot be both configured and a known gap")
    return PlatformConfig(
        id=platform_id,
        display_name=display_name.strip(),
        aliases=_string_tuple(data, "aliases", path),
        seller_markets=_string_tuple(data, "seller_markets", path),
        programs=_string_tuple(data, "programs", path),
        official_routes=tuple(normalized_routes),
        dashboard_checks=_string_tuple(data, "dashboard_checks", path),
        applicability_dimensions=_string_tuple(data, "applicability_dimensions", path),
        policy_areas=_string_tuple(data, "policy_areas", path),
        notes=_string_tuple(data, "notes", path),
        source_profile={
            "expected_source_types": tuple(expected_types),
            "known_gaps": dict(known_gaps),
        },
    )


def source_depth(config: PlatformConfig) -> dict[str, Any]:
    actual_types = {route["source_type"] for route in config.official_routes}
    missing_types = sorted(ROUTE_TYPES - actual_types)
    verified_public = sum(
        route["verification_status"] == "verified" and route["access"] in {"public", "mixed"}
        for route in config.official_routes
    )
    if not missing_types and verified_public:
        status = "full"
    elif len(actual_types) >= 2:
        status = "hybrid"
    else:
        status = "constrained"
    return {
        "status": status,
        "route_count": len(config.official_routes),
        "configured_source_types": sorted(actual_types),
        "missing_source_types": missing_types,
        "verified_public_route_count": verified_public,
        "conditional_route_count": sum(
            route["verification_status"] == "conditional" for route in config.official_routes
        ),
        "declared_gaps": dict(config.source_profile["known_gaps"]),
    }


@lru_cache(maxsize=1)
def load_registry() -> dict[str, PlatformConfig]:
    registry: dict[str, PlatformConfig] = {}
    aliases: dict[str, str] = {}
    paths = sorted(DATA_DIR.glob("*.json"))
    if not paths:
        raise ValueError(f"no platform configuration found in {DATA_DIR}")
    for path in paths:
        config = _load_config(path)
        if config.id in registry:
            raise ValueError(f"duplicate platform id: {config.id}")
        for name in config.normalized_names:
            owner = aliases.get(name)
            if owner and owner != config.id:
                raise ValueError(f"platform alias {name!r} belongs to both {owner} and {config.id}")
            aliases[name] = config.id
        registry[config.id] = config
    return registry


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    return {
        name: config.id
        for config in load_registry().values()
        for name in config.normalized_names
    }


def canonical_platform_id(value: object) -> str | None:
    return _alias_index().get(normalize_name(value))


def get_platform(value: object) -> PlatformConfig | None:
    platform_id = canonical_platform_id(value)
    return load_registry().get(platform_id) if platform_id else None


def _contains_alias(text: str, alias: str) -> bool:
    if not alias:
        return False
    if re.fullmatch(r"[a-z0-9 ]+", alias):
        return re.search(rf"(?<!\w){re.escape(alias)}(?!\w)", text) is not None
    return alias in text


def platforms_in_scope(scope: Iterable[object]) -> list[PlatformConfig]:
    text = normalize_name(" ".join(str(item) for item in scope if isinstance(item, str)))
    found = {
        config.id: config
        for config in load_registry().values()
        if any(_contains_alias(text, alias) for alias in config.normalized_names)
    }
    return [found[key] for key in sorted(found)]
