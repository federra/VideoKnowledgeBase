"""Explicit, current-Shanghai-day refresh. No client URLs, budgets or historic dates."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.models import Business, Contract


class RefreshRequest(Contract):
    business_code: Business


class RefreshChannel(Contract):
    code: Literal["hongguo", "tikhub", "fanqie", "qidian", "creators", "microfilm", "qimao"]
    name: str
    state: Literal["queued", "running", "succeeded", "partial", "failed", "unavailable"]
    completed: int = Field(ge=0)
    total: int = Field(ge=0)
    message: str


class RefreshView(Contract):
    task_id: UUID | None
    business_code: Business
    business_date: date
    state: Literal["idle", "queued", "running", "completed", "partial", "failed"]
    channels: list[RefreshChannel]
