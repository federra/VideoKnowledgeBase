"""Same-transaction topic/spark commands; all read boundaries remain authenticated."""

from uuid import UUID, uuid4

from sqlalchemy import select

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import compare_and_swap
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit, lock_org, receipt
from app.topics.contracts import TopicFields


def authorize(c, p, business=None, action="content.read", *, auth=None):
    if auth is None:
        refresh(c, p)
    if business is not None and business not in ("motion_comic", "story_short"):
        raise Denied("VALIDATION_FAILED")
    scopes = {("org", str(p.org_id))}
    if business:
        scopes.add(("business", business))
    if not (auth or Authorizer(c, p)).allowed(action, scopes):
        raise Denied("ACCESS_DENIED")


def row(c, p, kind, ident, *, auth=None):
    if auth is not None:
        return auth.memo(("topic.row", kind, ident), lambda: row(c, p, kind, ident))
    t = metadata.tables[kind]
    x = c.execute(select(t).where(t.c.org_id == p.org_id, t.c.id == ident)).mappings().one_or_none()
    if x is None:
        raise Denied("NOT_FOUND")
    return x


def require_owner(p, card):
    if card["created_by"] != p.member_id:
        raise Denied("NOT_FOUND")


def can_read_personal(c, p, owner):
    if owner == p.member_id:
        return True
    from app.accounts.policy import is_administrator

    return is_administrator(c, p)


def check_sources(c, p, refs, *, allow_admin=False, az=None):
    az = az or Authorizer(c, p)
    from app.security.read_authorizer import ReadAuthorizer

    read_auth = az if isinstance(az, ReadAuthorizer) else None
    for x in refs.get("sparks", []):
        sp = row(c, p, "topic_sparks", UUID(x["id"]), auth=read_auth)
        if sp["owner_member_id"] != p.member_id and not (
            allow_admin and can_read_personal(c, p, sp["owner_member_id"])
        ):
            raise Denied("NOT_FOUND")
        r = row(c, p, "topic_spark_revisions", UUID(x["revision_id"]), auth=read_auth)
        if r["spark_id"] != sp["id"]:
            raise Denied("SOURCE_UNAVAILABLE")
    for x in refs.get("knowledge", []):
        az.read("knowledge_revisions", UUID(x["revision_id"]))
    for x in refs.get("intelligence", []):
        from app.intelligence.service import authorized

        sid = UUID(x["snapshot_id"])

        def verify_snapshot(sid=sid):
            snap = row(c, p, "intelligence_snapshots", sid, auth=read_auth)
            authorized(c, p, snap, auth=read_auth)
            from app.intelligence.refresh_visibility import visible_snapshots

            t = metadata.tables["intelligence_snapshots"]
            if not c.execute(
                select(t.c.id).where(t.c.org_id == p.org_id, t.c.id == sid, visible_snapshots())
            ).first():
                raise Denied("SOURCE_UNAVAILABLE")
            return True

        if read_auth is not None:
            read_auth.memo(("topic.source.snapshot", sid), verify_snapshot)
        else:
            verify_snapshot()
        az.read("raw_assets", UUID(x["raw_asset_id"]))


