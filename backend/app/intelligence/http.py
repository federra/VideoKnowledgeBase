from uuid import UUID

from fastapi.responses import JSONResponse

from app.contracts.api import OPERATIONS, add_operation
from app.contracts.models import Envelope
from app.intelligence.feedback import entry_feedback, read_feedback
from app.intelligence.handoff import create_handoff, read_handoff
from app.intelligence.service import entries, feed, snapshots
from app.security.errors import Denied
from app.security.http import preflight
from app.security.sessions import authenticate


def dispatch(
    *,
    request,
    engine,
    session=None,
    filters=None,
    snapshot_id=None,
    feedback_id=None,
    entry_id=None,
    handoff_id=None,
    body=None,
    idempotency_key=None,
    csrf_token=None,
):
    spec = next(s for s in OPERATIONS if s.name == request.scope["route"].operation_id)
    with engine.begin() as c:
        # One consistent DB view for options, metrics, count and rows; concurrent grants
        # are serialized by refresh's org lock, while collection publishes hold that lock too.
        p = authenticate(c, session)
        if spec.name == "freezeResearchEvidence":
            data = create_handoff(
                c, p, entry_id, body, str(idempotency_key), request.state.request_id
            )
        elif spec.name == "getResearchEvidence":
            data = read_handoff(c, p, handoff_id)
        elif spec.name == "getFeedback":
            data = read_feedback(c, p, feedback_id)
        elif spec.name == "getEntryFeedback":
            data = entry_feedback(c, p, entry_id, filters.business_code, filters.business_date)
        elif spec.name == "getNovelFeed":
            from app.intelligence.novels import feed as novels

            data = novels(
                c,
                p,
                filters.business_code,
                filters.business_date,
                platform=filters.platform,
                rank_type=filters.rank_type,
                gender=filters.gender,
                genre=filters.genre,
                page=filters.page,
                q=filters.q,
            )
        elif spec.name == "listSnapshots":
            data = snapshots(
                c,
                p,
                filters.business_code,
                filters.business_date,
                filters.source_id,
                filters.view_kind,
            )
        elif spec.name == "listSnapshotEntries":
            data = entries(
                c, p, snapshot_id, filters.page, filters.page_size, filters.q, filters.account_id
            )
        else:
            accounts = None
            if filters.accounts:
                try:
                    accounts = {str(UUID(x)) for x in filters.accounts.split(",")}
                except ValueError:
                    raise Denied("VALIDATION_FAILED") from None
                if len(accounts) > 100:
                    raise Denied("VALIDATION_FAILED")
            data = feed(
                c,
                p,
                filters.business_code,
                filters.business_date,
                filters.lane,
                filters.page,
                filters.q,
                filters.source_id,
                accounts,
                video_catalog=filters.video_catalog,
                video_board=filters.video_board,
                video_genre=filters.video_genre,
                video_subgenre=filters.video_subgenre,
            )
    payload = Envelope[spec.response](request_id=request.state.request_id, data=data)
    return JSONResponse(
        payload.model_dump(mode="json"),
        status_code=spec.status,
        headers={"X-Request-ID": str(payload.request_id), "Cache-Control": "no-store"},
    )


def mount(app):
    for spec in OPERATIONS:
        if spec.name in (
            "getIntelligenceFeed",
            "getNovelFeed",
            "listSnapshots",
            "listSnapshotEntries",
            "getFeedback",
            "getEntryFeedback",
            "freezeResearchEvidence",
            "getResearchEvidence",
        ):
            add_operation(spec, app, dispatch, preflight)
