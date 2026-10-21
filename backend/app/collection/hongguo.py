"""Explicit public Hongguo capture with the existing budget, lease and provenance fences."""

from uuid import UUID, uuid4, uuid5

from app.collection.handler import Collect, publish_batch
from app.collection.service import get, insert
from app.connectors.hongguo import BOARDS, VERSION, normalize_board, parse_comments
from app.core.models import metadata
from app.core.repository import compare_and_swap, create_task
from app.intelligence.service import authorized, row, shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.security.storage import audit
from app.tasks.service import TaskError, input_digest


class CaptureHongguo(Collect):
    def __init__(self, connector):
        # The connector has a durable domain-wide lock/interval, including across organizations.
        super().__init__(connector, min_interval=0)

    def execute_ticket(self, runner, ticket, checkpoint):
        self.connector.capture_job_id = ticket.payload["job_id"]
        return super().execute_ticket(runner, ticket, checkpoint)

    def freeze(self, c, task, az, *, snapshot_id=None):
        org = task["org_id"]
        job = (
            c.exec_driver_sql(
                "SELECT * FROM collection_jobs WHERE org_id=%s AND task_id=%s", (org, task["id"])
            )
            .mappings()
            .one()
        )
        source = az.require("sources", job["source_id"], self.action)
        conn = get(c, "provider_connections", org, job["connection_id"])
        cap, request = job["capability_code"], job["safe_request"]
        board = cap == "hongguo.board"
        if (
            cap not in ("hongguo.board", "hongguo.comments")
            or source["platform_code"] != "hongguo"
            or source["business_code"] != task["business_code"]
            or not source["enabled"]
            or not conn
            or not conn["enabled"]
            or conn["provider_code"] != "hongguo_public"
            or conn["secret_ref"] != "PUBLIC_HONGGUO_NO_SECRET"
            or job["connector_version"] != VERSION
            or job["plan_id"] is not None
            or digest(request) != job["request_sha256"]
            or job["max_requests"] != 1
            or job["max_items"] != (20 if board else 15)
            or task["max_external_calls"] != 1
            or task["max_attempts"] != 1
        ):
            raise TaskError("INVALID_INPUT")
        if board:
            if (
                request != {"board": request.get("board")}
                or request.get("board") not in BOARDS
                or source["board_code"] != request["board"]
                or source["target_kind"] != "board"
            ):
                raise TaskError("INVALID_INPUT")
        else:
            content = row(c, "external_contents", org, source["content_id"])
            inputs = (
                [snapshot_id]
                if snapshot_id
                else c.exec_driver_sql(
                    "SELECT snapshot_id FROM task_inputs WHERE org_id=%s AND task_id=%s ORDER BY position",
                    (org, task["id"]),
                )
                .scalars()
                .all()
            )
            if len(inputs) != 1 or inputs[0] is None:
                raise TaskError("INVALID_INPUT")
            snap = row(c, "intelligence_snapshots", org, inputs[0])
            if (
                not snap["sealed_at"]
                or snap["business_date"] != job["business_date"]
                or snap["business_code"] != task["business_code"]
            ):
                raise TaskError("INVALID_INPUT")
            values = authorized(c, az.p, snap)
            if (
                not any(
                    v["entry"]["observation"]["platform_id"] == content["platform_content_id"]
                    for v in values
                )
                or content["platform_code"] != "hongguo"
                or request != {"series_id": content["platform_content_id"]}
                or source["target_kind"] != "content"
            ):
                raise TaskError("INVALID_INPUT")
        return {
            "job_id": str(job["id"]),
            "source_version": source["lock_version"],
            "connection_version": conn["lock_version"],
            "request": request,
            "capability": cap,
            "maximum": job["max_items"],
            "business_date": str(job["business_date"]),
        }

    def publish(self, c, task, result):
        org = task["org_id"]
        raw = get(c, "raw_assets", org, UUID(result["raw_asset_id"]))
        call = get(c, "collection_calls", org, UUID(result["call_id"]))
        job = get(c, "collection_jobs", org, raw["collection_job_id"])
        if (
            job["task_id"] != task["id"]
            or call["job_id"] != job["id"]
            or raw["collection_call_id"] != call["id"]
            or call["outcome"] != "success"
            or shanghai_date(raw["captured_at"]) != job["business_date"]
        ):
            raise TaskError("INVALID_INPUT")
        if job["capability_code"] == "hongguo.board":
            publish_batch(
                c, task, raw, job, normalize_board(raw["body_text"], job["safe_request"]["board"])
            )
        else:
            source = get(c, "sources", org, job["source_id"])
            comments = parse_comments(raw["body_text"], job["safe_request"]["series_id"])
            for value in comments["comments"]:
                insert(
                    c,
                    "comment_evidence",
                    org,
                    id=uuid5(raw["id"], str(value["sample_position"])),
                    content_id=source["content_id"],
                    raw_asset_id=raw["id"],
                    captured_at=raw["captured_at"],
                    **value,
                )
            c.execute(
                metadata.tables["task_outputs"]
                .insert()
                .values(
                    org_id=org,
                    task_id=task["id"],
                    position=0,
                    role="hongguo_comment_sample",
                    raw_asset_id=raw["id"],
                )
            )
        audit(c, org, task["execution_authorized_by"], "hongguo.captured", "raw_asset", raw["id"])


