"""Explicit monitored-creator refresh using only free Douyin JSON endpoints."""

from uuid import uuid4

from app.collection.creator_series import CreatorSeries
from app.collection.service import identity, insert
from app.connectors import douyin_public_http
from app.connectors.douyin_public_http import PublicDouyin
from app.connectors.douyin_series import CAPABILITY, MAX_CALLS, POLICY, VERSION
from app.core.repository import compare_and_swap, create_task
from app.intelligence.creator_resolution import Resolve, run_resolution
from app.intelligence.creators import active, known_account
from app.intelligence.refresh_worker import child_key
from app.intelligence.service import row, shanghai_date
from app.security.authorization import Authorizer
from app.security.primitives import digest
from app.security.sessions import refresh
from app.tasks.service import Runner, TaskError, input_digest


def collect_creators(channels):
    checkpoint(channels)
    entries = channels.ticket.payload.get("creators", [])
    if not entries:
        return "unavailable", "当前业务线未配置博主主页"
    channels.begin(len(entries))
    done, failed, partial = 0, 0, 0
    for entry in entries:
        channels.checkpoint()
        with channels.runner.engine.connect() as c:
            if not active(c, channels.p.org_id, channels.ticket.payload["business"], entry):
                failed += 1
                continue
            uid, evidence = known_account(c, channels.p, entry["url"])
        try:
            if not uid:
                # Identity is proved by this creator's real short-drama directory authors.
                connector = PublicDouyin()

                connector.before_request = lambda: checkpoint(channels)

                def resolve(url, connector=connector):
                    return douyin_public_http.resolve(url, connector)

                run_resolution(
                    channels, entry, Resolve(resolve, douyin_public_http.parse_identity, VERSION)
                )
                with channels.runner.engine.connect() as c:
                    uid, evidence = known_account(c, channels.p, entry["url"])
            if not uid:
                raise TaskError("INVALID_RESPONSE")
            outcome = run_creator(channels, entry, uid, evidence)
            partial += outcome == "insufficient_evidence"
            done += 1
            channels.completed = done
            channels.progress(
                "creators", "running", done, len(entries), "已保存完整短剧目录TOP10及第1集评论"
            )
        except TaskError as exc:
            if exc.code in ("ACCESS_REVOKED", "DATE_WINDOW_MISMATCH"):
                raise
            failed += 1
            if exc.code in ("SOURCE_UNAVAILABLE", "RATE_LIMITED", "EXTERNAL_RESULT_UNKNOWN"):
                break
    failed = len(entries) - done
    return (
        "partial" if done and (failed or partial) else "succeeded" if done else "failed",
        f"已保存{done}位博主的短剧TOP10；其中{partial}位评论受限，成功样本每部≤15条；{failed}位目录未完成，旧数据保留；免费HTTP，无付费API",
    )


