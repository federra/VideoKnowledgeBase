"""Exact-version assessments. Unknown evidence is never numeric zero."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictInt, model_validator

from app.contracts.models import Contract

ScoreValue = Annotated[StrictInt, Field(ge=0, le=5)]
DimensionKey = Literal[
    "emotion",
    "conflict",
    "contrast",
    "antagonist",
    "twist",
    "audience",
    "platform",
    "acquisition",
    "sequel",
    "differentiation",
]


class Dimension(Contract):
    key: DimensionKey
    score: ScoreValue | None
    analysis: str = Field(min_length=1, max_length=4000)


class ScoreResult(Contract):
    dimensions: list[Dimension] = Field(min_length=10, max_length=10)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class AssessmentView(ScoreResult):
    id: UUID
    topic_version: int
    rubric_version: Literal["genre-load-v2", "genre-load-v3-inferred"]
    content_total: int | None
    market_total: int | None
    total: int | None
    created_at: datetime

    market_basis: Literal["ai_inference", "unavailable"]

    @model_validator(mode="before")
    @classmethod
    def derive_market_basis(cls, value):
        if isinstance(value, dict):
            value = {
                **value,
                "market_basis": "ai_inference"
                if value.get("rubric_version") == "genre-load-v3-inferred"
                else "unavailable",
            }
        return value


class EvaluateRequest(Contract):
    expected_version: int = Field(ge=1)


class ScoreTaskView(Contract):
    id: UUID
    task_id: UUID
    state: Literal["queued", "running", "succeeded", "failed", "cancel_requested", "cancelled"]
    safe_error_code: str | None
    topic_id: UUID
    topic_version: int
    assessment: AssessmentView | None
