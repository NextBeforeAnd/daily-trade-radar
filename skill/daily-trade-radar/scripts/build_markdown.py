#!/usr/bin/env python3
"""Build a stable Markdown radar from validated event JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


LEVEL_ORDER = {"high": 0, "medium": 1, "low": 2, "watch": 3}
LEVEL_ZH = {"high": "高", "medium": "中", "low": "低", "watch": "观察"}
STATUS_ZH = {"new": "今日新增", "effective": "已生效", "deadline": "临近截止", "ongoing": "持续关注", "unconfirmed": "待核实"}
LEVEL_EN = {"high": "High", "medium": "Medium", "low": "Low", "watch": "Watch"}
STATUS_EN = {
    "new": "New today",
    "effective": "Effective",
    "deadline": "Approaching deadline",
    "ongoing": "Ongoing",
    "unconfirmed": "Unconfirmed",
}


def clean(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ").strip()


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = load(args.input)
    english = str(data.get("language", "")).casefold().startswith("en")
    events = sorted(
        data.get("events", []),
        key=lambda event: (LEVEL_ORDER.get(event.get("level"), 9), -int(event.get("score", 0)), event.get("effective_date") or "9999-99-99"),
    )
    main_events = [event for event in events if event.get("status") != "unconfirmed"]
    watch = [event for event in events if event.get("status") == "unconfirmed"]

    if english:
        if any(event.get("status") == "new" for event in main_events):
            judgment = "Verified new developments were found today. Act on the items below according to risk and urgency."
        elif main_events:
            judgment = "No verified material new developments were found today. The items below are effective, approaching a deadline, or ongoing."
        else:
            judgment = "No material items met the main-table evidence standard within this search scope and cutoff."
    elif any(event.get("status") == "new" for event in main_events):
        judgment = "发现经过核验的今日新增事项；请按风险等级和紧迫性执行表内项目。"
    elif main_events:
        judgment = "未发现经过核验的重大今日新增事项；以下为已生效、临近截止或持续关注项目。"
    else:
        judgment = "在本次检索范围和截止时间内，未发现可进入主表的重大事项。"

    if english:
        lines = [
            f"# Daily Trade Radar | {clean(data.get('report_date'))}",
            "",
            f"- Timezone: {clean(data.get('timezone'))}",
            f"- Search cutoff: {clean(data.get('cutoff'))}",
            f"- Scope: {clean(', '.join(data.get('scope', [])))}",
            "",
            "## Today's assessment",
            "",
            judgment,
            "",
            "## Radar at a glance",
            "",
            "| Level | Status | Event | Impact | Action today | Source |",
            "|---|---|---|---|---|---|",
        ]
    else:
        lines = [
            f"# 今日外贸雷达｜{clean(data.get('report_date'))}",
            "",
            f"- 时区：{clean(data.get('timezone'))}",
            f"- 检索截止：{clean(data.get('cutoff'))}",
            f"- 范围：{clean('、'.join(data.get('scope', [])))}",
            "",
            "## 今日判断",
            "",
            judgment,
            "",
            "## 一页雷达",
            "",
            "| 级别 | 状态 | 事件 | 影响 | 今天动作 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
    if main_events:
        for event in main_events:
            source = f"[{clean(event.get('source_title'))}]({event.get('source_url')})"
            levels = LEVEL_EN if english else LEVEL_ZH
            statuses = STATUS_EN if english else STATUS_ZH
            lines.append(
                f"| {levels.get(event.get('level'), clean(event.get('level')))} "
                f"| {statuses.get(event.get('status'), clean(event.get('status')))} "
                f"| {clean(event.get('title'))} | {clean(event.get('impact'))} "
                f"| {clean(event.get('action'))} | {source} |"
            )
    else:
        empty_message = "No items met the main-table standard" if english else "本次检索未发现符合主表标准的事项"
        lines.append(f"| — | — | {empty_message} | — | — | — |")

    lines.extend(["", "## Priority actions" if english else "## 优先动作", ""])
    actionable = [event for event in main_events if event.get("level") in {"high", "medium"}]
    if actionable:
        for index, event in enumerate(actionable, 1):
            separator = ":" if english else "："
            lines.append(f"{index}. **{clean(event.get('title'))}{separator}** {clean(event.get('action'))}")
    else:
        lines.append(
            "- No high- or medium-level actions. Review ongoing items according to the established compliance cadence."
            if english else "- 暂无高、中等级动作；按既定合规节奏复核持续事项。"
        )

    lines.extend(["", "## Deduplication" if english else "## 去重说明", ""])
    dedupe = data.get("deduplication", {})
    matches = dedupe.get("matches", [])
    removed = sum(item.get("disposition") == "duplicate_removed" for item in matches)
    review = sum(item.get("disposition") == "possible_update" for item in matches)
    retained = sum(item.get("disposition") == "retained_after_review" for item in matches)
    if english:
        lines.append(
            f"Compared with the previous report, {removed} unchanged duplicate(s) were removed; "
            f"{retained} material update(s) were retained after review; {review} item(s) still require review."
        )
    else:
        lines.append(
            f"与上一期比较后移除 {removed} 条无实质变化的重复事项；"
            f"人工复核后保留 {retained} 条实质更新事项；另有 {review} 条仍待复核。"
        )

    lines.extend(["", "## Unconfirmed watchlist" if english else "## 待核实观察", ""])
    if watch:
        for event in watch:
            if english:
                lines.append(f"- **{clean(event.get('title'))}:** {clean(event.get('summary'))} (evidence standard for the main table not yet met)")
            else:
                lines.append(f"- **{clean(event.get('title'))}：** {clean(event.get('summary'))}（尚未达到主表证据标准）")
    else:
        lines.append("- None." if english else "- 无。")

    lines.extend(["", "## Coverage gaps" if english else "## 覆盖缺口", ""])
    gaps = data.get("coverage_gaps", [])
    lines.extend([f"- {clean(gap)}" for gap in gaps] or ["- No known coverage gaps." if english else "- 无已知覆盖缺口。"])

    lines.extend(["", "## Official sources" if english else "## 官方来源", ""])
    for index, event in enumerate(main_events, 1):
        if english:
            lines.append(f"- S{index}: [{clean(event.get('source_title'))}]({event.get('source_url')}), retrieved {clean(event.get('retrieved_date'))}.")
        else:
            lines.append(f"- S{index}：[{clean(event.get('source_title'))}]({event.get('source_url')})，检索于 {clean(event.get('retrieved_date'))}。")

    if english:
        lines.extend([
            "",
            "## Watch tomorrow",
            "",
            "- Check whether today's high-level items receive implementation rules, FAQs, or scope clarifications.",
            "- Check for items taking effect, expiring, or closing for consultation within the next 30 days.",
            "",
        ])
    else:
        lines.extend([
            "",
            "## 明日观察",
            "",
            "- 复核今天的高等级事项是否出现实施细则、FAQ 或范围澄清。",
            "- 检查未来 30 天内生效、到期或结束征求意见的事项。",
            "",
        ])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"WROTE: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
