from datetime import date
from typing import Literal

from pydantic import Field

from app.contracts.models import Business, Contract, Count, FeedItem


class NovelQuery(Contract):
    business_code: Business
    business_date: date
    platform: Literal["all", "fanqie", "qidian"] = "all"
    rank_type: str | None = Field(default=None, max_length=80)
    gender: Literal["male", "female", "all"] | None = None
    genre: str | None = Field(default=None, max_length=100)
    page: int = Field(default=1, ge=1, le=2147483647)
    q: str | None = Field(default=None, max_length=100)


class NovelOption(Contract):
    value: str
    label: str
    disabled: bool = False
    reason: str | None = None


class NovelBoard(Contract):
    platform: Literal["fanqie", "qidian"]
    rank_type: str
    rank_name: str | None = None
    method: str | None = None
    gender: str
    category_id: str
    category_name: str
    rank_version: str | None = None
    code: str
    font_sha256: str | None = None
    name: str | None = None


class NovelItem(Contract):
    item: FeedItem
    work_gender: Literal["male", "female"] | None
    work_genre: str | None
    reader_count: Count | None
    rank: int = Field(ge=1)
    board: NovelBoard


class NovelStatus(Contract):
    platform: Literal["fanqie", "qidian"]
    board: str
    state: str
    http_status: int | None


class NovelFeed(Contract):
    business_code: Business
    business_date: date
    statistics_note: str | None = None
    novel_count: Count | None
    page: int
    page_size: Literal[10]
    total: Count
    items: list[NovelItem]
    rank_types: list[NovelOption]
    genders: list[NovelOption]
    genres: list[NovelOption]
    statuses: list[NovelStatus]
