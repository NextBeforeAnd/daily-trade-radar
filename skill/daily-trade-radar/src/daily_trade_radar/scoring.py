"""Deterministic score and risk-level rules."""

SCORE_DIMENSIONS = frozenset({
    "regulatory_force",
    "business_exposure",
    "urgency",
    "consequence",
    "evidence",
})
LEVELS = frozenset({"high", "medium", "low", "watch"})


def level_for_score(score: int) -> str:
    if score >= 8:
        return "high"
    if score >= 5:
        return "medium"
    if score >= 2:
        return "low"
    return "watch"
