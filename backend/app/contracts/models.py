"""S05.1 wire contracts. No database access, credentials, or business side effects."""

from datetime import UTC, date, datetime
from typing import Annotated, Literal, TypeVar
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)

Business = Literal["motion_comic", "story_short", "ecommerce_video"]
Material = Literal[
    "topic",
    "script",
    "storyboard_script",
    "storyboard_image",
    "asset",
    "finished_video",
    "reference",
]
TaskState = Literal["queued", "running", "succeeded", "failed", "cancel_requested", "cancelled"]
ResultState = Literal["completed", "insufficient_evidence", "failed"]
Grade = Literal["S", "A", "B", "C"]
NonEmpty = Annotated[
    str,
    StringConstraints(strict=True, min_length=1, max_length=1000),
    AfterValidator(lambda v: v if v.strip() else nonempty_error()),
]


def nonempty_error():
    raise ValueError("Text must contain a non-whitespace character.")


def bigint(value):
    if int(value) > 9223372036854775807:
        raise ValueError("Value exceeds signed bigint.")
    return value


Count = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,18})$"), AfterValidator(bigint)
]
Version = Annotated[
    str, StringConstraints(strict=True, pattern=r"^[1-9][0-9]{0,18}$"), AfterValidator(bigint)
]
DecimalValue = Annotated[
    str, StringConstraints(strict=True, pattern=r"^(0|[1-9][0-9]{0,13})(\.[0-9]{1,6})?$")
]
PositiveInt = Annotated[int, Field(strict=True, gt=0, le=2147483647)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_serializer("*", when_used="json", check_fields=False)
    def utc_values(self, value):
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value


T = TypeVar("T")


class Envelope[T](Contract):
    request_id: UUID
    data: T


class Page[T](Contract):
    items: list[T]
    next_cursor: str | None
    total: Count | None


class Entity(Contract):
    id: UUID
    created_at: AwareDatetime


class MutableEntity(Entity):
    lock_version: Version
    updated_at: AwareDatetime


ErrorCode = Literal[
    "AUTH_REQUIRED",
    "AUTH_INVALID",
    "CSRF_INVALID",
    "ACCESS_DENIED",
    "NOT_FOUND",
    "VALIDATION_FAILED",
    "VERSION_CONFLICT",
    "IDEMPOTENCY_CONFLICT",
    "REVIEW_STALE",
    "CURSOR_EXPIRED",
    "IMMUTABLE_INPUT",
    "STALE_RESULT",
    "BUDGET_EXHAUSTED",
    "EXTERNAL_RESULT_UNKNOWN",
    "CANCEL_UNCONFIRMED",
    "STANDARD_NOT_APPROVED",
    "MODEL_NOT_CONFIGURED",
    "INSUFFICIENT_MATERIAL",
    "DATE_WINDOW_MISMATCH",
    "SOURCE_UNAVAILABLE",
    "FILE_NOT_ACCEPTED",
    "UNSUPPORTED_SOURCE",
    "PROVENANCE_DEPTH_EXCEEDED",
    "RATE_LIMITED",
    "SERVICE_NOT_READY",
    "INTERNAL_ERROR",
    "FILE_TOO_LARGE",
    "INVALID_FILE",
    "UNSAFE_URL",
    "FETCH_FAILED",
    "INVALID_RESPONSE",
]
ERROR_STATUS = {
    "AUTH_REQUIRED": 401,
    "AUTH_INVALID": 401,
    "CSRF_INVALID": 403,
    "ACCESS_DENIED": 403,
    "NOT_FOUND": 404,
    "VALIDATION_FAILED": 422,
    "VERSION_CONFLICT": 409,
    "IDEMPOTENCY_CONFLICT": 409,
    "REVIEW_STALE": 409,
    "CURSOR_EXPIRED": 409,
    "IMMUTABLE_INPUT": 409,
    "STALE_RESULT": 409,
    "BUDGET_EXHAUSTED": 409,
    "EXTERNAL_RESULT_UNKNOWN": 409,
    "CANCEL_UNCONFIRMED": 409,
    "STANDARD_NOT_APPROVED": 409,
    "MODEL_NOT_CONFIGURED": 409,
    "INSUFFICIENT_MATERIAL": 422,
    "DATE_WINDOW_MISMATCH": 409,
    "SOURCE_UNAVAILABLE": 409,
    "FILE_NOT_ACCEPTED": 409,
    "UNSUPPORTED_SOURCE": 422,
    "PROVENANCE_DEPTH_EXCEEDED": 422,
    "RATE_LIMITED": 429,
    "SERVICE_NOT_READY": 503,
    "INTERNAL_ERROR": 500,
    "FILE_TOO_LARGE": 413,
    "INVALID_FILE": 422,
    "UNSAFE_URL": 422,
    "FETCH_FAILED": 502,
    "INVALID_RESPONSE": 502,
}


class ErrorInfo(Contract):
    code: ErrorCode
    message: NonEmpty
    field_paths: list[str] = Field(default_factory=list, max_length=20)


class ErrorEnvelope(Contract):
    request_id: UUID
    error: ErrorInfo


class Login(Contract):
    org_id: UUID
    login_name: NonEmpty
    password: Annotated[
        str, Field(min_length=1, max_length=1024, json_schema_extra={"writeOnly": True})
    ]


class Session(Contract):
    org_id: UUID
    member_id: UUID
    display_name: NonEmpty
    authz_version: Version
    csrf_token: NonEmpty
    expires_at: AwareDatetime
    actions: list[str]  # UI hints only; every operation rechecks object/dependency permission.


class Acknowledged(Contract):
    acknowledged: Literal[True]


class KeywordTarget(Contract):
    kind: Literal["keyword"]
    keyword: Annotated[NonEmpty, Field(max_length=100)]


class AccountTarget(Contract):
    kind: Literal["account"]
    account_id: UUID


class ContentTarget(Contract):
    kind: Literal["content"]
    content_id: UUID


class BoardTarget(Contract):
    kind: Literal["board"]
    board_code: NonEmpty


SourceTarget = Annotated[
    KeywordTarget | AccountTarget | ContentTarget | BoardTarget, Field(discriminator="kind")
]


class SourceCreate(Contract):
    name: NonEmpty
    business_code: Business
    platform_code: Literal["douyin"]
    target: SourceTarget
    enabled: bool = False


class Source(SourceCreate, MutableEntity):
    platform_code: Literal["douyin", "fanqie", "qidian", "hongguo"]
    enabled: bool


class SourcePatch(Contract):
    expected_lock_version: Version
    name: NonEmpty | None = None
    enabled: bool | None = None
    archived: bool | None = None

    @model_validator(mode="after")
    def meaningful_update(self):
        if self.name is None and self.enabled is None and self.archived is None:
            raise ValueError("At least one update is required.")
        return self


Frequency = Literal["daily_0900", "every_2h", "every_4h"]


class ConsoleSourceCreate(Contract):
    name: Annotated[NonEmpty, Field(max_length=90)]
    address: Annotated[NonEmpty, Field(max_length=256)]
    business_code: Business
    frequency: Frequency = "daily_0900"
    purpose: Literal["intelligence", "knowledge", "both"] = "intelligence"
    provider_connection_id: UUID | None = None


class CollectionPlan(Entity):
    lock_version: Version
    enabled: bool
    frequency: Frequency
    purpose: Literal["intelligence", "knowledge", "both"]
    max_requests: int
    max_items: int
    connection_id: UUID


class ConsoleSource(Source):
    archived: bool
    plan: CollectionPlan | None
    last_state: TaskState | None
    last_at: AwareDatetime | None


class CollectionCreate(Contract):
    source_id: UUID
    provider_connection_id: UUID
    capability_code: NonEmpty
    max_requests: Annotated[int, Field(strict=True, ge=1, le=100)] = 1
    max_items: Annotated[int, Field(strict=True, ge=1, le=100)] = 1


class TaskRef(Contract):
    task_id: UUID
    state: TaskState
    lock_version: Version


class Accepted(Contract):
    resource_id: UUID
    task: TaskRef
    reused_existing_task: bool


class OutputRef(Contract):
    kind: Literal[
        "raw_asset",
        "artifact_version",
        "snapshot",
        "feedback",
        "report",
        "evaluation",
        "prediction",
        "knowledge_revision",
        "ai_execution",
        "review_decision",
    ]
    id: UUID


class Task(MutableEntity):
    kind: NonEmpty
    business_code: Business | None
    state: TaskState
    business_outcome: Literal["completed", "insufficient_evidence"] | None
    requested_by: UUID | None
    execution_authorized_by: UUID | None
    max_attempts: PositiveInt
    max_external_calls: Annotated[int, Field(ge=0)]
    available_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    safe_error_code: ErrorCode | None
    outputs: list[OutputRef]


class TaskControl(Contract):
    expected_lock_version: Version
    reason: NonEmpty


class TaskAuthorize(TaskControl):
    max_attempts: PositiveInt = 1
    max_external_calls: Annotated[int, Field(strict=True, ge=0, le=100)] = 0


class ImmutableEntity(Contract):
    id: UUID
    created_at: AwareDatetime


class Snapshot(ImmutableEntity):
    source_id: UUID
    job_id: UUID
    business_code: Business
    business_date: date
    view_kind: Literal["account_discovery", "creator_works", "keyword_works", "board"]
    version_no: PositiveInt
    entry_count: Annotated[int, Field(ge=0)]
    sealed_at: AwareDatetime


class Observation(Contract):
    id: UUID
    kind: Literal["account", "content"]
    platform_code: Literal["douyin", "fanqie", "qidian", "hongguo"]
    platform_id: NonEmpty
    reader_count: Count | None = Field(default=None, exclude_if=lambda value: value is None)
    display_name: str | None
    description: str | None
    original_url: str | None
    follower_count: Count | None
    work_count: Count | None
    like_count: Count | None
    comment_count: Count | None
    share_count: Count | None
    collect_count: Count | None
    repost_count: Count | None
    view_count: Count | None
    observed_at: AwareDatetime
    published_at_raw: str | None
    published_at: AwareDatetime | None


class SnapshotEntry(ImmutableEntity):
    snapshot_id: UUID
    position: Annotated[int, Field(ge=0)]
    provider_rank: PositiveInt | None
    observation: Observation
    feedback_id: UUID | None


class SnapshotPage(Contract):
    snapshot_id: UUID
    page: PositiveInt
    page_size: Annotated[int, Field(ge=1, le=10)]
    total: Count
    items: list[SnapshotEntry]


class FeedOption(Contract):
    id: UUID
    name: str


class VideoGenreGroup(Contract):
    genre: NonEmpty
    subgenres: list[NonEmpty] = Field(default_factory=list)


class FeedItem(Contract):
    comment_sample_count: Annotated[int, Field(ge=0, le=15)] | None = None
    heat_value: Count | None = None
    genre_hierarchy: list[VideoGenreGroup] = Field(default_factory=list)
    heat_display: NonEmpty | None = None
    score_display: NonEmpty | None = None
    genre_tags: list[NonEmpty] = Field(default_factory=list)
    feedback_emotions: list[str] = Field(default_factory=list, max_length=2)
    entry: SnapshotEntry
    source_id: UUID
    source_name: str
    snapshot_version: PositiveInt
    account_id: UUID | None
    author: str | None


class FeedMetrics(Contract):
    videos: Count | None
    creators: Count | None
    comments: Count | None
    likes: Count | None


class InsightEmotion(Contract):
    name: NonEmpty
    count: PositiveInt
    percent: Annotated[int, Field(ge=0, le=100)]


class SampleInsight(Entity):
    business_code: Business
    business_date: date
    feedback_id: UUID
    version_no: PositiveInt
    sample_count: PositiveInt
    classified_count: Annotated[int, Field(ge=0)]
    emotions: list[InsightEmotion]
    motif: str | None
    genre: str | None
    suggestions: list[NonEmpty]
    coverage_note: NonEmpty


class IntelligenceFeed(Contract):
    video_latest_dates: dict[str, date] = Field(default_factory=dict)
    video_genres: list[NonEmpty] = Field(default_factory=list)
    video_subgenres: list[NonEmpty] = Field(default_factory=list)
    keyword_works_count: Count = "0"
    keyword_ranking_status: Literal[
        "not_acquired",
        "no_content_matches",
        "insufficient_metrics",
        "ready",
        "default_order",
        "provider_order",
        "series_order",
    ] = "not_acquired"
    business_code: Business
    business_date: date
    has_snapshot: bool
    metrics: FeedMetrics
    boards: list[FeedOption]
    creators: list[FeedOption]
    page: PositiveInt
    page_size: Literal[10]
    total: Count
    items: list[FeedItem]
    insight: SampleInsight | None = None


class FeedbackClaim(Contract):
    id: UUID
    kind: Literal["emotion", "finding", "expectation", "suggestion"]
    text: NonEmpty
    support_count: Annotated[int, Field(ge=0)]
    comment_ids: list[UUID]
    details: dict = Field(default_factory=dict)


class CommentEvidence(Entity):
    content_id: UUID
    platform_comment_id: str | None
    body_text: str
    username: str | None = None
    like_count: Count | None
    posted_at_raw: str | None
    posted_at: AwareDatetime | None
    captured_at: AwareDatetime


class Feedback(Entity):
    snapshot_id: UUID
    version_no: PositiveInt
    sampling_description: NonEmpty
    sample_count: PositiveInt
    classified_count: Annotated[int, Field(ge=0)]
    coverage_note: NonEmpty
    summary: str | None
    claims: list[FeedbackClaim]
    comments: list[CommentEvidence]


class EntryFeedback(Contract):
    entry_id: UUID
    snapshot_id: UUID
    snapshot_version: PositiveInt
    business_code: Business
    business_date: date
    platform_code: str
    status: Literal["not_acquired", "sampled", "ready"]
    feedback_id: UUID | None
    feedback_version: PositiveInt | None
    sampling_description: str | None
    coverage_note: str | None
    sample_count: Annotated[int, Field(ge=0)] | None
    classified_count: Annotated[int, Field(ge=0)] | None
    comments: list[CommentEvidence]
    claims: list[FeedbackClaim]


class ResearchEvidenceCreate(Contract):
    business_code: Business
    business_date: date
    snapshot_id: UUID
    snapshot_version: PositiveInt
    feedback_id: UUID | None = None
    feedback_version: PositiveInt | None = None

    @model_validator(mode="after")
    def paired_feedback(self):
        if (self.feedback_id is None) != (self.feedback_version is None):
            raise ValueError("Feedback ID and version must be paired")
        return self


class FrozenResearchEvidence(Contract):
    schema_version: Literal[1] = 1
    snapshot: Snapshot
    entry: SnapshotEntry
    content_id: UUID
    feedback: EntryFeedback


class ResearchEvidencePackage(ImmutableEntity):
    frozen_by: UUID
    manifest_sha256: Digest
    body: FrozenResearchEvidence


class WorkCreate(Contract):
    business_code: Business
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    genre_tags: list[NonEmpty] = Field(default_factory=list, max_length=30)
    total_episode_count: PositiveInt | None = None

    @model_validator(mode="after")
    def comic_episodes_only(self):
        if not self.name.strip():
            raise ValueError("Work name required.")
        if self.business_code != "motion_comic" and self.total_episode_count is not None:
            raise ValueError("Only motion comics have episode counts.")
        return self


class Work(WorkCreate, MutableEntity):
    genre_tags: list[NonEmpty]
    total_episode_count: PositiveInt | None
    work_number: NonEmpty
    report_generation: Count
    latest_report_id: UUID | None


class ExistingWork(Contract):
    kind: Literal["existing"]
    work_id: UUID
    expected_lock_version: Version


class NewWork(WorkCreate):
    kind: Literal["new"]


WorkTarget = Annotated[ExistingWork | NewWork, Field(discriminator="kind")]


class Assessment(Contract):
    quality_grade: Grade
    genre_tags: list[NonEmpty] = Field(min_length=1, max_length=30)
    learning_tags: list[NonEmpty] = Field(default_factory=list, max_length=30)
    additional_learning: Annotated[str, Field(max_length=1000)] | None = None
    total_episode_count: PositiveInt | None = None
    episode_no: PositiveInt | None = None

    @model_validator(mode="after")
    def evidence_and_episodes(self):
        if any(not value.strip() for value in self.genre_tags + self.learning_tags):
            raise ValueError("Tags cannot be blank.")
        if not self.learning_tags and not (self.additional_learning or "").strip():
            raise ValueError("At least one learning point required.")
        if (
            self.total_episode_count
            and self.episode_no
            and self.episode_no > self.total_episode_count
        ):
            raise ValueError("Episode exceeds total.")
        return self


class IntakeCreate(Contract):
    snapshot_entry_id: UUID
    feedback_id: UUID | None = None
    target: WorkTarget
    confirmed_business_code: Business
    material_kind: Material
    assessment: Assessment
    cross_business_confirmed: bool = False

    @model_validator(mode="after")
    def business_episode_rules(self):
        if self.confirmed_business_code != "motion_comic" and (
            self.assessment.episode_no is not None
            or self.assessment.total_episode_count is not None
        ):
            raise ValueError("Episode counts only apply to motion comics.")
        if isinstance(self.target, NewWork):
            if self.target.business_code != self.confirmed_business_code:
                raise ValueError("Work and confirmed business must match.")
            if self.target.total_episode_count != self.assessment.total_episode_count:
                raise ValueError("Episode totals must match.")
        return self


class Submission(Entity):
    work_id: UUID
    artifact_version_id: UUID
    snapshot_entry_id: UUID | None
    feedback_id: UUID | None
    confirmed_business_code: Business
    assessment: Assessment | None
    task: TaskRef


class SourceRef(Contract):
    raw_asset_id: UUID
    role: Literal["primary", "reference", "transcript", "frame"]


class ArtifactVersionCreate(Contract):
    artifact_id: UUID
    expected_artifact_lock_version: Version
    title: NonEmpty | None = None
    material_kind: Material
    body_text: str | None = None
    file_id: UUID | None = None
    sources: list[SourceRef] = Field(default_factory=list, max_length=100)
    unit_ids: list[UUID] = Field(default_factory=list, max_length=1000)
    revision_reason: NonEmpty | None = None

    @model_validator(mode="after")
    def actual_input(self):
        if not (self.body_text or "").strip() and self.file_id is None and not self.sources:
            raise ValueError("Actual body, file or source is required.")
        return self


class ArtifactVersion(Entity):
    artifact_id: UUID
    title: str | None
    material_kind: Material
    body_text: str | None
    file_id: UUID | None
    sources: list[SourceRef]
    unit_ids: list[UUID]
    revision_reason: str | None
    version_no: PositiveInt
    content_sha256: Digest
    normalization_version: Literal[1]
    sealed_at: AwareDatetime


class InputItem(Contract):
    artifact_version_id: UUID
    role: Literal["primary", "reference"]
    position: Annotated[int, Field(strict=True, ge=0, le=2147483647)]


class InputSetCreate(Contract):
    work_id: UUID
    scope: Literal["work", "unit", "artifact"]
    unit_id: UUID | None = None
    artifact_id: UUID | None = None
    items: list[InputItem] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def scope_and_primary(self):
        if (self.scope == "unit") != (self.unit_id is not None) or (self.scope == "artifact") != (
            self.artifact_id is not None
        ):
            raise ValueError("Scope must select its exact target.")
        if not any(x.role == "primary" for x in self.items):
            raise ValueError("Primary input required.")
        if len({x.position for x in self.items}) != len(self.items):
            raise ValueError("Duplicate positions.")
        if len({(x.artifact_version_id, x.role) for x in self.items}) != len(self.items):
            raise ValueError("Duplicate inputs.")
        return self


class FrozenParsedSource(Contract):
    raw_asset_id: UUID
    sha256: Digest


class InputSet(InputSetCreate, Entity):
    parsed_sources: dict[str, FrozenParsedSource] = Field(default_factory=dict)
    unit_id: UUID | None
    artifact_id: UUID | None
    business_code: Business
    manifest_sha256: Digest
    normalization_version: Literal[1]
    sealed_at: AwareDatetime


class AnalysisCreate(Contract):
    input_set_id: UUID
    execute_now: bool = False
    max_external_calls: Annotated[int, Field(strict=True, ge=0, le=100)] = 0


class Report(Entity):
    work_id: UUID
    input_set_id: UUID
    version_no: PositiveInt
    coverage_kind: Literal["partial"]
    result_state: Literal["completed", "insufficient_evidence"]
    schema_version: PositiveInt
    body: dict[str, object]  # Versioned AI document, schema resolved in S07.
    missing_inputs: list[dict[str, object]]
    content_sha256: Digest


class Evaluation(Entity):
    input_set_id: UUID
    report_id: UUID | None
    rubric_revision_id: UUID
    result_state: ResultState
    quality_grade: Grade | None
    schema_version: PositiveInt
    dimensions: dict[str, object]
    summary: str | None
    content_sha256: Digest


class Tag(Contract):
    kind: Literal["stage", "task", "genre", "platform"]
    code: NonEmpty


class KnowledgeCreate(Contract):
    title: NonEmpty
    body_text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=1000000),
        AfterValidator(lambda v: v if v.strip() else nonempty_error()),
    ]
    knowledge_type: Literal[
        "fact", "content_atom", "method_rule", "case_experience", "project_related"
    ]
    browse_category: Literal["genre", "quote", "payoff", "failure", "dna_case"]
    business_codes: list[Business] = Field(min_length=1, max_length=3)
    tags: list[Tag] = Field(default_factory=list, max_length=100)
    evidence_ids: list[UUID] = Field(default_factory=list, max_length=100)
    source_report_id: UUID | None = None
    limitations: NonEmpty | None = None


