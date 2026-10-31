"""Read sealed feedback and its evidence. No collection, model or write side effects."""

from sqlalchemy import select

from app.core.models import metadata
from app.intelligence.service import authorized, row, shanghai_date
from app.security.errors import Denied
from app.security.read_authorizer import ReadAuthorizer


def project(full, content_id):
    comments = [x for x in full["comments"] if str(x["content_id"]) == str(content_id)]
    ids = {str(x["id"]) for x in comments}
    # A statement about several works cannot be rewritten as a single work's statement.
    claims = [
        x for x in full["claims"] if x["comment_ids"] and {str(v) for v in x["comment_ids"]} <= ids
    ]
    classified = {
        str(v)
        for claim in claims
        if claim["kind"] == "emotion"
        and claim.get("details", {}).get("sentiment") != "unclassifiable"
        for v in claim["comment_ids"]
    }
    return {
        "comments": comments,
        "claims": claims,
        "sample_count": len(comments),
        "classified_count": len(classified),
    }


def read_feedback(c, p, feedback_id, *, auth=None):
    auth = auth or ReadAuthorizer(c, p)
    auth._refresh()
    full = row(c, "feedback_snapshots", p.org_id, feedback_id, auth=auth)
    if not full["sealed_at"]:
        raise Denied("NOT_FOUND")
    snap = row(c, "intelligence_snapshots", p.org_id, full["snapshot_id"], auth=auth)
    if not snap["sealed_at"]:
        raise Denied("NOT_FOUND")
    auth.memo(("feedback.snapshot", snap["id"]), lambda: authorized(c, p, snap, auth=auth))
    task = row(c, "tasks", p.org_id, full["task_id"], auth=auth)
    execution = row(c, "ai_executions", p.org_id, full["ai_execution_id"], auth=auth)
    if task["state"] != "succeeded" or execution["result_state"] != "completed":
        raise Denied("SOURCE_UNAVAILABLE")
    # All raw input dependencies remain protected, including evidence not selected for TOP5.
    inputs = metadata.tables["task_inputs"]
    raw_ids = set()
    for item in c.execute(
        select(inputs).where(inputs.c.org_id == p.org_id, inputs.c.task_id == full["task_id"])
    ).mappings():
        if item["raw_asset_id"]:
            auth.read("raw_assets", item["raw_asset_id"])
            raw_ids.add(item["raw_asset_id"])
        elif item["snapshot_id"]:
            dependency = row(c, "intelligence_snapshots", p.org_id, item["snapshot_id"], auth=auth)
            if dependency["id"] != snap["id"]:
                raise Denied("SOURCE_UNAVAILABLE")
        elif not item["ai_config_revision_id"]:
            raise Denied("SOURCE_UNAVAILABLE")
    links, evidence = metadata.tables["feedback_comments"], metadata.tables["comment_evidence"]
    comments = []
    seen = set()
    for value in c.execute(
        select(evidence)
        .join(links, (links.c.org_id == evidence.c.org_id) & (links.c.comment_id == evidence.c.id))
        .where(links.c.org_id == p.org_id, links.c.feedback_id == feedback_id)
        .order_by(links.c.position)
    ).mappings():
        auth.read("raw_assets", value["raw_asset_id"])
        key = (value["content_id"], value["platform_comment_id"])
        if (
            value["raw_asset_id"] not in raw_ids
            or shanghai_date(value["captured_at"]) != snap["business_date"]
            or (value["platform_comment_id"] and key in seen)
        ):
            raise Denied("SOURCE_UNAVAILABLE")
        seen.add(key)
        comment = {
            k: value[k]
            for k in (
                "id",
                "created_at",
                "content_id",
                "platform_comment_id",
                "body_text",
                "like_count",
                "posted_at_raw",
                "posted_at",
                "captured_at",
            )
        }
        comment["like_count"] = (
            str(comment["like_count"]) if comment["like_count"] is not None else None
        )
        comment["username"] = value["username"]
        comments.append(comment)
    claims, refs = metadata.tables["feedback_claims"], metadata.tables["feedback_claim_evidence"]
    references = {}
    for claim_id, comment_id in c.execute(
        select(refs.c.claim_id, refs.c.comment_id)
        .where(refs.c.org_id == p.org_id, refs.c.feedback_id == feedback_id)
        .order_by(refs.c.comment_id)
    ):
        references.setdefault(claim_id, []).append(comment_id)
    output = []
    for value in c.execute(
        select(claims)
        .where(claims.c.org_id == p.org_id, claims.c.feedback_id == feedback_id)
        .order_by(claims.c.created_at, claims.c.id)
    ).mappings():
        ids = references.get(value["id"], [])
        if (
            not ids
            or not set(ids) <= {x["id"] for x in comments}
            or len(ids) != value["support_count"]
        ):
            raise Denied("SOURCE_UNAVAILABLE")
        output.append(
            {
                **{k: value[k] for k in ("id", "kind", "text", "support_count", "details")},
                "comment_ids": ids,
            }
        )
    classified = {
        i
        for claim in output
        if claim["kind"] == "emotion"
        and claim.get("details", {}).get("sentiment") != "unclassifiable"
        for i in claim["comment_ids"]
    }
    if len(comments) != full["sample_count"] or len(classified) != full["classified_count"]:
        raise Denied("SOURCE_UNAVAILABLE")
    return {
        **{
            k: full[k]
            for k in (
                "id",
                "created_at",
                "snapshot_id",
                "version_no",
                "sampling_description",
                "sample_count",
                "classified_count",
                "coverage_note",
                "summary",
            )
        },
        "comments": comments,
        "claims": output,
    }


