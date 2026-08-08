"""Unified command-line interface for package users."""

from __future__ import annotations

from importlib import import_module
import sys


COMMAND_MODULES = {
    "init": "daily_trade_radar.initializer",
    "language-check": "daily_trade_radar.language_quality",
    "coverage-dashboard": "daily_trade_radar.coverage_dashboard",
    "run": "daily_trade_radar.run",
    "validate": "daily_trade_radar.validation",
    "deduplicate": "daily_trade_radar.deduplication",
    "snapshot": "daily_trade_radar.snapshots.filesystem",
    "snapshot-audit": "daily_trade_radar.snapshots.audit",
    "markdown": "daily_trade_radar.renderers.markdown",
    "docx": "daily_trade_radar.renderers.docx",
    "platforms": "daily_trade_radar.platforms.cli",
    "acquisition": "daily_trade_radar.acquisition.cli",
    "plan": "daily_trade_radar.planning",
    "doctor": "daily_trade_radar.source_health",
    "discover": "daily_trade_radar.discovery",
    "library": "daily_trade_radar.library",
    "drill": "daily_trade_radar.drill",
    "calibrate": "daily_trade_radar.calibration",
    "calibration-scaffold": "daily_trade_radar.calibration_scaffold",
    "calibration-update": "daily_trade_radar.calibration_update",
    "calibration-promote": "daily_trade_radar.calibration_promote",
    "calibration-rollback": "daily_trade_radar.calibration_rollback",
    "evaluate": "daily_trade_radar.evaluation",
    "evaluate-history": "daily_trade_radar.evaluation_history",
    "evaluation-scaffold": "daily_trade_radar.evaluation_scaffold",
    "match": "daily_trade_radar.applicability",
    "alert": "daily_trade_radar.alerting",
}


def usage() -> str:
    commands = " | ".join(COMMAND_MODULES)
    return (
        "usage: daily-trade-radar <command> [arguments]\n\n"
        f"commands: {commands}\n"
        "Run 'daily-trade-radar <command> --help' for command-specific options."
    )


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] in {"-h", "--help"}:
        print(usage())
        return 0
    command = arguments.pop(0)
    module_name = COMMAND_MODULES.get(command)
    if module_name is None:
        print(f"ERROR: unknown command {command!r}\n\n{usage()}", file=sys.stderr)
        return 2
    module = import_module(module_name)
    return module.main(arguments)
