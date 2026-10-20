"""Offline evidence policy. No model/network call or business persistence."""

import hashlib
import json
from datetime import date
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, Field, model_validator

from app.contracts.models import Business, Contract, NonEmpty, PositiveInt


class CommentInput(Contract):
    id: UUID
    platform_comment_id: NonEmpty | None = None
    body_text: Annotated[str, Field(min_length=1, max_length=20000)]
    like_count: Annotated[int, Field(strict=True, ge=0, le=9223372036854775807)] | None = None
    captured_at: AwareDatetime
    posted_at_raw: str | None = None

    @model_validator(mode="after")
    def body_nonblank(self):
        if not self.body_text.strip():
            raise ValueError("Empty comment")
        return self


class FeedbackInput(Contract):
    business_code: Business
    business_date: date
    snapshot_id: UUID
    snapshot_version: PositiveInt
    entry_id: UUID
    platform_code: Literal["douyin"]
    sampling_description: NonEmpty
    comments: Annotated[list[CommentInput], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def same_day_deduplicated(self):
        ids, platform_ids = set(), set()
        for comment in self.comments:
            if comment.id in ids or (
                comment.platform_comment_id and comment.platform_comment_id in platform_ids
            ):
                raise ValueError("Duplicate comment identity")
            ids.add(comment.id)
            if comment.platform_comment_id:
                platform_ids.add(comment.platform_comment_id)
            if (
                comment.captured_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
                != self.business_date
            ):
                raise ValueError("Comment capture date mismatch")
        return self


class Claim(Contract):
    claim_key: NonEmpty
    text: NonEmpty
    comment_ids: Annotated[list[UUID], Field(min_length=1, max_length=20)]


class Emotion(Claim):
    kind: Literal["emotion"]
    trigger: NonEmpty


class Finding(Claim):
    kind: Literal["finding"]
    dimension: Literal["剧情", "人物", "世界观", "节奏", "金句", "视听表达", "商品场景"]
    polarity: Literal["受欢迎点", "问题点"]


class Expectation(Claim):
    kind: Literal["expectation"]
    basis: Literal["明确表达", "系统推测"]


class Suggestion(Claim):
    kind: Literal["suggestion"]
    priority: Literal["优先", "次优先"]
    stage: Literal["选题", "脚本", "资产", "成片"]
    reason: NonEmpty
    change: NonEmpty
    verify: NonEmpty


class FeedbackOutput(Contract):
    result_state: Literal["completed", "insufficient_evidence"]
    summary: NonEmpty | None
    claims: Annotated[
        list[Annotated[Emotion | Finding | Expectation | Suggestion, Field(discriminator="kind")]],
        Field(max_length=40),
    ]


def freeze_input(value: FeedbackInput):
    body = value.model_dump(mode="json")
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return {"input": body, "sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def inspect_output(sample: FeedbackInput, value):
    result = FeedbackOutput.model_validate(value)
    if (result.result_state == "completed") != bool(result.claims):
        raise ValueError("Result state and supported claims disagree")
    if result.result_state == "insufficient_evidence" and result.summary is not None:
        raise ValueError("Insufficient evidence cannot support a summary")
    available = {x.id for x in sample.comments}
    keys, classified, emotions, counts = set(), set(), {}, {}
    for claim in result.claims:
        refs = set(claim.comment_ids)
        if len(refs) != len(claim.comment_ids) or not refs <= available or claim.claim_key in keys:
            raise ValueError("Invalid claim evidence")
        keys.add(claim.claim_key)
        counts[claim.claim_key] = len(refs)
        if claim.kind == "emotion":
            classified |= refs
            emotions.setdefault(claim.text, set()).update(refs)
    denominator = len(classified)
    return {
        "output": result.model_dump(mode="json"),
        "sample_count": len(sample.comments),
        "classified_count": denominator,
        "support_counts": counts,
        "emotions": [
            {"name": name, "count": len(refs), "percent": int(len(refs) / denominator * 100 + 0.5)}
            for name, refs in sorted(emotions.items(), key=lambda x: -len(x[1]))
        ],
        "top_comment_ids": [
            str(x.id)
            for x in sorted(
                sample.comments,
                key=lambda x: (x.like_count is None, -(x.like_count or 0)),
            )[:5]
        ],
    }