def run_creator(channels, entry, uid, evidence, *, posts_connector=None):
    checkpoint(channels)
    org, business = channels.p.org_id, channels.ticket.payload["business"]
    capability, version, policy, calls, maximum = CAPABILITY, VERSION, POLICY, MAX_CALLS, 10
    kind, prefix, provider, secret = (
        "collect.creator-series",
        "博主短剧 · ",
        "douyin_public",
        "PUBLIC_DOUYIN_NO_SECRET",
    )
    if posts_connector is not None:
        from app.collection.creator_posts import CreatorPosts
        from app.connectors import douyin_posts as posts

        capability, version, policy, calls, maximum = (
            posts.CAPABILITY,
            posts.VERSION,
            posts.POLICY,
            posts.MAX_PAGES,
            posts.MAX_ITEMS,
        )
        kind, prefix, provider, secret = (
            "collect.creator-posts",
            "博主近七日视频 · ",
            "douyin_session",
            "LOCAL_DOUYIN_BROWSER_SESSION",
        )
    request = {
        "entry": entry,
        "sec_user_id": entry["url"].rsplit("/", 1)[-1],
        "uid": uid,
        "identity_evidence": str(evidence),
        "policy": policy,
    }
    if posts_connector is not None:
        request["window"] = channels.ticket.payload["creator_window"]
    handler = CreatorSeries(PublicDouyin(), parent_checkpoint=lambda: checkpoint(channels))
    if posts_connector is not None:
        handler = CreatorPosts(posts_connector, parent_checkpoint=lambda: checkpoint(channels))
    key = child_key(
        getattr(channels, "resume_batch", channels.ticket.task), "creators", capability, request
    )
    with channels.runner.engine.begin() as c:
        refresh(c, channels.p)
        if not channels.runner.live(c, channels.ticket) or not active(c, org, business, entry):
            raise TaskError("ACCESS_REVOKED")
        source = None
        existing = (
            c.exec_driver_sql(
                "SELECT t.id,j.source_id FROM tasks t JOIN collection_jobs j ON j.task_id=t.id AND j.org_id=t.org_id WHERE t.org_id=%s AND t.idempotency_key=%s",
                (org, key),
            )
            .mappings()
            .one_or_none()
        )
        if existing:
            tid, source = existing["id"], existing["source_id"]
        else:
            conn = c.exec_driver_sql(
                "SELECT id FROM provider_connections WHERE org_id=%s AND provider_code=%s ORDER BY created_at LIMIT 1",
                (org, provider),
            ).scalar_one_or_none()
            if conn is None:
                conn = insert(
                    c,
                    "provider_connections",
                    org,
                    name="抖音独立会话作品JSON"
                    if posts_connector is not None
                    else "抖音公开短剧JSON",
                    provider_code=provider,
                    secret_ref=secret,
                    enabled=True,
                )
            connection = row(c, "provider_connections", org, conn)
            if not connection["enabled"] or connection["secret_ref"] != secret:
                raise TaskError("SOURCE_UNAVAILABLE")
            account = identity(c, "external_accounts", org, "platform_uid", uid)
            source = c.exec_driver_sql(
                "SELECT id FROM sources WHERE org_id=%s AND business_code=%s AND platform_code='douyin' AND account_id=%s AND name LIKE %s AND archived_at IS NULL ORDER BY created_at LIMIT 1",
                (org, business, account, prefix + "%"),
            ).scalar_one_or_none()
            if source is None:
                source = insert(
                    c,
                    "sources",
                    org,
                    name=prefix + uid,
                    business_code=business,
                    platform_code="douyin",
                    target_kind="account",
                    account_id=account,
                    enabled=False,
                    created_by=channels.p.member_id,
                )
            az = Authorizer(c, channels.p)
            src = az.require("sources", source, "source.configure")
            if not src["enabled"]:
                compare_and_swap(c, "sources", org, source, src["lock_version"], {"enabled": True})
            tid = uuid4()
            insert(
                c,
                "collection_jobs",
                org,
                task_id=tid,
                source_id=source,
                connection_id=conn,
                capability_code=capability,
                connector_version=version,
                business_code=business,
                business_date=shanghai_date(),
                safe_request=request,
                request_sha256=digest(request),
                max_requests=calls,
                max_items=maximum,
            )
            values = {
                "id": tid,
                "org_id": org,
                "kind": kind,
                "handler_version": version,
                "source_id": source,
                "business_code": business,
                "requested_by": channels.p.member_id,
                "execution_authorized_by": channels.p.member_id,
                "max_attempts": 1,
                "max_external_calls": calls,
                "idempotency_key": key,
            }
            values["input_sha256"] = input_digest(values, handler.freeze(c, values, az))
            create_task(c, values, [{"role": "creator_identity", "raw_asset_id": evidence}])
    try:
        worker = Runner(channels.runner.engine, {(kind, version): handler}, lease_seconds=90)
        if worker.run(org, tid) != "succeeded":
            with channels.runner.engine.connect() as c:
                raise TaskError(
                    row(c, "tasks", org, tid)["safe_error_code"] or "SOURCE_UNAVAILABLE"
                )
        with channels.runner.engine.connect() as c:
            return row(c, "tasks", org, tid)["business_outcome"]
    finally:
        with channels.runner.engine.begin() as c:
            src = row(c, "sources", org, source)
            if src["enabled"]:
                compare_and_swap(c, "sources", org, source, src["lock_version"], {"enabled": False})


def checkpoint(channels):
    channels.checkpoint()
    if str(shanghai_date()) != channels.ticket.payload["day"]:
        raise TaskError("DATE_WINDOW_MISMATCH")
