"""Render an actionable platform-source coverage dashboard."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from html import escape
import json
from pathlib import Path
from typing import Any, Iterable

from .platforms import get_platform, load_registry, source_depth
from .snapshots.filesystem import atomic_write_text


def _health_index(health: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for record in (health or {}).get("records", []):
        if isinstance(record, dict) and isinstance(record.get("platform"), str):
            result.setdefault(record["platform"].casefold(), []).append(record)
    return result


def build_dashboard(
    platforms: Iterable[str] | None = None, *, health: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    if health is not None and not isinstance(health, dict):
        raise ValueError("health input must be a JSON object")
    registry = load_registry()
    if platforms:
        selected = []
        seen: set[str] = set()
        for name in platforms:
            config = get_platform(name)
            if config is None:
                raise ValueError(f"unregistered platform: {name}")
            if config.id not in seen:
                selected.append(config)
                seen.add(config.id)
    else:
        selected = [registry[key] for key in sorted(registry)]
    health_by_platform = _health_index(health)
    rows: list[dict[str, Any]] = []
    for config in selected:
        depth = source_depth(config)
        records = health_by_platform.get(config.display_name.casefold(), [])
        states = sorted({str(record.get("audit_state")) for record in records if record.get("audit_state")})
        checked = sorted(str(record["checked_at"]) for record in records if record.get("checked_at"))
        verified_dates = sorted(
            str(route["last_verified_on"]) for route in config.official_routes if route.get("last_verified_on")
        )
        priority = {"full": 0, "hybrid": 40, "constrained": 70}[depth["status"]]
        priority += 20 * len(depth["missing_source_types"])
        priority += 10 * depth["conditional_route_count"]
        priority += 15 if depth["verified_public_route_count"] == 0 else 0
        priority += 10 * sum(state in {"blocked", "timeout", "rate_limited", "schema_drift"} for state in states)
        actions: list[str] = []
        if depth["missing_source_types"]:
            actions.append("Add verified routes for " + ", ".join(depth["missing_source_types"]))
        if depth["conditional_route_count"]:
            actions.append(f"Reverify {depth['conditional_route_count']} conditional route(s)")
        if depth["verified_public_route_count"] == 0:
            actions.append("Establish at least one verified public route")
        if any(state in {"blocked", "timeout", "rate_limited", "schema_drift"} for state in states):
            actions.append("Resolve the latest source-health failure before claiming coverage")
        if not actions:
            actions.append("Maintain route verification and substantive review cadence")
        rows.append({
            "id": config.id, "platform": config.display_name, "status": depth["status"],
            "priority": min(priority, 100), "route_count": depth["route_count"],
            "verified_source_types": depth["verified_source_types"],
            "missing_source_types": depth["missing_source_types"],
            "conditional_route_count": depth["conditional_route_count"],
            "verified_public_route_count": depth["verified_public_route_count"],
            "declared_gaps": depth["declared_gaps"],
            "last_verified_on": verified_dates[-1] if verified_dates else None,
            "last_checked_at": checked[-1] if checked else None,
            "health_states": states,
            "actions": actions,
            "routes": [dict(route) for route in config.official_routes],
        })
    rows.sort(key=lambda row: (-row["priority"], row["platform"].casefold()))
    counts = Counter(row["status"] for row in rows)
    return {
        "schema_version": "1.0",
        "generated_at": generated_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": {
            "platform_count": len(rows), "full": counts["full"],
            "hybrid": counts["hybrid"], "constrained": counts["constrained"],
            "platforms_requiring_action": sum(bool(row["priority"]) for row in rows),
        },
        "platforms": rows,
        "disclaimer": "Route coverage and access health do not prove that a policy was substantively reviewed.",
    }


def render_markdown(data: dict[str, Any]) -> str:
    summary = data["summary"]
    lines = [
        "# Platform Source Coverage Dashboard", "",
        f"Generated: {data['generated_at']}", "",
        f"Platforms: {summary['platform_count']} | Full: {summary['full']} | Hybrid: {summary['hybrid']} | Constrained: {summary['constrained']}",
        "", f"> {data['disclaimer']}", "",
        "| Priority | Platform | Depth | Verified types | Conditional | Missing / gaps | Last checked | Next action |",
        "|---:|---|---|---|---:|---|---|---|",
    ]
    for row in data["platforms"]:
        gaps = "; ".join(f"{key}: {value}" for key, value in row["declared_gaps"].items())
        missing = ", ".join(row["missing_source_types"])
        gap_text = "; ".join(value for value in (missing, gaps) if value)
        lines.append(
            f"| {row['priority']} | {row['platform']} | {row['status']} "
            f"| {', '.join(row['verified_source_types']) or 'none'} | {row['conditional_route_count']} "
            f"| {gap_text or 'none'} | {row['last_checked_at'] or row['last_verified_on'] or 'never'} "
            f"| {'; '.join(row['actions'])} |"
        )
    return "\n".join(lines) + "\n"


def render_html(data: dict[str, Any]) -> str:
    summary = data["summary"]
    cards = "".join(
        f'<div class="card"><strong>{escape(str(value))}</strong><span>{escape(label)}</span></div>'
        for label, value in (
            ("Platforms", summary["platform_count"]), ("Full", summary["full"]),
            ("Hybrid", summary["hybrid"]), ("Constrained", summary["constrained"]),
        )
    )
    rows = []
    for row in data["platforms"]:
        routes = "".join(
            f'<li><a href="{escape(str(route["url"]), quote=True)}">{escape(str(route["source_type"]))}</a> · '
            f'{escape(str(route["verification_status"]))}</li>'
            for route in row["routes"]
        )
        gaps = "<br>".join(
            f"<b>{escape(str(key))}</b>: {escape(str(value))}" for key, value in row["declared_gaps"].items()
        ) or escape(", ".join(row["missing_source_types"]) or "none")
        rows.append(
            f'<tr><td class="priority">{row["priority"]}</td><td><strong>{escape(row["platform"])}</strong><ul>{routes}</ul></td>'
            f'<td><span class="badge {escape(row["status"])}">{escape(row["status"])}</span></td>'
            f'<td>{escape(", ".join(row["verified_source_types"]) or "none")}</td>'
            f'<td>{row["conditional_route_count"]}</td><td>{gaps}</td>'
            f'<td>{escape(str(row["last_checked_at"] or row["last_verified_on"] or "never"))}</td>'
            f'<td>{escape("; ".join(row["actions"]))}</td></tr>'
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Platform Source Coverage Dashboard</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7fa;color:#172033}}main{{max-width:1440px;margin:auto;padding:28px}}
h1{{margin:0 0 6px}}.meta{{color:#62708a}}.cards{{display:flex;gap:12px;margin:22px 0;flex-wrap:wrap}}
.card{{background:white;border:1px solid #dce2ea;border-radius:10px;padding:14px 20px;min-width:120px}}.card strong{{font-size:26px;display:block}}.card span{{color:#62708a}}
table{{width:100%;border-collapse:collapse;background:white;font-size:14px}}th,td{{padding:12px;border:1px solid #dce2ea;text-align:left;vertical-align:top}}th{{background:#eef2f7}}ul{{margin:7px 0 0;padding-left:18px}}
.priority{{font-weight:700;text-align:center}}.badge{{padding:3px 8px;border-radius:999px}}.full{{background:#d9f7e8}}.hybrid{{background:#fff0c2}}.constrained{{background:#ffd9d9}}
.notice{{background:#eaf2ff;border-left:4px solid #3977d5;padding:12px;margin:18px 0}}a{{color:#1f66c1}}
</style></head><body><main><h1>Platform Source Coverage Dashboard</h1><div class="meta">Generated {escape(data['generated_at'])}</div>
<div class="cards">{cards}</div><div class="notice">{escape(data['disclaimer'])}</div>
<table><thead><tr><th>Priority</th><th>Platform / routes</th><th>Depth</th><th>Verified types</th><th>Conditional</th><th>Missing / gaps</th><th>Last checked</th><th>Next action</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></main></body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", action="append")
    parser.add_argument("--health", type=Path, help="optional doctor/postmortem JSON")
    parser.add_argument("--format", choices=("html", "markdown", "json"), default="html")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        health = json.loads(args.health.read_text(encoding="utf-8")) if args.health else None
        data = build_dashboard(args.platform, health=health)
        if args.format == "json":
            content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        elif args.format == "markdown":
            content = render_markdown(data)
        else:
            content = render_html(data)
        atomic_write_text(args.output, content)
        print(f"WROTE: {args.output} ({len(data['platforms'])} platform(s))")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
