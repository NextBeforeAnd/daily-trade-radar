"""Prioritize and cluster early trade signals without promoting them to verified events."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from .acquisition.models import require_datetime_offset, require_url
from .deduplication import canonical_scope, canonical_url, regulatory_identifiers, text_similarity
from .platforms import get_platform
from .snapshots.filesystem import atomic_write_text


SOURCE_TIERS = {
    "official_lead": 20,
    "platform_owned": 20,
    "government_affiliated": 18,
    "industry_association": 17,
    "carrier_or_port": 16,
    "trade_media": 14,
    "seller_forum": 8,
    "social": 5,
    "other": 3,
}
LEAD_SOURCE_TYPES = {
    "official_preview", "platform_notice", "industry_report", "logistics_notice",
    "trade_media", "seller_forum", "social_post", "other",
}


def _strings(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be an array of nonblank strings")
    return tuple(dict.fromkeys(item.strip() for item in value))


def _lead_id(value: dict[str, Any]) -> str:
    payload = "\n".join((
        canonical_url(value.get("source_url")),
        str(value.get("claim") or "").strip().casefold(),
        str(value.get("published_at") or ""),
    ))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class DiscoveryLead:
    lead_id: str
    source_title: str
    source_url: str
    source_name: str
    source_tier: str
    source_type: str
    published_at: str
    retrieved_at: str
    jurisdiction: str
    platform: str | None
    products: tuple[str, ...]
    hs_codes: tuple[str, ...]
    claim: str
    momentum_score: int = 0
    momentum_evidence: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{24}", self.lead_id):
            raise ValueError("lead_id must be a 24-character lowercase hexadecimal digest")
        for field in ("source_title", "source_name", "jurisdiction", "claim"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ValueError(f"{field} must be a nonblank string")
        require_url(self.source_url, "source_url")
        require_datetime_offset(self.published_at, "published_at")
        require_datetime_offset(self.retrieved_at, "retrieved_at")
        if datetime.fromisoformat(self.retrieved_at) < datetime.fromisoformat(self.published_at):
            raise ValueError("retrieved_at must not precede published_at")
        if self.source_tier not in SOURCE_TIERS:
            raise ValueError(f"invalid source_tier: {self.source_tier}")
        if self.source_type not in LEAD_SOURCE_TYPES:
            raise ValueError(f"invalid source_type: {self.source_type}")
        if isinstance(self.momentum_score, bool) or not isinstance(self.momentum_score, int) or not 0 <= self.momentum_score <= 5:
            raise ValueError("momentum_score must be an integer from 0 to 5")
        if self.momentum_score and (not isinstance(self.momentum_evidence, str) or not self.momentum_evidence.strip()):
            raise ValueError("positive momentum_score requires momentum_evidence")
        if self.platform is not None:
            if not isinstance(self.platform, str) or not self.platform.strip():
                raise ValueError("platform must be a nonblank string or null")
            config = get_platform(self.platform)
            if config is not None:
                object.__setattr__(self, "platform", config.display_name)
        for field in ("products", "hs_codes"):
            values = getattr(self, field)
            if not isinstance(values, tuple) or any(not isinstance(item, str) or not item.strip() for item in values):
                raise ValueError(f"{field} must contain nonblank strings")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["products"] = list(self.products)
        value["hs_codes"] = list(self.hs_codes)
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "DiscoveryLead":
        if not isinstance(value, dict):
            raise ValueError("lead must be an object")
        allowed = {
            "lead_id", "source_title", "source_url", "source_name", "source_tier", "source_type",
            "published_at", "retrieved_at", "jurisdiction", "platform", "products", "hs_codes",
            "claim", "momentum_score", "momentum_evidence",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"lead has unknown fields: {', '.join(sorted(unknown))}")
        normalized = dict(value)
        normalized["lead_id"] = normalized.get("lead_id") or _lead_id(normalized)
        normalized["products"] = _strings(normalized.get("products"), "products")
        normalized["hs_codes"] = _strings(normalized.get("hs_codes"), "hs_codes")
        normalized.setdefault("platform", None)
        normalized.setdefault("momentum_score", 0)
        normalized.setdefault("momentum_evidence", "")
        return cls(**normalized)


def _known(value: object) -> str | None:
    normalized = canonical_scope(value)
    return None if normalized in {"", "unknown", "global", "not stated", "n/a", "none"} else normalized


def _scope_conflict(left: DiscoveryLead, right: DiscoveryLead) -> bool:
    jurisdictions = (_known(left.jurisdiction), _known(right.jurisdiction))
    platforms = (_known(left.platform), _known(right.platform))
    return bool(
        jurisdictions[0] and jurisdictions[1] and jurisdictions[0] != jurisdictions[1]
        or platforms[0] and platforms[1] and platforms[0] != platforms[1]
    )


def _lead_event(lead: DiscoveryLead) -> dict[str, Any]:
    return {
        "title": lead.source_title,
        "summary": lead.claim,
        "source_title": lead.source_title,
    }


def lead_similarity(left: DiscoveryLead, right: DiscoveryLead) -> float:
    if _scope_conflict(left, right):
        return 0.0
    if canonical_url(left.source_url) == canonical_url(right.source_url):
        return 1.0
    left_ids = regulatory_identifiers(_lead_event(left))
    right_ids = regulatory_identifiers(_lead_event(right))
    if left_ids and right_ids and left_ids.intersection(right_ids):
        return 0.95
    claim = text_similarity(left.claim, right.claim) or 0.0
    title = text_similarity(left.source_title, right.source_title) or 0.0
    product_overlap = 0.0
    left_products = {item.casefold() for item in (*left.products, *left.hs_codes)}
    right_products = {item.casefold() for item in (*right.products, *right.hs_codes)}
    if left_products and right_products:
        product_overlap = len(left_products & right_products) / len(left_products | right_products)
    return 0.55 * claim + 0.30 * title + 0.15 * product_overlap


def cluster_leads(leads: list[DiscoveryLead], *, threshold: float = 0.62) -> list[list[DiscoveryLead]]:
    if not 0 < threshold <= 1:
        raise ValueError("cluster threshold must be greater than 0 and at most 1")
    parents = list(range(len(leads)))
    jurisdictions = [{value} if (value := _known(lead.jurisdiction)) else set() for lead in leads]
    platforms = [{value} if (value := _known(lead.platform)) else set() for lead in leads]

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root == right_root:
            return
        merged_jurisdictions = jurisdictions[left_root] | jurisdictions[right_root]
        merged_platforms = platforms[left_root] | platforms[right_root]
        if len(merged_jurisdictions) > 1 or len(merged_platforms) > 1:
            return
        parents[right_root] = left_root
        jurisdictions[left_root] = merged_jurisdictions
        platforms[left_root] = merged_platforms

    for left in range(len(leads)):
        for right in range(left + 1, len(leads)):
            if lead_similarity(leads[left], leads[right]) >= threshold:
                union(left, right)
    clusters: dict[int, list[DiscoveryLead]] = {}
    for index, lead in enumerate(leads):
        clusters.setdefault(find(index), []).append(lead)
    return [sorted(items, key=lambda item: item.lead_id) for items in clusters.values()]


def _recency_score(published_at: str, cutoff: datetime) -> int:
    age_hours = max(0.0, (cutoff - datetime.fromisoformat(published_at)).total_seconds() / 3600)
    if age_hours <= 24:
        return 25
    if age_hours <= 72:
        return 21
    if age_hours <= 7 * 24:
        return 16
    if age_hours <= 14 * 24:
        return 10
    if age_hours <= 30 * 24:
        return 5
    return 0


def _relevance_score(lead: DiscoveryLead, scope: dict[str, tuple[str, ...]]) -> int:
    score = 0
    regions = {canonical_scope(item) for item in scope["regions"]}
    platforms = {canonical_scope(item) for item in scope["platforms"]}
    products = {item.casefold() for item in (*scope["products"], *scope["hs_codes"], *scope["keywords"])}
    if not regions or canonical_scope(lead.jurisdiction) in regions:
        score += 8
    if lead.platform and (not platforms or canonical_scope(lead.platform) in platforms):
        score += 6
    lead_products = {item.casefold() for item in (*lead.products, *lead.hs_codes)}
    if products and lead_products.intersection(products):
        score += 6
    elif not products:
        score += 3
    return min(score, 20)


def _verification_queries(lead: DiscoveryLead) -> list[str]:
    subject = " ".join((*lead.products, *(f"HS {code}" for code in lead.hs_codes))) or lead.claim
    queries = [f"{lead.jurisdiction} {subject} official announcement rule effective date"]
    if lead.platform:
        queries.append(f"{lead.platform} {lead.jurisdiction} seller policy update {subject}")
    identifiers = sorted(regulatory_identifiers(_lead_event(lead)))
    queries.extend(f'"{identifier}" official' for identifier in identifiers)
    return list(dict.fromkeys(queries))


def prioritize_discovery(
    value: dict[str, Any], *, minimum_score: int = 45, cluster_threshold: float = 0.62,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("discovery input must be an object")
    allowed = {"cutoff", "scope", "leads"}
    if set(value) - allowed:
        raise ValueError(f"discovery input has unknown fields: {', '.join(sorted(set(value) - allowed))}")
    cutoff_value = value.get("cutoff")
    require_datetime_offset(cutoff_value, "cutoff")
    cutoff = datetime.fromisoformat(cutoff_value)
    if isinstance(minimum_score, bool) or not isinstance(minimum_score, int) or not 0 <= minimum_score <= 100:
        raise ValueError("minimum_score must be an integer from 0 to 100")
    raw_scope = value.get("scope", {})
    if not isinstance(raw_scope, dict):
        raise ValueError("scope must be an object")
    unknown_scope = set(raw_scope) - {"regions", "platforms", "products", "hs_codes", "keywords"}
    if unknown_scope:
        raise ValueError(f"scope has unknown fields: {', '.join(sorted(unknown_scope))}")
    scope = {field: _strings(raw_scope.get(field), f"scope.{field}") for field in ("regions", "platforms", "products", "hs_codes", "keywords")}
    raw_leads = value.get("leads")
    if not isinstance(raw_leads, list):
        raise ValueError("leads must be an array")
    leads = [DiscoveryLead.from_dict(item) for item in raw_leads]
    ids = [lead.lead_id for lead in leads]
    if len(ids) != len(set(ids)):
        raise ValueError("lead ids must be unique")
    if any(datetime.fromisoformat(lead.published_at) > cutoff for lead in leads):
        raise ValueError("lead published_at must not be after cutoff")

    ranked: list[dict[str, Any]] = []
    for cluster in cluster_leads(leads, threshold=cluster_threshold):
        domains = {urlsplit(lead.source_url).netloc.casefold() for lead in cluster}
        corroboration = 0 if len(domains) == 1 else 15 if len(domains) == 2 else 22 if len(domains) == 3 else 30
        best = max(cluster, key=lambda lead: (
            SOURCE_TIERS[lead.source_tier], _recency_score(lead.published_at, cutoff), lead.momentum_score,
        ))
        breakdown = {
            "recency": max(_recency_score(lead.published_at, cutoff) for lead in cluster),
            "cross_source_corroboration": corroboration,
            "business_relevance": max(_relevance_score(lead, scope) for lead in cluster),
            "source_quality": max(SOURCE_TIERS[lead.source_tier] for lead in cluster),
            "momentum": max(lead.momentum_score for lead in cluster),
        }
        score = sum(breakdown.values())
        cluster_id = hashlib.sha256("\n".join(sorted(lead.lead_id for lead in cluster)).encode("utf-8")).hexdigest()[:24]
        ranked.append({
            "cluster_id": cluster_id,
            "title": best.source_title,
            "claim": best.claim,
            "event_status": "unconfirmed",
            "risk_level": "watch",
            "promotion_eligible": False,
            "priority_score": score,
            "priority_breakdown": breakdown,
            "corroborating_domain_count": len(domains),
            "corroborated_lead": len(domains) >= 2,
            "jurisdiction": best.jurisdiction,
            "platform": best.platform,
            "products": list(dict.fromkeys(item for lead in cluster for item in lead.products)),
            "hs_codes": list(dict.fromkeys(item for lead in cluster for item in lead.hs_codes)),
            "lead_ids": [lead.lead_id for lead in cluster],
            "sources": [lead.to_dict() for lead in cluster],
            "verification_queries": _verification_queries(best),
            "missing_confirmation": "Open a direct primary or platform-owned source and verify scope, dates, and operative text.",
        })
    ranked.sort(key=lambda item: (-item["priority_score"], -item["corroborating_domain_count"], item["cluster_id"]))
    qualified = [item for item in ranked if item["priority_score"] >= minimum_score]
    outcome = "candidates_found" if qualified else "nothing_solid"
    return {
        "schema_version": "1.0",
        "cutoff": cutoff_value,
        "minimum_score": minimum_score,
        "cluster_threshold": cluster_threshold,
        "outcome": outcome,
        "scope": {field: list(items) for field, items in scope.items()},
        "candidate_count": len(qualified),
        "candidates": qualified,
        "weak_signal": ranked[0] if not qualified and ranked else None,
        "excluded_below_threshold": [item["cluster_id"] for item in ranked if item["priority_score"] < minimum_score],
        "evidence_boundary": "Priority scores rank verification work only; every cluster remains unconfirmed and watch-level.",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--minimum-score", type=int, default=45)
    parser.add_argument("--cluster-threshold", type=float, default=0.62)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        value = json.loads(args.input.read_text(encoding="utf-8"))
        result = prioritize_discovery(
            value, minimum_score=args.minimum_score, cluster_threshold=args.cluster_threshold,
        )
        content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
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
