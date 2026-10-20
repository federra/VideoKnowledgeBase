"""S07.3 execution requests; no client-owned model, role or standard activation."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.models import Contract


class AnalysisRequest(Contract):
    input_set_id: UUID
    purpose: Literal["decompose", "evaluate", "predict"] = "decompose"
    execute_now: bool = False
    max_external_calls: int = Field(default=0, strict=True, ge=0, le=1)


class AnalysisAccepted(Contract):
    id: UUID
    kind: Literal["task"] = "task"
    state: str
    execute_now: bool


from datetime import datetime

from app.contracts.models import Evaluation, FrozenPrediction, Report
from app.research.prediction_contracts import DraftView


class ReportEvidence(Contract):
    target_artifact_version_id: UUID | None = None
    target_episode_no: int | None = None
    claim_path: str
    evidence_id: UUID
    raw_asset_id: UUID | None
    artifact_version_id: UUID | None
    paragraph_no: int | None
    quoted_text: str | None


class ReportView(Report):
    evidence: list[ReportEvidence]


class PredictionAssessment(Contract):
    task_id: UUID
    raw_id: UUID
    input_set_id: UUID
    result_state: Literal["insufficient_evidence"]
    uncertainty_note: str
    limitations: list[str]
    created_at: datetime


class AnalysisHistory(Contract):
    reports: list[ReportView]
    evaluations: list[Evaluation]
    prediction_drafts: list[DraftView]
    frozen_predictions: list[FrozenPrediction]
    prediction_assessments: list[PredictionAssessment]