def topic(c, p, ident, *, auth=None):
    from app.security.read_authorizer import ReadAuthorizer

    auth = auth or ReadAuthorizer(c, p)
    a = row(c, p, "topic_cards", ident, auth=auth)
    authorize(c, p, a["business_code"], auth=auth)
    if not can_read_personal(c, p, a["created_by"]):
        raise Denied("NOT_FOUND")
    r = row(c, p, "topic_revisions", a["current_revision_id"], auth=auth)
    check_sources(c, p, r["source_refs"], allow_admin=True, az=auth)
    if a["created_by"] != p.member_id:
        audit(c, p.org_id, p.member_id, "topic.personal.read", "topic", ident)
    history = c.exec_driver_sql(
        "SELECT version_no,fields,created_at FROM topic_revisions WHERE org_id=%s AND topic_id=%s ORDER BY version_no DESC",
        (p.org_id, ident),
    ).mappings()
    return {
        "id": a["id"],
        "business_code": a["business_code"],
        "version": r["version_no"],
        "status": a["status"],
        "fields": r["fields"],
        "origin": r["origin"],
        "source_refs": r["source_refs"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        **_quality_projection(c, p, a, r, auth=auth),
        "handed_off": bool(
            c.exec_driver_sql(
                "SELECT 1 FROM topic_handoffs WHERE org_id=%s AND topic_id=%s AND topic_revision_id=%s LIMIT 1",
                (p.org_id, ident, a["current_revision_id"]),
            ).first()
        ),
        "history": [
            {"version": x["version_no"], "fields": x["fields"], "created_at": x["created_at"]}
            for x in history
        ],
    }


def _quality_projection(c, p, card, revision, *, auth=None):
    from app.topics.quality import screen
    from app.topics.scoring import projection

    return {
        "originality": screen(revision["fields"], revision["source_refs"]),
        **projection(c, p, card, revision, auth=auth),
    }


def _guard_edit(fields, refs):
    from app.topics.quality import screen

    if screen(fields, refs)["status"] == "risk":
        raise Denied("ORIGINALITY_RISK")


def listing(c, p, business, pool, page, q=None, status="all"):
    from app.security.read_authorizer import ReadAuthorizer

    auth = ReadAuthorizer(c, p)
    authorize(c, p, business, auth=auth)
    ids = (
        c.exec_driver_sql(
            "SELECT id FROM topic_cards WHERE org_id=%s AND created_by=%s AND business_code=%s AND status=%s ORDER BY created_at DESC,id DESC",
            (p.org_id, p.member_id, business, "candidate" if pool == "candidate" else "production"),
        )
        .scalars()
        .all()
    )
    items = []
    for ident in ids:
        try:
            item = topic(c, p, ident, auth=auth)
            text = " ".join(item["fields"].values()).casefold()
            if q and q.strip().casefold() not in text:
                continue
            if (
                status == "pending"
                and item["handed_off"]
                or status == "handed_off"
                and not item["handed_off"]
            ):
                continue
            items.append(item)
        except Denied as e:
            if e.code not in ("NOT_FOUND", "ACCESS_DENIED", "SOURCE_UNAVAILABLE"):
                raise
    from app.model_config import resolve

    try:
        resolve(c, p, business, "topic")
        ready = True
    except Denied:
        ready = False
    return {
        "items": items[(page - 1) * 9 : page * 9],
        "total": str(len(items)),
        "page": page,
        "page_size": 9,
        "model_ready": ready,
    }


def add(c, p, business, fields, origin="manual", source_refs=None, generation_task_id=None):
    authorize(c, p, business, "content.write")
    lock_org(c, p.org_id)
    refs = source_refs or {}
    check_sources(c, p, refs)
    body = TopicFields.model_validate(fields).model_dump()
    _guard_edit(body, refs)
    tid, rid = uuid4(), uuid4()
    insert(
        c,
        "topic_cards",
        p.org_id,
        id=tid,
        business_code=business,
        status="candidate",
        current_revision_id=rid,
        created_by=p.member_id,
    )
    insert(
        c,
        "topic_revisions",
        p.org_id,
        id=rid,
        topic_id=tid,
        version_no=1,
        fields=body,
        origin=origin,
        source_refs=refs,
        generation_task_id=generation_task_id,
        content_sha256=digest(body),
        created_by=p.member_id,
    )
    audit(c, p.org_id, p.member_id, "topic.created", "topic", tid)
    return tid


def create(c, p, key, request):
    authorize(c, p, request.business_code, "content.write")
    result = receipt(
        c,
        p,
        "createTopic",
        key,
        request.model_dump(mode="json"),
        lambda: {"id": str(add(c, p, request.business_code, request.fields.model_dump()))},
    )
    return topic(c, p, UUID(result["id"]))


def revise(c, p, key, ident, request):
    a = row(c, p, "topic_cards", ident)
    require_owner(p, a)
    authorize(c, p, a["business_code"], "content.write")

    def perform():
        a = row(c, p, "topic_cards", ident)
        old = row(c, p, "topic_revisions", a["current_revision_id"])
        check_sources(c, p, old["source_refs"])
        if old["version_no"] != request.expected_version:
            raise Denied("VERSION_CONFLICT")
        fields = request.fields.model_dump()
        if fields != old["fields"]:
            _guard_edit(fields, old["source_refs"])
            if old["generation_task_id"]:
                import json

                from app.tasks.service import TaskError
                from app.topics.generation_v2 import validate_saved_creation

                task = row(c, p, "tasks", old["generation_task_id"])
                if task["kind"] == "topic.generate" and task["handler_version"] == "2":
                    data = json.loads(row(c, p, "raw_assets", task["raw_asset_id"])["body_text"])
                    try:
                        validate_saved_creation(c, p, task, data, fields)
                    except TaskError as exc:
                        raise Denied(exc.code) from None
                    except ValueError:
                        raise Denied("VALIDATION_FAILED") from None
            rid = insert(
                c,
                "topic_revisions",
                p.org_id,
                topic_id=ident,
                version_no=old["version_no"] + 1,
                fields=fields,
                origin=old["origin"],
                source_refs=old["source_refs"],
                generation_task_id=old["generation_task_id"],
                content_sha256=digest(fields),
                created_by=p.member_id,
            )
            compare_and_swap(
                c, "topic_cards", p.org_id, ident, a["lock_version"], {"current_revision_id": rid}
            )
            audit(c, p.org_id, p.member_id, "topic.revised", "topic", ident)
        return {"id": str(ident)}

    result = receipt(
        c, p, "reviseTopic", key, {"id": str(ident), **request.model_dump(mode="json")}, perform
    )
    return topic(c, p, UUID(result["id"]))


def choose(c, p, key, ident, request):
    a = row(c, p, "topic_cards", ident)
    require_owner(p, a)
    authorize(c, p, a["business_code"], "content.write")

    def perform():
        a = row(c, p, "topic_cards", ident)
        v = topic(c, p, ident)
        if v["version"] != request.expected_version:
            raise Denied("VERSION_CONFLICT")
        if a["status"] != "production" or a["selected_revision_id"] != a["current_revision_id"]:
            compare_and_swap(
                c,
                "topic_cards",
                p.org_id,
                ident,
                a["lock_version"],
                {"status": "production", "selected_revision_id": a["current_revision_id"]},
            )
            audit(c, p.org_id, p.member_id, "topic.selected", "topic", ident)
        return {"id": str(ident)}

    result = receipt(
        c, p, "selectTopic", key, {"id": str(ident), **request.model_dump(mode="json")}, perform
    )
    return topic(c, p, UUID(result["id"]))


def handoff(c, p, key, ident, request):
    a = row(c, p, "topic_cards", ident)
    require_owner(p, a)
    authorize(c, p, a["business_code"], "content.export")

    def perform():
        a = row(c, p, "topic_cards", ident)
        v = topic(c, p, ident)
        if (
            v["version"] != request.expected_version
            or a["status"] != "production"
            or a["selected_revision_id"] != a["current_revision_id"]
        ):
            raise Denied("VERSION_CONFLICT")
        if request.phase == "authorize":
            return {
                "id": str(uuid4()),
                "topic_id": str(ident),
                "version": v["version"],
                "method": request.method,
            }
        hid = insert(
            c,
            "topic_handoffs",
            p.org_id,
            topic_id=ident,
            topic_revision_id=a["current_revision_id"],
            method=request.method,
            created_by=p.member_id,
        )
        audit(c, p.org_id, p.member_id, "topic.handed_off", "topic", ident)
        return {
            "id": str(hid),
            "topic_id": str(ident),
            "version": v["version"],
            "method": request.method,
        }

    if request.phase == "authorize":
        # A clipboard/download failure can retry the same intent after another
        # window edits the card. Authorization is a live check, never a cached
        # receipt; only recording the completed handoff is idempotent.
        lock_org(c, p.org_id)
        return perform()
    return receipt(
        c,
        p,
        "handoffTopic/" + request.phase,
        key,
        {"id": str(ident), **request.model_dump(mode="json")},
        perform,
    )


def spark(c, p, ident, *, allow_admin=False):
    authorize(c, p)
    a = row(c, p, "topic_sparks", ident)
    if (
        a["deleted_at"] is not None
        or a["owner_member_id"] != p.member_id
        and not (allow_admin and can_read_personal(c, p, a["owner_member_id"]))
    ):
        raise Denied("NOT_FOUND")
    r = row(c, p, "topic_spark_revisions", a["current_revision_id"])
    return {
        "id": a["id"],
        "version": r["version_no"],
        "text": r["text"],
        "title": r["title"],
        "color": r["color"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
    }


def sparks(c, p):
    authorize(c, p)
    ids = c.exec_driver_sql(
        "SELECT id FROM topic_sparks WHERE org_id=%s AND owner_member_id=%s AND deleted_at IS NULL ORDER BY updated_at DESC,id DESC",
        (p.org_id, p.member_id),
    ).scalars()
    return {"items": [spark(c, p, x) for x in ids]}


def save_spark(c, p, key, request):
    authorize(c, p, action="content.write")

    def perform():
        text = request.text
        title = text.splitlines()[0][:90]
        if request.id:
            old = spark(c, p, request.id)
            a = row(c, p, "topic_sparks", request.id)
            if old["version"] != request.expected_version:
                raise Denied("VERSION_CONFLICT")
            color = request.color or old["color"]
            if old["text"] != text or old["color"] != color:
                rid = insert(
                    c,
                    "topic_spark_revisions",
                    p.org_id,
                    spark_id=request.id,
                    version_no=old["version"] + 1,
                    text=text,
                    title=title,
                    color=color,
                    created_by=p.member_id,
                )
                compare_and_swap(
                    c,
                    "topic_sparks",
                    p.org_id,
                    request.id,
                    a["lock_version"],
                    {"current_revision_id": rid},
                )
            return {"id": str(request.id)}
        sid, rid = uuid4(), uuid4()
        insert(
            c,
            "topic_sparks",
            p.org_id,
            id=sid,
            owner_member_id=p.member_id,
            current_revision_id=rid,
        )
        insert(
            c,
            "topic_spark_revisions",
            p.org_id,
            id=rid,
            spark_id=sid,
            version_no=1,
            text=text,
            title=title,
            color=request.color or "violet",
            created_by=p.member_id,
        )
        audit(c, p.org_id, p.member_id, "spark.created", "spark", sid)
        return {"id": str(sid)}

    result = receipt(
        c,
        p,
        "saveSpark",
        key,
        request.model_dump(mode="json", exclude={"color"} if request.color is None else None),
        perform,
    )
    return spark(c, p, UUID(result["id"]))


def remove_spark(c, p, key, request):
    authorize(c, p, action="content.write")

    def perform():
        note = spark(c, p, request.id)
        if note["version"] != request.expected_version:
            raise Denied("VERSION_CONFLICT")
        identity = row(c, p, "topic_sparks", request.id)
        deleted_at = c.exec_driver_sql("SELECT now()").scalar_one()
        compare_and_swap(
            c,
            "topic_sparks",
            p.org_id,
            request.id,
            identity["lock_version"],
            {"deleted_at": deleted_at},
        )
        audit(c, p.org_id, p.member_id, "spark.deleted", "spark", request.id)
        return {"id": str(request.id)}

    return receipt(c, p, "removeSpark", key, request.model_dump(mode="json"), perform)
