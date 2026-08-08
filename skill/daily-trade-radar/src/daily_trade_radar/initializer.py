"""Create a safe starter profile for a narrow Daily Trade Radar pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from .planning import build_research_plan
from .platforms import get_platform
from .profiles import load_profile
from .snapshots.filesystem import atomic_write_text


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return result or "daily-trade-radar"


def build_starter_files(
    *, name: str, regions: list[str], products: list[str], hs_codes: list[str],
    platforms: list[str], language: str, formats: list[str], sku: str | None = None,
) -> tuple[dict, dict | None]:
    if not name.strip():
        raise ValueError("name must be nonblank")
    if not regions:
        raise ValueError("at least one region is required")
    resolved_platforms: list[str] = []
    for platform in platforms:
        config = get_platform(platform)
        if config is None:
            raise ValueError(f"unregistered platform: {platform}")
        if config.display_name not in resolved_platforms:
            resolved_platforms.append(config.display_name)
    profile: dict = {
        "schema_version": "1.0",
        "name": name.strip(),
        "scope": {
            "language": language,
            "regions": list(dict.fromkeys(item.strip() for item in regions)),
            "products": list(dict.fromkeys(item.strip() for item in products if item.strip())),
            "hs_codes": list(dict.fromkeys(item.strip() for item in hs_codes if item.strip())),
            "platforms": resolved_platforms,
        },
        "output": {
            "directory": "output",
            "basename": _slug(name),
            "formats": list(dict.fromkeys(formats)),
        },
        "deduplication": {"threshold": 0.82, "review_threshold": 0.65},
        "quality": {"language_mode": "strict"},
        "alerts": {"min_level": "high", "require_applicability_match": bool(sku)},
    }
    catalog = None
    if sku:
        if len(products) != 1:
            raise ValueError("--sku requires exactly one --product so catalog identity is unambiguous")
        catalog = {
            "schema_version": "1.0",
            "organization": name.strip(),
            "items": [{
                "sku": sku.strip(), "name": products[0].strip(),
                "hs_codes": profile["scope"]["hs_codes"], "keywords": [],
                "markets": profile["scope"]["regions"], "platforms": resolved_platforms,
            }],
        }
        profile["catalog"] = "catalog.json"
    # Validate the generated scope before touching the filesystem.
    build_research_plan(profile["scope"])
    return profile, catalog


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path("radar-profile"))
    parser.add_argument("--name", default="starter-radar")
    parser.add_argument("--region", action="append", default=[])
    parser.add_argument("--product", action="append", default=[])
    parser.add_argument("--hs-code", action="append", default=[])
    parser.add_argument("--platform", action="append", default=[])
    parser.add_argument("--language", choices=("zh-CN", "en-US"), default="zh-CN")
    parser.add_argument("--format", action="append", choices=("markdown", "docx"), default=[])
    parser.add_argument("--sku", help="also create a one-item organization catalog")
    parser.add_argument("--force", action="store_true", help="replace generated files if they already exist")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        directory = args.directory.resolve()
        profile_path = directory / "profile.json"
        catalog_path = directory / "catalog.json"
        targets = [profile_path, *([catalog_path] if args.sku else [])]
        existing = [path for path in targets if path.exists()]
        if existing and not args.force:
            raise ValueError("refusing to overwrite: " + ", ".join(str(path) for path in existing))
        profile, catalog = build_starter_files(
            name=args.name, regions=args.region or ["China"], products=args.product,
            hs_codes=args.hs_code, platforms=args.platform, language=args.language,
            formats=args.format or ["markdown"], sku=args.sku,
        )
        directory.mkdir(parents=True, exist_ok=True)
        atomic_write_text(profile_path, json.dumps(profile, ensure_ascii=False, indent=2) + "\n")
        if catalog is not None:
            atomic_write_text(catalog_path, json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        load_profile(profile_path)
        print(f"CREATED: {profile_path}")
        if catalog is not None:
            print(f"CREATED: {catalog_path}")
        print(f"NEXT: daily-trade-radar run --profile {profile_path}")
        return 0
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
