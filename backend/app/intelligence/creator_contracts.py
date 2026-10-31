"""Business-scoped, batch homepage configuration; saving has no external I/O."""

from typing import Literal
from uuid import UUID

from pydantic import Field

from app.contracts.models import Business, Contract


class CreatorQuery(Contract):
    business_code: Business


class CreatorBatch(CreatorQuery):
    links: str = Field(min_length=1, max_length=16000)


class CreatorRemove(CreatorQuery):
    creator_id: UUID


class CreatorLink(Contract):
    id: UUID
    url: str
    platform_uid: str | None = None
    display_name: str | None = None


class CreatorLine(Contract):
    line: int
    state: Literal["added", "duplicate", "invalid", "limit"]
    message: str


class CreatorConfig(Contract):
    business_code: Business
    items: list[CreatorLink]
    results: list[CreatorLine]
