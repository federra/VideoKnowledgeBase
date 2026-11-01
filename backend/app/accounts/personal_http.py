"""Read-only explicit administrator space; never impersonates its owner."""

from fastapi.responses import JSONResponse

from app.accounts import personal_contracts as t
from app.accounts.policy import require_administrator
from app.accounts.service import user_view
from app.contracts.api import Operation, add_operation
from app.contracts.models import Envelope
from app.security.http import preflight
from app.security.sessions import authenticate, refresh
from app.security.storage import audit
from app.topics import service

OPERATIONS = [
    Operation(
        "GET",
        "/users/{member_id}/space",
        "getUserSpace",
        t.PersonalSpaceView,
        ("member.manage",),
        "User spaces",
        query=t.PersonalSpaceQuery,
        implementation="implemented",
    )
]


def space(c, p, member_id, business_code):
    refresh(c, p)
    require_administrator(c, p)
    service.authorize(c, p, business_code)
    member = user_view(c, p, member_id)
    topics = (
        c.exec_driver_sql(
            "SELECT id FROM topic_cards WHERE org_id=%s AND created_by=%s AND business_code=%s ORDER BY created_at DESC,id DESC",
            (p.org_id, member_id, business_code),
        )
        .scalars()
        .all()
    )
    sparks = (
        c.exec_driver_sql(
            "SELECT id FROM topic_sparks WHERE org_id=%s AND owner_member_id=%s ORDER BY updated_at DESC,id DESC",
            (p.org_id, member_id),
        )
        .scalars()
        .all()
    )
    data = {
        "member": member,
        "topics": [service.topic(c, p, ident) for ident in topics],
        "sparks": [service.spark(c, p, ident, allow_admin=True) for ident in sparks],
    }
    audit(c, p.org_id, p.member_id, "member.space.read", "member", member_id)
    return data


def dispatch(*, request, engine, session=None, member_id=None, filters=None):
    with engine.begin() as c:
        p = authenticate(c, session)
        data = space(c, p, member_id, filters.business_code)
    payload = Envelope[t.PersonalSpaceView](request_id=request.state.request_id, data=data)
    return JSONResponse(
        payload.model_dump(mode="json"),
        headers={
            "Cache-Control": "no-store",
            "X-Request-ID": str(request.state.request_id),
        },
    )


def mount(app):
    for spec in OPERATIONS:
        add_operation(spec, app, dispatch, preflight)