def entry_feedback(c, p, entry_id, business, day, *, _analysis=True, auth=None):
    auth = auth or ReadAuthorizer(c, p)
    auth._refresh()
    entry = row(c, "snapshot_entries", p.org_id, entry_id, auth=auth)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"], auth=auth)
    if not snap["sealed_at"] or snap["business_code"] != business or snap["business_date"] != day:
        raise Denied("NOT_FOUND")
    auth.memo(("feedback.snapshot", snap["id"]), lambda: authorized(c, p, snap, auth=auth))
    if not entry["content_observation_id"]:
        raise Denied("NOT_FOUND")
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"], auth=auth)
    content = row(c, "external_contents", p.org_id, obs["content_id"], auth=auth)
    result = {
        "entry_id": entry_id,
        "snapshot_id": snap["id"],
        "snapshot_version": snap["version_no"],
        "business_code": business,
        "business_date": day,
        "platform_code": content["platform_code"],
        "status": "not_acquired",
        "feedback_id": None,
        "feedback_version": None,
        "sampling_description": None,
        "coverage_note": None,
        "sample_count": None,
        "classified_count": None,
        "comments": [],
        "claims": [],
    }

    def finish(value):
        if not _analysis:
            return value
        from app.intelligence.feedback_v2 import decorate

        return decorate(c, p, value, auth=auth)

    from app.intelligence.creator_samples import sample as creator_sample

    acquired = creator_sample(c, p, snap, content) if content["platform_code"] == "douyin" else None
    if acquired is not None:
        result.update(
            status="sampled",
            comments=acquired,
            sample_count=len(acquired),
            classified_count=0,
            sampling_description="该短剧明确第1集的视频评论，按返回顺序最多保留15条",
            coverage_note="整剧播放量与单集评论分开；仅为已采集样本，未执行AI分析，不代表全剧或全部观众",
        )
        return finish(result)
    if content["platform_code"] == "douyin" and business == "story_short":
        from app.intelligence.microfilm import sample_for_entry

        sample = sample_for_entry(c, p, entry_id, business, day, auth=auth)
        if sample is not None:
            result.update(
                status="sampled",
                comments=sample,
                sample_count=len(sample),
                classified_count=0,
                sampling_description="该视频接口按返回顺序最多15条一级评论",
                coverage_note="仅已采集原文样本，未执行AI分析、不代表全部观众或全部评论",
            )
            return finish(result)
    if content["platform_code"] == "hongguo":
        from app.intelligence.hongguo import sample_for_content

        sample = sample_for_content(c, p, content["id"], business, day, auth=auth)
        if sample is not None:
            result.update(
                status="sampled",
                comments=sample["comments"],
                sample_count=len(sample["comments"]),
                classified_count=0,
                sampling_description=f"公开播放页第{sample['page_episode_number']}集上下文预载，最多15条，未翻页",
                coverage_note="仅为已采集评论原文，未执行AI分析；评论池跨集归属及全量覆盖未验证，平台评论ID未提供",
            )
        return finish(result)
    t = metadata.tables["feedback_snapshots"]
    newest = c.execute(
        select(t.c.id)
        .where(t.c.org_id == p.org_id, t.c.snapshot_id == snap["id"], t.c.sealed_at.is_not(None))
        .where(
            t.c.task_id.in_(
                select(metadata.tables["tasks"].c.id).where(
                    metadata.tables["tasks"].c.kind == "audience.feedback",
                    metadata.tables["tasks"].c.handler_version.not_in(("2", "3")),
                )
            )
        )
        .order_by(t.c.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if newest:
        # Denied latest evidence propagates; never fall back to an older accessible version.
        full = read_feedback(c, p, newest, auth=auth)
        scoped = project(full, obs["content_id"])
        if scoped["comments"]:
            result.update(scoped)
            result.update(
                status="ready",
                feedback_id=full["id"],
                feedback_version=full["version_no"],
                sampling_description=full["sampling_description"],
                coverage_note=full["coverage_note"],
            )
    return finish(result)


def _attach_legacy_previews(c, p, snap, values, *, auth=None):
    t = metadata.tables["feedback_snapshots"]
    newest = c.execute(
        select(t.c.id)
        .where(t.c.org_id == p.org_id, t.c.snapshot_id == snap["id"], t.c.sealed_at.is_not(None))
        .where(
            t.c.task_id.in_(
                select(metadata.tables["tasks"].c.id).where(
                    metadata.tables["tasks"].c.kind == "audience.feedback",
                    metadata.tables["tasks"].c.handler_version.not_in(("2", "3")),
                )
            )
        )
        .order_by(t.c.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not newest:
        return
    try:
        full = read_feedback(c, p, newest, auth=auth)
    except Denied as exc:
        if exc.code == "NOT_FOUND":
            return  # Withheld evidence never leaks its existence or an older feedback ID.
        raise
    for value in values:
        observation = (
            row(c, "content_observations", p.org_id, value["entry"]["observation"]["id"])
            if value["entry"]["observation"]["kind"] == "content"
            else None
        )
        if observation is None:
            continue
        scoped = project(full, observation["content_id"])
        if not scoped["comments"]:
            continue
        value["entry"]["feedback_id"] = newest
        emotions = {}
        for claim in scoped["claims"]:
            if claim["kind"] == "emotion":
                emotions.setdefault(claim["text"], set()).update(claim["comment_ids"])
        value["feedback_emotions"] = [
            name for name, _ in sorted(emotions.items(), key=lambda x: -len(x[1]))[:2]
        ]


def attach_previews(c, p, snap, values, *, auth=None):
    auth = auth or ReadAuthorizer(c, p)
    _attach_legacy_previews(c, p, snap, values, auth=auth)
    # v2 tasks are per entry, unlike the legacy snapshot-wide report.
    import json

    from app.intelligence.feedback_v2 import members

    manifests = c.exec_driver_sql(
        "SELECT r.body_text FROM tasks t JOIN raw_assets r ON r.org_id=t.org_id AND r.id=t.raw_asset_id WHERE t.org_id=%s AND t.kind='audience.feedback' AND t.handler_version IN ('2','3') AND EXISTS(SELECT 1 FROM task_inputs i WHERE i.org_id=t.org_id AND i.task_id=t.id AND i.snapshot_id=%s)",
        (p.org_id, snap["id"]),
    ).scalars()
    entries = {
        __import__("uuid").UUID(x["sample"]["entry_id"])
        for text in manifests
        for x in members(json.loads(text))
    }
    for value in values:
        entry = value["entry"]
        if entry["id"] not in entries:
            continue
        full = entry_feedback(
            c, p, entry["id"], snap["business_code"], snap["business_date"], auth=auth
        )
        value["feedback_emotions"] = []
        entry["feedback_id"] = full["feedback_id"]
        if full["status"] != "ready":
            continue
        emotions = {}
        for claim in full["claims"]:
            if claim["kind"] == "emotion" and claim["details"].get("sentiment") != "unclassifiable":
                emotions.setdefault(claim["text"], set()).update(claim["comment_ids"])
        value["feedback_emotions"] = [
            name for name, _ in sorted(emotions.items(), key=lambda x: -len(x[1]))[:2]
        ]
