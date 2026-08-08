"""Run the deterministic Daily Trade Radar workflow from one profile."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
from typing import Any

from .alerting import build_alert_batch, deliver_webhook, load_state, save_state
from .applicability import load_catalog, match_report
from .deduplication import main as deduplicate_main
from .language_quality import assess_language
from .planning import build_research_plan, write_acquisition_manifests
from .profiles import load_profile
from .renderers.markdown import main as markdown_main
from .snapshots.filesystem import atomic_write_text
from .validation import validate


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _write(path: Path, value: object) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _status(output: Path, profile: str, state: str, artifacts: dict[str, str], **extra: object) -> None:
    _write(output / "run-status.json", {
        "schema_version": "1.0", "profile": profile, "state": state,
        "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "artifacts": artifacts, **extra,
    })


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--events", type=Path, help="validated candidate event JSON; overrides profile")
    parser.add_argument("--previous", type=Path, help="previous event JSON; overrides profile")
    parser.add_argument("--output-dir", type=Path, help="run directory; overrides profile")
    parser.add_argument("--send-alerts", action="store_true", help="explicitly POST eligible alerts to the profile webhook")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        profile = load_profile(args.profile)
        output = (args.output_dir or profile.output_directory).resolve()
        output.mkdir(parents=True, exist_ok=True)
        artifacts: dict[str, str] = {}

        plan = build_research_plan(profile.scope)
        plan_path = output / "research-plan.json"
        _write(plan_path, plan.to_dict())
        artifacts["research_plan"] = str(plan_path)
        manifest_paths = write_acquisition_manifests(plan, output / "manifests")
        artifacts["manifest_directory"] = str(output / "manifests")
        artifacts["manifest_count"] = str(len(manifest_paths))

        event_source = (args.events.resolve() if args.events else profile.candidate_report)
        if event_source is None:
            _status(
                output, profile.name, "research_required", artifacts,
                next_step="Research every plan track, record receipts/gaps, then rerun with --events CANDIDATE_REPORT.json.",
            )
            print(f"PREPARED: {output} (research required before report generation)")
            return 0
        report = _load_object(event_source)
        if profile.catalog:
            report = match_report(report, load_catalog(profile.catalog))
        enriched_path = output / "events-enriched.json"
        _write(enriched_path, report)
        artifacts["enriched_events"] = str(enriched_path)

        errors = validate(report)
        if errors:
            error_path = output / "validation-errors.json"
            _write(error_path, {"errors": errors})
            artifacts["validation_errors"] = str(error_path)
            _status(output, profile.name, "validation_failed", artifacts, error_count=len(errors))
            print(f"ERROR: candidate report failed validation ({len(errors)} error(s)); see {error_path}")
            return 1
        if profile.language_mode != "off":
            language_result = assess_language(
                report, require_language=str(profile.scope.get("language", report.get("language", ""))),
            )
            language_path = output / "language-quality.json"
            _write(language_path, language_result)
            artifacts["language_quality"] = str(language_path)
            if profile.language_mode == "strict" and language_result["issues"]:
                _status(
                    output, profile.name, "language_review_required", artifacts,
                    language_issue_count=language_result["issue_count"],
                )
                print(f"ERROR: language consistency review required; see {language_path}")
                return 1

        previous = args.previous.resolve() if args.previous else profile.previous_report
        final_path = output / "events-final.json"
        if previous:
            result = deduplicate_main([
                str(enriched_path), "--previous", str(previous), "--output", str(final_path),
                "--threshold", str(profile.threshold), "--review-threshold", str(profile.review_threshold),
            ])
            if result:
                raise ValueError("deduplication failed")
        else:
            shutil.copyfile(enriched_path, final_path)
        final_report = _load_object(final_path)
        final_errors = validate(final_report)
        if final_errors:
            raise ValueError("post-deduplication validation failed: " + "; ".join(final_errors[:5]))
        artifacts["final_events"] = str(final_path)

        if "markdown" in profile.formats:
            markdown_path = output / f"{profile.output_basename}.md"
            if markdown_main([str(final_path), "--output", str(markdown_path)]):
                raise ValueError("Markdown rendering failed")
            artifacts["markdown"] = str(markdown_path)
        if "docx" in profile.formats:
            from .renderers.docx import main as docx_main

            docx_path = output / f"{profile.output_basename}.docx"
            if docx_main([str(final_path), "--output", str(docx_path)]):
                raise ValueError("DOCX rendering failed")
            artifacts["docx"] = str(docx_path)

        seen = load_state(profile.alert_state_file)
        batch = build_alert_batch(
            final_report, min_level=profile.alert_min_level,
            require_applicability_match=profile.alert_require_match,
            seen_signatures=seen,
        )
        alert_path = output / "alerts.json"
        _write(alert_path, batch)
        artifacts["alerts"] = str(alert_path)
        delivered = False
        if args.send_alerts and batch["alert_count"]:
            if not profile.alert_webhook:
                raise ValueError("--send-alerts requires profile.alerts.webhook")
            deliver_webhook(batch, profile.alert_webhook)
            delivered = True
        if profile.alert_state_file and delivered:
            save_state(profile.alert_state_file, seen | {item["signature"] for item in batch["alerts"]})
            artifacts["alert_state"] = str(profile.alert_state_file)
        _status(
            output, profile.name, "complete", artifacts,
            event_count=len(final_report.get("events", [])), alert_count=batch["alert_count"],
            alerts_delivered=delivered,
        )
        print(f"COMPLETE: {output} ({batch['alert_count']} eligible alert(s), delivered={delivered})")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
