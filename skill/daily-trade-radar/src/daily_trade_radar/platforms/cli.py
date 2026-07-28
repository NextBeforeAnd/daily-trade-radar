"""Inspect the bundled platform registry."""

from __future__ import annotations

import argparse
import json

from .registry import load_registry, source_depth


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args(argv)
    registry = load_registry()
    if args.json:
        payload = [
            {
                "id": config.id,
                "display_name": config.display_name,
                "aliases": list(config.aliases),
                "seller_markets": list(config.seller_markets),
                "programs": list(config.programs),
                "official_routes": list(config.official_routes),
                "source_depth": source_depth(config),
            }
            for config in registry.values()
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for config in registry.values():
            depth = source_depth(config)
            print(
                f"{config.id}: {config.display_name} "
                f"({len(config.official_routes)} official route(s), {depth['status']} source depth)"
            )
    return 0
