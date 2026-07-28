"""Unified command-line interface for package users."""

from __future__ import annotations

from importlib import import_module
import sys


COMMAND_MODULES = {
    "validate": "daily_trade_radar.validation",
    "deduplicate": "daily_trade_radar.deduplication",
    "snapshot": "daily_trade_radar.snapshots.filesystem",
    "snapshot-audit": "daily_trade_radar.snapshots.audit",
    "markdown": "daily_trade_radar.renderers.markdown",
    "docx": "daily_trade_radar.renderers.docx",
    "platforms": "daily_trade_radar.platforms.cli",
    "acquisition": "daily_trade_radar.acquisition.cli",
    "calibrate": "daily_trade_radar.calibration",
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
