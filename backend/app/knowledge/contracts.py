"""Review detail and same-transaction Demo approval contract."""

from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.models import (
    Business,
    Contract,
    KnowledgeCreate,
    KnowledgeDetail,
    NonEmpty,
    ReviewDecision,
    ReviewRequest,
    Version,
)


class ReviewView(ReviewRequest):
    decisions: list[ReviewDecision]


class ApprovePublish(Contract):
    expected_lock_version: Version
    expected_head_id: UUID | None
    expected_head_lock_version: Version | None
    reviewed_ai_decision_id: UUID
    reason: NonEmpty

    @model_validator(mode="after")
    def head_pair(self):
        if (self.expected_head_id is None) != (self.expected_head_lock_version is None):
            raise ValueError("Head identity and version must both be present or absent.")
        return self


class ExtractCreate(Contract):
    execute_now: bool = False
    max_external_calls: int = Field(default=0, strict=True, ge=0, le=1)


class KnowledgeView(KnowledgeDetail):
    review_request_id: UUID | None


class ManualSource(Contract):
    """Explicit human supplied original text, never independently verified by ingestion."""

    body_text: str = Field(min_length=1, max_length=12000)
    attribution: NonEmpty

    @model_validator(mode="after")
    def original_text(self):
        import re

        if not self.body_text.strip() or re.fullmatch(r"https?://\S+", self.body_text.strip()):
            raise ValueError("Original text is required; a source URL alone is insufficient.")
        return self


class KnowledgeWrite(KnowledgeCreate):
    manual_source: ManualSource | None = None


class KnowledgeRevisionWrite(KnowledgeWrite):
    expected_lock_version: Version
    revision_reason: NonEmpty


class KnowledgeSource(Contract):
    id: UUID
    raw_asset_id: UUID | None
    artifact_version_id: UUID | None
    locator_kind: str
    paragraph_no: int | None
    page_no: int | None
    start_ms: int | None
    end_ms: int | None
    quoted_text: str | None
    origin: str
    independently_verified: bool
    attribution: str | None
    target_artifact_version_id: UUID | None
    work_id: UUID | None
    episode_no: int | None
    material_version_no: int | None
    business_code: Business | None


class KnowledgeSources(Contract):
    revision_id: UUID
    knowledge_id: UUID
    source_report_id: UUID | None
    items: list[KnowledgeSource]
