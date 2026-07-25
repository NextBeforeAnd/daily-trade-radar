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
POLICY_AREA_ZH = {
    "onboarding_kyc": "入驻与身份核验",
    "listing_product_compliance": "刊登与商品合规",
    "pricing_promotions": "定价与促销",
    "fees_commissions": "费用与佣金",
    "fulfillment_logistics": "履约与物流",
    "returns_refunds_aftersales": "退货退款与售后",
    "payments_settlement_tax": "支付、结算与税务",
    "content_ads_affiliate": "内容、广告与联盟",
    "data_privacy_security": "数据、隐私与安全",
    "account_health_enforcement": "账户健康与执法",
    "api_feature_deprecation": "API、功能与停用",
    "other": "其他",
}


def clean(value: object) -> str:
    return str(value or "—").replace("|", "\\|").replace("\n", " ").strip()


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def action_item_text(item: dict, english: bool) -> str:
    action = clean(item.get("action")).rstrip("。.;；")
    evidence = clean(item.get("completion_evidence")).rstrip("。.;；")
    if english:
        return (
            f"{clean(item.get('owner'))} | {clean(item.get('deadline'))}: "
            f"{action}. Completion evidence: {evidence}."
        )
    return (
        f"{clean(item.get('owner'))}｜{clean(item.get('deadline'))}："
        f"{action}；完成凭证：{evidence}。"
    )


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
            f"- Reporting window starts: {clean(data.get('window_start'))}",
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
            f"- 报告窗口起点：{clean(data.get('window_start'))}",
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
        action_number = 1
        for event in actionable:
            separator = ":" if english else "："
            items = event.get("action_items") or []
            if items:
                for item in items:
                    lines.append(f"{action_number}. **{clean(event.get('title'))}{separator}** {action_item_text(item, english)}")
                    action_number += 1
            else:
                lines.append(f"{action_number}. **{clean(event.get('title'))}{separator}** {clean(event.get('action'))}")
                action_number += 1
    else:
        lines.append(
            "- No high- or medium-level actions. Review ongoing items according to the established compliance cadence."
            if english else "- 暂无高、中等级动作；按既定合规节奏复核持续事项。"
        )

    platform_events = [event for event in main_events if isinstance(event.get("platform_policy"), dict)]
    if platform_events:
        lines.extend(["", "## Platform policy analysis" if english else "## 平台政策分析", ""])
        if english:
            lines.extend([
                "| Platform / market | Area | Change | Seller scope | Verified new state | Enforcement |",
                "|---|---|---|---|---|---|",
            ])
        else:
            lines.extend([
                "| 平台 / 市场 | 政策领域 | 变化类型 | 卖家范围 | 已核实新状态 | 执法后果 |",
                "|---|---|---|---|---|---|",
            ])
        for event in platform_events:
            policy = event["platform_policy"]
            area = policy.get("policy_area") if english else POLICY_AREA_ZH.get(policy.get("policy_area"), policy.get("policy_area"))
            lines.append(
                f"| {clean(policy.get('platform'))} / {clean(policy.get('seller_market'))} "
                f"| {clean(area)} | {clean(policy.get('change_type'))} | {clean(policy.get('seller_scope'))} "
                f"| {clean(policy.get('new_state'))} | {clean(policy.get('enforcement_consequence'))} |"
            )

    lines.extend(["", "## Deduplication" if english else "## 去重说明", ""])
    dedupe = data.get("deduplication", {})
    matches = dedupe.get("matches", [])
    removed = sum(item.get("disposition") == "duplicate_removed" for item in matches)
    review = sum(item.get("disposition") == "possible_update" for item in matches)
    material = sum(item.get("disposition") in {"material_update", "retained_after_review"} for item in matches)
    operational = sum(item.get("disposition") == "operational_refresh" for item in matches)
    if english:
        lines.append(
            f"Compared with the previous report, {removed} unchanged duplicate(s) were removed; "
            f"{material} material update(s) and {operational} operational refresh(es) were retained; "
            f"{review} item(s) still require review."
        )
    else:
        lines.append(
            f"与上一期比较后移除 {removed} 条无实质变化的重复事项；"
            f"保留 {material} 条实质更新事项和 {operational} 条运营节点刷新事项；"
            f"另有 {review} 条仍待复核。"
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

    coverage_ledger = data.get("coverage_ledger", [])
    if coverage_ledger:
        lines.extend(["", "## Platform coverage ledger" if english else "## 平台覆盖台账", ""])
        if english:
            lines.extend([
                "| Platform / market | Program | Public update | Current policy | Dashboard | Access result | Checked at | Gaps |",
                "|---|---|---|---|---|---|---|---|",
            ])
        else:
            lines.extend([
                "| 平台 / 市场 | 项目 / 模式 | 公告核验 | 现行政策核验 | 后台核验 | 访问结果 | 核验时间 | 缺口 |",
                "|---|---|---|---|---|---|---|---|",
            ])
        yes_no = (lambda value: "Yes" if value else "No") if english else (lambda value: "是" if value else "否")
        for entry in coverage_ledger:
            lines.append(
                f"| {clean(entry.get('platform'))} / {clean(entry.get('seller_market'))} "
                f"| {clean(entry.get('program'))} | {yes_no(entry.get('public_update_checked'))} "
                f"| {yes_no(entry.get('current_policy_checked'))} | {yes_no(entry.get('dashboard_checked'))} "
                f"| {clean(entry.get('access_result'))} | {clean(entry.get('checked_at'))} "
                f"| {clean('；'.join(entry.get('gaps', [])))} |"
            )

    lines.extend(["", "## Official sources" if english else "## 官方来源", ""])
    for index, event in enumerate(main_events, 1):
        exact_times = [
            ("published", "发布", event.get("published_at")),
            ("effective", "生效", event.get("effective_at")),
            ("deadline", "截止", event.get("deadline_at")),
        ]
        time_text = "; ".join(
            f"{en_label if english else zh_label}: {clean(value)}"
            for en_label, zh_label, value in exact_times
            if value
        )
        if time_text and event.get("source_timezone"):
            time_text += f"; {'source timezone' if english else '来源时区'}: {clean(event.get('source_timezone'))}"
        if english:
            suffix = f" Exact timing: {time_text}." if time_text else ""
            lines.append(f"- S{index}: [{clean(event.get('source_title'))}]({event.get('source_url')}), retrieved {clean(event.get('retrieved_date'))}.{suffix}")
        else:
            suffix = f" 精确时间：{time_text}。" if time_text else ""
            lines.append(f"- S{index}：[{clean(event.get('source_title'))}]({event.get('source_url')})，检索于 {clean(event.get('retrieved_date'))}。{suffix}")

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