class KnowledgeRevisionCreate(KnowledgeCreate):
    expected_lock_version: Version
    revision_reason: NonEmpty


class KnowledgeRevision(KnowledgeCreate, Entity):
    tags: list[Tag]
    evidence_ids: list[UUID]
    source_report_id: UUID | None
    limitations: NonEmpty | None
    knowledge_id: UUID
    version_no: PositiveInt
    content_sha256: Digest
    sealed_at: AwareDatetime


class KnowledgeSummary(MutableEntity):
    title: NonEmpty
    revision_id: UUID
    publication_id: UUID | None
    browse_category: Literal["genre", "quote", "payoff", "failure", "dna_case"]
    business_codes: list[Business]
    tags: list[Tag]
    state: Literal[
        "draft",
        "pending_ai",
        "ai_error",
        "needs_changes",
        "pending_human",
        "ready_to_publish",
        "published",
    ]


class KnowledgeDetail(KnowledgeSummary):
    revision: KnowledgeRevision


class ReviewCreate(Contract):
    purpose: Literal["knowledge_release", "report_review", "evaluation_review", "standard_approval"]
    target_id: (
        UUID  # purpose determines target table; server persists concrete FK, never loose IDs.
    )
    execute_ai: bool = False
    max_external_calls: Annotated[int, Field(strict=True, ge=0, le=100)] = 0

    @model_validator(mode="after")
    def valid_ai_purpose(self):
        if self.execute_ai and self.purpose in ("evaluation_review", "standard_approval"):
            raise ValueError("This review purpose does not require an additional AI execution.")
        return self