def submit(
    c,
    p,
    request,
    handler,
    *,
    snapshot_id=None,
    content_id=None,
    business="motion_comic",
    storage_repair=False,
):
    refresh(c, p)
    az = Authorizer(c, p)
    scopes = {("org", str(p.org_id)), ("business", business)}
    if not all(az.allowed(action, scopes) for action in ("source.configure", "collection.run")):
        raise TaskError("ACCESS_DENIED")
    board = "board" in request
    cap = "hongguo.board" if board else "hongguo.comments"
    if board and request.get("board") not in BOARDS:
        raise TaskError("INVALID_INPUT")
    if not board and (not content_id or not snapshot_id):
        raise TaskError("INVALID_INPUT")
    day = shanghai_date()
    # refresh() holds the org lock: creation and URL/day budget are serialized.
    old = (
        c.exec_driver_sql(
            "SELECT task_id,id job_id,source_id FROM collection_jobs WHERE org_id=%s AND business_code=%s AND business_date=%s AND capability_code=%s AND request_sha256=%s ORDER BY created_at DESC LIMIT 1",
            (p.org_id, business, day, cap, digest(request)),
        )
        .mappings()
        .one_or_none()
    )
    repair = False
    if old and storage_repair:
        failed = row(c, "tasks", p.org_id, old["task_id"])
        count = c.exec_driver_sql(
            "SELECT count(*) FROM collection_jobs WHERE org_id=%s AND business_date=%s AND capability_code=%s AND request_sha256=%s AND business_code=%s",
            (p.org_id, day, cap, digest(request), business),
        ).scalar_one()
        raw_count = c.exec_driver_sql(
            "SELECT count(*) FROM raw_assets WHERE org_id=%s AND collection_job_id=%s",
            (p.org_id, old["job_id"]),
        ).scalar_one()
        if (
            board
            and count <= 2
            and not raw_count
            and failed["state"] == "failed"
            and failed["safe_error_code"] == "EXTERNAL_RESULT_UNKNOWN"
        ):
            repair = True
    if old and not repair:
        return {k: str(old[k]) for k in ("task_id", "job_id", "source_id")}
    conn = (
        c.exec_driver_sql(
            "SELECT * FROM provider_connections WHERE org_id=%s AND provider_code='hongguo_public' ORDER BY created_at,id LIMIT 1",
            (p.org_id,),
        )
        .mappings()
        .one_or_none()
    )
    if conn and (not conn["enabled"] or conn["secret_ref"] != "PUBLIC_HONGGUO_NO_SECRET"):
        raise TaskError("SOURCE_UNAVAILABLE")
    connection = (
        conn["id"]
        if conn
        else insert(
            c,
            "provider_connections",
            p.org_id,
            name="红果公开网页",
            provider_code="hongguo_public",
            secret_ref="PUBLIC_HONGGUO_NO_SECRET",
            enabled=True,
        )
    )
    existing = (
        c.exec_driver_sql(
            "SELECT * FROM sources WHERE org_id=%s AND business_code=%s AND platform_code='hongguo' AND target_kind=%s AND board_code IS NOT DISTINCT FROM %s AND content_id IS NOT DISTINCT FROM %s ORDER BY created_at,id LIMIT 1",
            (
                p.org_id,
                business,
                "board" if board else "content",
                request["board"] if board else None,
                content_id,
            ),
        )
        .mappings()
        .one_or_none()
    )
    if existing:
        source = existing["id"]
        az.require("sources", source, "source.configure")
        if not existing["enabled"]:
            compare_and_swap(
                c, "sources", p.org_id, source, existing["lock_version"], {"enabled": True}
            )
    else:
        source = insert(
            c,
            "sources",
            p.org_id,
            name=BOARDS[request["board"]] if board else "红果评论 · " + request["series_id"],
            business_code=business,
            platform_code="hongguo",
            target_kind="board" if board else "content",
            board_code=request["board"] if board else None,
            content_id=content_id,
            enabled=True,
            created_by=p.member_id,
        )
    tid = uuid4()
    job = insert(
        c,
        "collection_jobs",
        p.org_id,
        source_id=source,
        connection_id=connection,
        task_id=tid,
        capability_code=cap,
        connector_version=VERSION,
        business_code=business,
        business_date=day,
        safe_request=request,
        request_sha256=digest(request),
        max_requests=1,
        max_items=20 if board else 15,
    )
    values = {
        "id": tid,
        "org_id": p.org_id,
        "kind": "collect.hongguo",
        "handler_version": VERSION,
        "source_id": source,
        "business_code": business,
        "requested_by": p.member_id,
        "execution_authorized_by": p.member_id,
        "max_attempts": 1,
        "max_external_calls": 1,
        "idempotency_key": str(p.member_id)
        + ":hongguo:"
        + str(day)
        + ":"
        + digest(request)
        + (":storage-repair:" + str(old["task_id"]) if repair else ""),
    }
    # freeze() validates a comment's frozen snapshot even before create_task.
    inputs = [{"role": "comment_board_snapshot", "snapshot_id": snapshot_id}] if snapshot_id else []
    if inputs:
        # create_task needs input_sha first; pass the exact same explicit input through the handler.
        values["input_sha256"] = input_digest(
            values, handler.freeze(c, values, az, snapshot_id=snapshot_id)
        )
    else:
        values["input_sha256"] = input_digest(values, handler.freeze(c, values, az))
    create_task(c, values, inputs)
    audit(c, p.org_id, p.member_id, "hongguo.submitted", "task", tid)
    return {"task_id": str(tid), "job_id": str(job), "source_id": str(source)}
