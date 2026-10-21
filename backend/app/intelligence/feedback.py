"""Read sealed feedback and its evidence. No collection, model or write side effects."""

from sqlalchemy import select

from app.core.models import metadata
from app.intelligence.service import authorized, row, shanghai_date
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh


def project(full, content_id):
    comments = [x for x in full["comments"] if str(x["content_id"]) == str(content_id)]
    ids = {str(x["id"]) for x in comments}
    # A statement about several works cannot be rewritten as a single work's statement.
    claims = [
        x for x in full["claims"] if x["comment_ids"] and {str(v) for v in x["comment_ids"]} <= ids
    ]
    classified = {
        str(v) for claim in claims if claim["kind"] == "emotion" for v in claim["comment_ids"]
    }
    return {
        "comments": comments,
        "claims": claims,
        "sample_count": len(comments),
        "classified_count": len(classified),
    }


def read_feedback(c, p, feedback_id):
    refresh(c, p)
    full = row(c, "feedback_snapshots", p.org_id, feedback_id)
    if not full["sealed_at"]:
        raise Denied("NOT_FOUND")
    snap = row(c, "intelligence_snapshots", p.org_id, full["snapshot_id"])
    if not snap["sealed_at"]:
        raise Denied("NOT_FOUND")
    authorized(c, p, snap)
    task = row(c, "tasks", p.org_id, full["task_id"])
    execution = row(c, "ai_executions", p.org_id, full["ai_execution_id"])
    if task["state"] != "succeeded" or execution["result_state"] != "completed":
        raise Denied("SOURCE_UNAVAILABLE")
    # All raw input dependencies remain protected, including evidence not selected for TOP5.
    inputs = metadata.tables["task_inputs"]
    auth = Authorizer(c, p)
    raw_ids = set()
    for item in c.execute(
        select(inputs).where(inputs.c.org_id == p.org_id, inputs.c.task_id == full["task_id"])
    ).mappings():
        if item["raw_asset_id"]:
            auth.read("raw_assets", item["raw_asset_id"])
            raw_ids.add(item["raw_asset_id"])
        elif item["snapshot_id"]:
            dependency = row(c, "intelligence_snapshots", p.org_id, item["snapshot_id"])
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
    output = []
    for value in c.execute(
        select(claims)
        .where(claims.c.org_id == p.org_id, claims.c.feedback_id == feedback_id)
        .order_by(claims.c.created_at, claims.c.id)
    ).mappings():
        ids = list(
            c.execute(
                select(refs.c.comment_id)
                .where(refs.c.org_id == p.org_id, refs.c.claim_id == value["id"])
                .order_by(refs.c.comment_id)
            ).scalars()
        )
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
    classified = {i for claim in output if claim["kind"] == "emotion" for i in claim["comment_ids"]}
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


def entry_feedback(c, p, entry_id, business, day):
    refresh(c, p)
    entry = row(c, "snapshot_entries", p.org_id, entry_id)
    snap = row(c, "intelligence_snapshots", p.org_id, entry["snapshot_id"])
    if not snap["sealed_at"] or snap["business_code"] != business or snap["business_date"] != day:
        raise Denied("NOT_FOUND")
    authorized(c, p, snap)
    if not entry["content_observation_id"]:
        raise Denied("NOT_FOUND")
    obs = row(c, "content_observations", p.org_id, entry["content_observation_id"])
    content = row(c, "external_contents", p.org_id, obs["content_id"])
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
    if content["platform_code"] == "hongguo":
        from app.intelligence.hongguo import sample_for_content

        sample = sample_for_content(c, p, content["id"], business, day)
        if sample is not None:
            result.update(status="sampled", comments=sample["comments"], sample_count=len(sample["comments"]), classified_count=0,
                          sampling_description=f"公开播放页第{sample['page_episode_number']}集上下文预载，最多15条，未翻页",
                          coverage_note="仅为已采集评论原文，未执行AI分析；评论池跨集归属及全量覆盖未验证，平台评论ID未提供")
        return result
    t = metadata.tables["feedback_snapshots"]
    newest = c.execute(
        select(t.c.id)
        .where(t.c.org_id == p.org_id, t.c.snapshot_id == snap["id"], t.c.sealed_at.is_not(None))
        .order_by(t.c.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if newest:
        # Denied latest evidence propagates; never fall back to an older accessible version.
        full = read_feedback(c, p, newest)
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
    return result


def attach_previews(c, p, snap, values):
    t = metadata.tables["feedback_snapshots"]
    newest = c.execute(
        select(t.c.id)
        .where(t.c.org_id == p.org_id, t.c.snapshot_id == snap["id"], t.c.sealed_at.is_not(None))
        .order_by(t.c.version_no.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not newest:
        return
    try:
        full = read_feedback(c, p, newest)
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
