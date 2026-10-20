"""Same-day sample insight schema. Generation and persistence are not enabled."""

from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.models import Business, Contract, Digest, NonEmpty, PositiveInt


class FeedbackRef(Contract):
    id: UUID
    version: PositiveInt
    business_code: Business
    business_date: date
    input_sha256: Digest


class InsightInput(Contract):
    business_code: Business
    business_date: date
    feedbacks: Annotated[list[FeedbackRef], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def exact_scope(self):
        if len({x.id for x in self.feedbacks}) != len(self.feedbacks) or any(
            x.business_code != self.business_code or x.business_date != self.business_date
            for x in self.feedbacks
        ):
            raise ValueError("Mixed or duplicate feedback scope")
        return self


class Statement(Contract):
    kind: Literal["emotion", "motif", "genre", "direction"]
    text: NonEmpty
    feedback_ids: Annotated[list[UUID], Field(min_length=1, max_length=10)]


class InsightOutput(Contract):
    scope: Literal["sample"]
    coverage_note: NonEmpty
    statements: Annotated[list[Statement], Field(min_length=1, max_length=20)]


def inspect_output(sample: InsightInput, value):
    output = InsightOutput.model_validate(value)
    ids = {x.id for x in sample.feedbacks}
    for item in output.statements:
        refs = set(item.feedback_ids)
        if len(refs) != len(item.feedback_ids) or not refs <= ids:
            raise ValueError("Unknown insight evidence")
    return output.model_dump(mode="json")
