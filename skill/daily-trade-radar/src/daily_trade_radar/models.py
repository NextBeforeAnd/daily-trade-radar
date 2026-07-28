"""Shared type definitions for radar event data."""

from __future__ import annotations

from typing import Any, TypedDict


JsonObject = dict[str, Any]


class ScoreBreakdown(TypedDict):
    regulatory_force: int
    business_exposure: int
    urgency: int
    consequence: int
    evidence: int


class LevelOverride(TypedDict):
    level: str
    reason: str


class MatchRecord(TypedDict):
    current_id: str | None
    previous_id: str | None
    similarity: float
    match_method: str
    match_confidence: str
    match_components: dict[str, float]
    review_required: bool
    disposition: str
    change_reasons: list[str]
