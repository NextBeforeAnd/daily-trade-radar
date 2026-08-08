"""Generate a conservative, validation-ready platform registry template."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from ..snapshots.filesystem import atomic_write_text
from .registry import ROLE_FOR_SOURCE_TYPE, ROUTE_TYPES, _load_config


def build_platform_template(
    *, platform_id: str, display_name: str, url: str, source_type: str,
    aliases: list[str], markets: list[str], programs: list[str], access: str | None = None,
) -> dict:
    route_access = access or ("authenticated" if source_type == "dashboard" else "public")
    known_gaps = {
        route_type: f"No verified {route_type} route is configured; verify an official entry before operational use."
        for route_type in sorted(ROUTE_TYPES - {source_type})
    }
    return {
        "id": platform_id,
        "display_name": display_name,
        "aliases": list(dict.fromkeys([platform_id, display_name, *aliases])),
        "seller_markets": list(dict.fromkeys(markets or ["Global"])),
        "programs": list(dict.fromkeys(programs or ["marketplace seller"])),
        "official_routes": [{
            "route_id": "starter-route",
            "source_type": source_type,
            "url": url,
            "market_specific": bool(markets and markets != ["Global"]),
            "markets": list(dict.fromkeys(markets or ["*"])),
            "access": route_access,
            "evidence_role": ROLE_FOR_SOURCE_TYPE[source_type],
            "verification_status": "conditional",
            "last_verified_on": None,
            "verify_before_use": True,
        }],
        "source_profile": {
            "expected_source_types": sorted(ROUTE_TYPES),
            "known_gaps": known_gaps,
        },
        "dashboard_checks": ["Policy inbox", "Account health", "Logistics", "Settlement"],
        "applicability_dimensions": ["seller_market", "program", "product_or_category"],
        "policy_areas": ["listing_product_compliance", "account_health_enforcement", "other"],
        "notes": [
            "Generated scaffold only; open and verify every official route before changing verification_status.",
            "Do not infer market-wide applicability from one seller-account notice.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--source-type", choices=tuple(sorted(ROUTE_TYPES)), default="official_updates")
    parser.add_argument("--access", choices=("public", "authenticated", "mixed"))
    parser.add_argument("--alias", action="append", default=[])
    parser.add_argument("--market", action="append", default=[])
    parser.add_argument("--program", action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.output.exists() and not args.force:
            raise ValueError(f"refusing to overwrite: {args.output}")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.id):
            raise ValueError("--id must be a lowercase kebab-case identifier")
        if not args.display_name.strip():
            raise ValueError("--display-name must be nonblank")
        if not args.url.startswith(("https://", "http://")):
            raise ValueError("--url must be http(s)")
        if any(not value.strip() for value in (*args.alias, *args.market, *args.program)):
            raise ValueError("aliases, markets, and programs must be nonblank")
        payload = build_platform_template(
            platform_id=args.id, display_name=args.display_name, url=args.url,
            source_type=args.source_type, aliases=args.alias, markets=args.market,
            programs=args.program, access=args.access,
        )
        atomic_write_text(args.output, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        config = _load_config(args.output)
        print(f"CREATED: {args.output} ({config.id}, conditional route; verification required)")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