class ReviewRequest(Entity):
    purpose: Literal["knowledge_release", "report_review", "evaluation_review", "standard_approval"]
    target_id: UUID
    input_sha256: Digest
    ai_head_id: UUID | None
    human_head_id: UUID | None
    ai_head_lock_version: Version | None
    human_head_lock_version: Version | None
    task: TaskRef | None


class HumanDecisionCreate(Contract):
    expected_head_id: UUID | None
    expected_head_lock_version: Version | None
    reviewed_ai_decision_id: UUID | None
    verdict: Literal["approved", "rejected", "needs_changes"]
    reason: NonEmpty

    @model_validator(mode="after")
    def head_pair(self):
        if (self.expected_head_id is None) != (self.expected_head_lock_version is None):
            raise ValueError("Head identity and version must both be present or absent.")
        return self


class ReviewDecision(Entity):
    request_id: UUID
    reviewer_kind: Literal["ai", "human"]
    verdict: Literal["approved", "rejected", "needs_changes", "error"]
    reason: NonEmpty
    reviewed_ai_decision_id: UUID | None
    supersedes_decision_id: UUID | None


class PublishCreate(Contract):
    expected_lock_version: Version
    revision_id: UUID
    review_request_id: UUID
    ai_decision_id: UUID
    human_decision_id: UUID


