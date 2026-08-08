"""Load and validate bundled government-source configurations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable
from urllib.parse import urlsplit


DATA_DIR = Path(__file__).with_name("data")
ALLOWED_SOURCE_TYPES = {"official_publication", "current_rule"}


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonblank string")
    return value.strip()


@dataclass(frozen=True)
class OfficialRoute:
    label: str
    url: str
    source_type: str
    topics: tuple[str, ...]

    @classmethod
    def from_dict(cls, value: object, source_id: str) -> "OfficialRoute":
        if not isinstance(value, dict):
            raise ValueError(f"{source_id}.routes entries must be objects")
        expected = {"label", "url", "source_type", "topics"}
        if set(value) != expected:
            raise ValueError(f"{source_id}.routes fields do not match schema")
        url = _text(value["url"], f"{source_id}.routes.url")
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError(f"{source_id}.routes.url must be a direct https URL")
        source_type = _text(value["source_type"], f"{source_id}.routes.source_type")
        if source_type not in ALLOWED_SOURCE_TYPES:
            raise ValueError(f"{source_id}.routes.source_type is unsupported")
        topics = value["topics"]
        if not isinstance(topics, list) or any(not isinstance(item, str) or not item.strip() for item in topics):
            raise ValueError(f"{source_id}.routes.topics must be nonblank strings")
        return cls(
            label=_text(value["label"], f"{source_id}.routes.label"),
            url=url,
            source_type=source_type,
            topics=tuple(item.strip() for item in topics),
        )


@dataclass(frozen=True)
class OfficialSource:
    id: str
    display_name: str
    jurisdiction: str
    authority: str
    aliases: tuple[str, ...]
    routes: tuple[OfficialRoute, ...]

    @classmethod
    def from_dict(cls, value: object) -> "OfficialSource":
        if not isinstance(value, dict):
            raise ValueError("official source entry must be an object")
        expected = {"id", "display_name", "jurisdiction", "authority", "aliases", "routes"}
        if set(value) != expected:
            raise ValueError("official source fields do not match schema")
        source_id = _text(value["id"], "id")
        aliases = value["aliases"]
        if not isinstance(aliases, list) or any(not isinstance(item, str) or not item.strip() for item in aliases):
            raise ValueError(f"{source_id}.aliases must be nonblank strings")
        routes = value["routes"]
        if not isinstance(routes, list) or not routes:
            raise ValueError(f"{source_id}.routes must be a non-empty array")
        return cls(
            id=source_id,
            display_name=_text(value["display_name"], f"{source_id}.display_name"),
            jurisdiction=_text(value["jurisdiction"], f"{source_id}.jurisdiction"),
            authority=_text(value["authority"], f"{source_id}.authority"),
            aliases=tuple(item.strip() for item in aliases),
            routes=tuple(OfficialRoute.from_dict(item, source_id) for item in routes),
        )


def load_registry(directory: Path = DATA_DIR) -> dict[str, OfficialSource]:
    registry: dict[str, OfficialSource] = {}
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise ValueError(f"{path}: expected a sources array")
        for entry in entries:
            source = OfficialSource.from_dict(entry)
            if source.id in registry:
                raise ValueError(f"duplicate official source id: {source.id}")
            registry[source.id] = source
    return registry


def sources_for_regions(regions: Iterable[str]) -> tuple[OfficialSource, ...]:
    wanted = {str(region).strip().casefold() for region in regions}
    selected: list[OfficialSource] = []
    for source in load_registry().values():
        identities = {source.jurisdiction.casefold(), *(alias.casefold() for alias in source.aliases)}
        if identities & wanted:
            selected.append(source)
    return tuple(selected)
