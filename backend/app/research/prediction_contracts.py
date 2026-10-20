"""Human prediction drafts; exposure and timestamps are server-owned."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.models import Contract, Count, DecimalValue, MutableEntity, NonEmpty, Version


class DraftCreate(Contract):
    input_set_id: UUID
    metric_spec_id: UUID
    platform_code: Literal["douyin"]
    account_id: UUID | None = None
    window_start_offset_seconds: Count
    window_end_offset_seconds: Count
    conditions: dict[str, object]
    reliability: Literal["estimable", "insufficient_evidence"]
    lower_bound: DecimalValue | None = None
    upper_bound: DecimalValue | None = None
    rationale: NonEmpty
    uncertainty_note: NonEmpty
    supersedes_prediction_id: UUID | None = None

    @model_validator(mode="after")
    def bounds(self):
        if int(self.window_end_offset_seconds) <= int(self.window_start_offset_seconds):
            raise ValueError("Invalid window")
        if (self.reliability == "estimable") != (self.lower_bound is not None) or (
            self.lower_bound is None
        ) != (self.upper_bound is None):
            raise ValueError("Bounds and reliability mismatch")
        if self.lower_bound is not None and (
            Decimal(self.lower_bound) < 0
            or Decimal(self.upper_bound) < Decimal(self.lower_bound)
            or Decimal(self.upper_bound) > Decimal("99999999999999.999999")
        ):
            raise ValueError("Invalid bounds")
        if not self.rationale.strip() or not self.uncertainty_note.strip():
            raise ValueError("Explanation required")
        import json

        if len(json.dumps(self.conditions, ensure_ascii=False, allow_nan=False)) > 20000:
            raise ValueError("Conditions too large")
        return self


class DraftUpdate(DraftCreate):
    expected_lock_version: Version


class DraftView(DraftCreate, MutableEntity):
    context_kind: Literal["retrospective", "unknown"]
    outcome_exposure: Literal["observed", "unknown"]
    author_kind: Literal["human"]
    author_member_id: UUID


class Retraction(Contract):
    reason: NonEmpty = Field(max_length=1000)