class Publication(Entity):
    knowledge_id: UUID
    revision_id: UUID
    review_request_id: UUID
    ai_decision_id: UUID
    human_decision_id: UUID
    published_at: AwareDatetime


class PredictionFreeze(Contract):
    expected_lock_version: Version


class FrozenPrediction(Entity):
    author_kind: Literal["human", "ai"]
    author_member_id: UUID | None
    conditions: dict[str, object]
    rationale: NonEmpty
    draft_id: UUID
    draft_lock_version: Version
    input_set_id: UUID
    metric_spec_id: UUID
    platform_code: Literal["douyin"]
    account_id: UUID | None
    lower_bound: DecimalValue
    upper_bound: DecimalValue
    window_start_offset_seconds: Count
    window_end_offset_seconds: Count
    context_kind: Literal["prospective_candidate", "retrospective", "unknown"]
    outcome_exposure: Literal["unobserved", "observed", "unknown"]
    frozen_at: AwareDatetime
    confirmed_at: AwareDatetime | None
    retracted_at: AwareDatetime | None
    uncertainty_note: NonEmpty


class FileUploadQuery(Contract):
    work_id: UUID
    expected_work_lock_version: Version
    original_name: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    media_type: Literal["text/plain", "application/pdf", "video/mp4", "image/png", "image/jpeg"]


class FileFromUrl(FileUploadQuery):
    url: Annotated[str, StringConstraints(min_length=1, max_length=2048)]


class FileInfo(Entity):
    original_name: str
    media_type: str
    byte_size: Count
    sha256: Digest
    validation_state: Literal["accepted"]


class FileDownloadQuery(Contract):
    parent_kind: Literal["works", "artifact_versions", "raw_assets"] | None = None
    parent_id: UUID | None = None

    @model_validator(mode="after")
    def paired_parent(self):
        if (self.parent_kind is None) != (self.parent_id is None):
            raise ValueError("Parent kind and ID must be supplied together")
        return self
