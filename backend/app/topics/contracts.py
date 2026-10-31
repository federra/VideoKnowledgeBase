from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.contracts.models import Contract
from app.topics.score_contracts import AssessmentView, ScoreTaskView

Business = Literal["motion_comic", "story_short"]
Text = Annotated[str, Field(max_length=12000)]


class TopicFields(Contract):
    title: str = Field(min_length=1, max_length=90)
    audience: str = Field(default="", max_length=500)
    logline: str = Field(min_length=1, max_length=4000)
    character_settings: Text = ""
    global_rhythm: Text = ""

    @field_validator("*", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class GenerateRequest(Contract):
    business_code: Business
    mode: Literal["batch", "brainstorm"]
    spark_ids: list[UUID] = Field(default_factory=list, max_length=12)
    instructions: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.spark_ids)) != len(self.spark_ids) or bool(self.spark_ids) != (
            self.mode == "brainstorm"
        ):
            raise ValueError("Brainstorm requires distinct sparks; batch accepts no sparks")
        return self


class TopicWrite(Contract):
    business_code: Business
    fields: TopicFields


class TopicUpdate(Contract):
    expected_version: int = Field(ge=1)
    fields: TopicFields


class TopicSelect(Contract):
    expected_version: int = Field(ge=1)


class TopicHandoff(TopicSelect):
    method: Literal["copy", "export"]
    phase: Literal["authorize", "confirm"] = "confirm"


class GenerationSave(Contract):
    fields: TopicFields


class SparkWrite(Contract):
    id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Empty spark")
        return value.strip()

    @model_validator(mode="after")
    def update_pair(self):
        if (self.id is None) != (self.expected_version is None):
            raise ValueError("Version required")
        return self


class TopicQuery(Contract):
    business_code: Business
    pool: Literal["candidate", "production"] = "candidate"
    page: int = Field(default=1, ge=1, le=2147483647)
    q: str | None = Field(default=None, max_length=100)
    status: Literal["all", "pending", "handed_off"] = "all"


class History(Contract):
    version: int
    fields: TopicFields
    created_at: datetime


class OriginalityView(Contract):
    status: Literal["no_obvious_overlap", "risk", "unchecked"]
    matches: list[dict]
    limitations: str


class TopicView(Contract):
    id: UUID
    business_code: Business
    version: int
    status: Literal["candidate", "production"]
    fields: TopicFields
    origin: Literal["manual", "batch", "brainstorm"]
    created_at: datetime
    updated_at: datetime
    evaluation_status: Literal[
        "not_evaluated",
        "needs_review",
        "pending",
        "scoring",
        "scored",
        "insufficient_evidence",
        "failed",
    ]
    originality: OriginalityView | None = None
    assessment: AssessmentView | None = None
    evaluation_task: ScoreTaskView | None = None
    score_model_ready: bool = False
    source_refs: dict
    history: list[History]
    handed_off: bool = False


class TopicList(Contract):
    items: list[TopicView]
    total: str
    page: int
    page_size: Literal[9] = 9
    model_ready: bool


class GenerationResult(Contract):
    topics: list[TopicFields] = Field(min_length=1, max_length=5)


class GenerationInput(Contract):
    spark_ids: list[UUID]
    instructions: str


class GenerationView(Contract):
    id: UUID
    task_id: UUID
    state: Literal["queued", "running", "succeeded", "failed", "cancel_requested", "cancelled"]
    safe_error_code: str | None
    business_code: Business
    mode: Literal["batch", "brainstorm"]
    saved_topic_id: UUID | None
    result: GenerationResult | None
    input: GenerationInput
    created_at: datetime


class SparkView(Contract):
    id: UUID
    version: int
    text: str
    title: str
    created_at: datetime
    updated_at: datetime


class SparkList(Contract):
    items: list[SparkView]


class HandoffView(Contract):
    id: UUID
    topic_id: UUID
    version: int
    method: Literal["copy", "export"]
