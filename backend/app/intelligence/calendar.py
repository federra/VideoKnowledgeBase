"""Month-bounded availability. The calendar is a read, never a collection trigger."""

from datetime import date

from pydantic import Field, field_validator
from sqlalchemy import select

from app.contracts.models import Business, Contract
from app.core.models import metadata
from app.intelligence.read_batch import prepare
from app.intelligence.refresh_visibility import visible_snapshots
from app.intelligence.service import authorized, shanghai_date
from app.security.errors import Denied
from app.security.read_authorizer import ReadAuthorizer


class CalendarQuery(Contract):
    business_code: Business
    month: str = Field(pattern=r"^[0-9]{4}-(0[1-9]|1[0-2])$")

    @field_validator("month")
    @classmethod
    def real_month(cls, value):
        date.fromisoformat(value + "-01")
        return value


class FeedCalendar(Contract):
    business_code: Business
    month: str
    today: date
    dates: list[date]


def calendar(c, p, business, month):
    start = date.fromisoformat(month + "-01")
    today = shanghai_date()
    auth = ReadAuthorizer(c, p)
    # This is the same publication fence and latest-version rule used by selected().
    s = metadata.tables["intelligence_snapshots"]
    sources = metadata.tables["sources"]
    jobs = metadata.tables["collection_jobs"]
    query = (
        select(s, sources.c.platform_code, jobs.c.capability_code)
        .join(sources, (sources.c.org_id == s.c.org_id) & (sources.c.id == s.c.source_id))
        .join(jobs, (jobs.c.org_id == s.c.org_id) & (jobs.c.id == s.c.job_id))
        .where(
            s.c.org_id == p.org_id,
            s.c.business_code == business,
            s.c.business_date >= start,
            s.c.business_date <= today,
            s.c.sealed_at.is_not(None),
            visible_snapshots(),
            s.c.view_kind.in_(("board", "creator_works", "keyword_works")),
            sources.c.platform_code.in_(("douyin", "hongguo", "fanqie", "qidian", "qimao")),
        )
    )
    # Avoid overflowing date.max when querying December 9999.
    if start.year < 9999 or start.month < 12:
        end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
        query = query.where(s.c.business_date < end)
    seen, candidates = set(), []
    for value in c.execute(
        query.order_by(s.c.version_no.desc(), s.c.created_at.desc(), s.c.id.desc())
    ).mappings():
        key = (value["business_date"], value["source_id"], value["view_kind"])
        if key in seen:
            continue
        seen.add(key)  # Empty/withdrawn newest snapshot never falls back to older rows.
        if not value["entry_count"]:
            continue
        if (
            business == "story_short"
            and value["platform_code"] in ("douyin", "hongguo")
            and value["view_kind"] == "board"
            and value["capability_code"] != "douyin.search.microfilm"
        ):
            continue
        candidates.append(dict(value))
    dates = set()
    # Only one readable nonempty source is needed per date. Do not expand every
    # novel board / comments / insight for an availability-only read.
    for snap in candidates:
        if snap["business_date"] in dates:
            continue
        try:
            prepare(c, p, [snap], auth)
            if authorized(c, p, snap, auth):
                dates.add(snap["business_date"])
        except Denied as exc:
            if exc.code not in ("NOT_FOUND", "SOURCE_UNAVAILABLE"):
                raise
    return {"business_code": business, "month": month, "today": today, "dates": sorted(dates)}
