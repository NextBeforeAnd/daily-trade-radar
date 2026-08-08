"""Match validated radar events to an organization's HS/SKU catalog."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from .snapshots.filesystem import atomic_write_text


def _strings(value: object, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field} must be an array of nonblank strings")
    return list(dict.fromkeys(item.strip() for item in value))


def _hs(value: str) -> str:
    digits = re.sub(r"[.\s-]", "", value)
    if not digits.isdigit() or not 4 <= len(digits) <= 10:
        raise ValueError(f"invalid HS code {value!r}; expected 4-10 digits")
    return digits


def load_catalog(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != "1.0":
        raise ValueError("catalog must be a version 1.0 JSON object")
    organization = value.get("organization")
    if not isinstance(organization, str) or not organization.strip():
        raise ValueError("catalog.organization must be nonblank")
    items = value.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("catalog.items must be a non-empty array")
    normalized_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError(f"catalog.items[{index}] must be an object")
        allowed = {"sku", "name", "hs_codes", "keywords", "markets", "platforms"}
        unknown = set(item) - allowed
        if unknown:
            raise ValueError(f"catalog.items[{index}] has unknown fields: {', '.join(sorted(unknown))}")
        sku = item.get("sku")
        name = item.get("name")
        if not isinstance(sku, str) or not sku.strip() or not isinstance(name, str) or not name.strip():
            raise ValueError(f"catalog.items[{index}] requires nonblank sku and name")
        normalized_items.append({
            "sku": sku.strip(), "name": name.strip(),
            "hs_codes": [_hs(code) for code in _strings(item.get("hs_codes"), f"catalog.items[{index}].hs_codes")],
            "keywords": _strings(item.get("keywords"), f"catalog.items[{index}].keywords"),
            "markets": _strings(item.get("markets"), f"catalog.items[{index}].markets"),
            "platforms": _strings(item.get("platforms"), f"catalog.items[{index}].platforms"),
        })
    return {"schema_version": "1.0", "organization": organization.strip(), "items": normalized_items}


def _norm(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").casefold()).strip()


def _same_scope(left: str, right: str) -> bool:
    aliases = {
        "us": "united states", "usa": "united states", "美国": "united states",
        "eu": "european union", "欧盟": "european union",
        "cn": "china", "中国": "china", "中华人民共和国": "china",
        "uk": "united kingdom", "英国": "united kingdom",
    }
    return aliases.get(_norm(left), _norm(left)) == aliases.get(_norm(right), _norm(right))


def _event_hs_codes(event: dict[str, Any]) -> set[str]:
    values = event.get("hs_codes", [])
    codes = {_hs(item) for item in values if isinstance(item, str)} if isinstance(values, list) else set()
    text = " ".join(str(event.get(field, "")) for field in ("title", "summary", "impact", "rationale"))
    text += " " + " ".join(str(item) for item in event.get("products_or_channels", []))
    codes.update(re.sub(r"[.\s-]", "", match) for match in re.findall(r"(?i)\bHS(?:\s+code)?\s*[:：]?\s*([0-9][0-9.\s-]{2,12}[0-9])", text))
    return {code for code in codes if code.isdigit() and 4 <= len(code) <= 10}


def _hs_overlap(left: str, right: str) -> bool:
    return left.startswith(right) or right.startswith(left)


def match_report(report: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(report)
    for event in result.get("events", []):
        if not isinstance(event, dict):
            continue
        event_text = _norm(" ".join(
            [str(event.get(field, "")) for field in ("title", "summary", "impact", "rationale")]
            + [str(item) for item in event.get("products_or_channels", [])]
        ))
        event_codes = _event_hs_codes(event)
        jurisdiction = str(event.get("jurisdiction", ""))
        policy = event.get("platform_policy") if isinstance(event.get("platform_policy"), dict) else {}
        event_platform = str(policy.get("platform", ""))
        matches: list[dict[str, Any]] = []
        scope_only = False
        for item in catalog["items"]:
            markets = item["markets"]
            platforms = item["platforms"]
            market_match = not markets or any(_same_scope(jurisdiction, market) for market in markets)
            platform_match = not platforms or any(_same_scope(event_platform, platform) for platform in platforms)
            if not market_match or not platform_match:
                continue
            scope_only = True
            hs_matches = sorted({code for code in item["hs_codes"] for event_code in event_codes if _hs_overlap(code, event_code)})
            terms = [item["name"], *item["keywords"]]
            term_matches = sorted({term for term in terms if len(_norm(term)) >= 3 and _norm(term) in event_text})
            if hs_matches or term_matches:
                basis = (["hs_prefix"] if hs_matches else []) + (["product_keyword"] if term_matches else [])
                matches.append({
                    "sku": item["sku"], "name": item["name"], "basis": basis,
                    "matched_hs_codes": hs_matches, "matched_terms": term_matches,
                })
        status = "matched" if matches else "needs_review" if scope_only else "no_match"
        event["applicability"] = {
            "organization": catalog["organization"], "status": status,
            "matched_items": matches,
            "reason": (
                "Matched by an HS-code prefix or catalog product term."
                if matches else
                "Market/platform scope overlaps, but no product or HS signal was strong enough."
                if scope_only else
                "No catalog market/platform scope matched this event."
            ),
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        output = match_report(report, load_catalog(args.catalog))
        atomic_write_text(args.output, json.dumps(output, ensure_ascii=False, indent=2) + "\n")
        print(f"WROTE: {args.output}")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
