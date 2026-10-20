"""S07.2 HTTP input/output. Existing stable work/material kinds remain authoritative."""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.contracts.models import (
    Business,
    Contract,
    IntakeCreate,
    Material,
    PositiveInt,
    Version,
    Work,
    WorkTarget,
)


class MaterialIntake(Contract):
    title: Annotated[str, Field(min_length=1, max_length=200)]
    material_kind: Material = "reference"
    origin: Literal["text", "link", "upload"]
    body_text: Annotated[str, Field(max_length=200000)] | None = None
    url: Annotated[str, Field(max_length=4000)] | None = None
    file_id: UUID | None = None
    episode_no: PositiveInt | None = None
    artifact_id: UUID | None = None
    expected_artifact_lock_version: Version | None = None

    @model_validator(mode="after")
    def actual_source(self):
        if not self.title.strip() or "\x00" in self.title or "\x00" in (self.body_text or ""):
            raise ValueError("Title required")
        if self.origin == "text" and (
            not (self.body_text or "").strip() or self.url or self.file_id
        ):
            raise ValueError("Exact text source required")
        if self.origin == "link" and (not self.url or self.body_text or self.file_id):
            raise ValueError("Exact link source required")
        if self.origin == "upload" and (not self.file_id or self.body_text or self.url):
            raise ValueError("Exact uploaded source required")
        if bool(self.artifact_id) != bool(self.expected_artifact_lock_version):
            raise ValueError("Version edit requires artifact and lock version")
        return self


class DirectIntake(MaterialIntake):
    target: WorkTarget


class IntelligenceIntake(IntakeCreate):
    pass


class ImportResult(Contract):
    work_id: UUID
    artifact_id: UUID
    artifact_version_id: UUID
    task_id: UUID
    submission_id: UUID
    reused: bool


class ResearchListQuery(Contract):
    business_code: Business
    q: Annotated[str, Field(max_length=200)] = ""
    genre: Annotated[str, Field(max_length=100)] = ""
    status: Literal["all", "processing", "attention", "review", "reported"] = "all"
    page: Annotated[int, Field(ge=1, le=100000)] = 1


class Paragraph(Contract):
    number: PositiveInt
    text: str
    evidence_id: UUID


class Parsing(Contract):
    task_id: UUID
    state: str
    result_state: Literal["completed", "insufficient_evidence", "failed"] | None
    safe_error_code: str | None
    raw_id: UUID | None = None
    paragraphs: list[Paragraph] = Field(default_factory=list)
    media_kind: str | None = None
    duration_ms: int | None = None
    missing_inputs: list[str] = Field(default_factory=list)


class PreliminaryView(Contract):
    quality_grade: str | None
    learning_tags: list[str]
    additional_learning: str | None
    confirmed_genre_tags: list[str]


class SubmissionView(Contract):
    id: UUID
    origin: str
    created_at: str
    assessment: PreliminaryView | None


class VersionView(Contract):
    id: UUID
    version_no: PositiveInt
    title: str | None
    material_kind: Material
    body_text: str | None
    file_id: UUID | None
    content_sha256: str
    episode_no: int | None
    parsing: Parsing | None
    submissions: list[SubmissionView] = Field(default_factory=list)


class MaterialView(Contract):
    id: UUID
    lock_version: Version
    material_number: str
    current_version_id: UUID
    title: str | None
    versions: list[VersionView]
    parsing: Parsing | None


class UnitView(Contract):
    id: UUID
    episode_no: int | None
    title: str | None


class WorkView(Work):
    collected_units: int
    analyzed_units: int
    material_count: int
    processing_count: int
    attention_count: int
    author: str | None = None
    author_id: str | None = None


class WorkDetail(WorkView):
    units: list[UnitView]
    materials: list[MaterialView]


class WorkPage(Contract):
    items: list[WorkView]
    total: int
    page: int
    pages: int
    genres: list[str]
    counts: dict[str, int]
