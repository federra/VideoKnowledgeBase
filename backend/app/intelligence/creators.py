"""Append-only configuration versions in existing manual raw assets, with audited heads."""

import hashlib
import json
from uuid import uuid4

from app.collection.service import get, insert
from app.connectors.creator_profiles import ProfileError, canonical_profile
from app.core.models import metadata
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import refresh
from app.security.storage import receipt

ACTION = "creator.config.saved"
MAX_CREATORS = 50


def authorize(c, p, business):
    refresh(c, p)
    if not Authorizer(c, p).allowed(
        "source.configure", {("org", str(p.org_id)), ("business", business)}
    ):
        raise Denied("ACCESS_DENIED")


def current(c, org, business):
    raw = (
        c.exec_driver_sql(
            "SELECT r.id,r.body_text FROM audit_events a JOIN raw_assets r ON r.org_id=a.org_id AND r.id=a.target_id "
            "WHERE a.org_id=%s AND a.action_code=%s AND a.safe_details->>'business'= %s "
            "ORDER BY r.captured_at DESC,a.id DESC LIMIT 1",
            (org, ACTION, business),
        )
        .mappings()
        .one_or_none()
    )
    return (raw["id"], json.loads(raw["body_text"])["items"]) if raw else (None, [])


def view(c, p, business):
    authorize(c, p, business)
    return {
        "business_code": business,
        "items": card_items(c, p, current(c, p.org_id, business)[1]),
        "results": [],
    }


def card_items(c, p, items):
    # Project only already verified, currently readable identities; never resolve online.
    projected = []
    for item in items:
        uid, raw_id = known_account(c, p, item["url"])
        name = identity_name(c, p, item["url"], uid, raw_id) if raw_id else None
        projected.append({**item, "platform_uid": uid, "display_name": name})
    return projected


def identity_name(c, p, url, uid, raw_id):
    from app.connectors.creator_profiles import parse_identity as profile_identity
    from app.connectors.douyin_public_http import parse_identity as series_identity
    from app.connectors.redfox import AdapterError

    body = get(c, "raw_assets", p.org_id, raw_id)["body_text"] or ""
    from app.connectors.douyin_posts import parse_identity as posts_identity

    for parser in (series_identity, profile_identity, posts_identity):
        try:
            data = parser(body, url)
        except (AdapterError, ValueError, TypeError, KeyError, AttributeError):
            continue
        if data["uid"] == uid:
            return data["name"].strip()[:90] or None
    return None


def save(c, p, body, key, *, remove=False):
    business = body.business_code
    authorize(c, p, business)

    def perform():
        _, items = current(c, p.org_id, business)
        results = []
        if remove:
            items = [x for x in items if x["id"] != str(body.creator_id)]
        else:
            known = {x["url"] for x in items}
            lines = body.links.splitlines()
            if len(lines) > 100:
                raise Denied("VALIDATION_FAILED")
            for index, line in enumerate(lines, 1):
                if not line.strip():
                    continue
                try:
                    url = canonical_profile(line)
                except ProfileError as exc:
                    results.append({"line": index, "state": "invalid", "message": str(exc)})
                    continue
                state = (
                    "duplicate"
                    if url in known
                    else "limit"
                    if len(items) >= MAX_CREATORS
                    else "added"
                )
                if state == "added":
                    items.append({"id": str(uuid4()), "url": url})
                    known.add(url)
                results.append(
                    {
                        "line": index,
                        "state": state,
                        "message": {
                            "added": "已保存",
                            "duplicate": "已配置，已去重",
                            "limit": "每个业务线最多50位博主",
                        }[state],
                    }
                )
        text = json.dumps({"business": business, "items": items}, sort_keys=True)
        raw = insert(
            c,
            "raw_assets",
            p.org_id,
            origin="manual",
            asset_kind="response",
            submitted_by=p.member_id,
            body_text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            captured_at=c.exec_driver_sql("SELECT clock_timestamp()").scalar_one(),
        )
        c.execute(
            metadata.tables["audit_events"]
            .insert()
            .values(
                id=uuid4(),
                org_id=p.org_id,
                actor_member_id=p.member_id,
                action_code=ACTION,
                target_kind="raw_asset",
                target_id=raw,
                request_id=str(uuid4()),
                safe_details={"business": business},
            )
        )
        return {"business_code": business, "items": items, "results": results}

    result = receipt(
        c,
        p,
        "removeCreatorLink" if remove else "saveCreatorLinks",
        key,
        body.model_dump(mode="json"),
        perform,
    )
    return {**result, "items": card_items(c, p, result["items"])}


def active(c, org, business, entry):
    return any(x == entry for x in current(c, org, business)[1])


def known_account(c, p, url):
    import re

    sec = url.rsplit("/", 1)[-1]
    rows = (
        c.exec_driver_sql(
            "SELECT a.platform_uid,x.raw_asset_id FROM external_accounts a JOIN external_account_aliases x "
            "ON x.org_id=a.org_id AND x.account_id=a.id WHERE a.org_id=%s AND a.platform_code='douyin' "
            "AND x.alias_kind='sec_uid' AND x.alias_value=%s ORDER BY x.observed_at DESC",
            (p.org_id, sec),
        )
        .mappings()
        .all()
    )
    available = []
    for row in rows:
        if not re.fullmatch(r"[1-9][0-9]{2,24}", row["platform_uid"]):
            continue
        try:
            Authorizer(c, p).read("raw_assets", row["raw_asset_id"])
        except Denied:
            continue
        available.append((row["platform_uid"], row["raw_asset_id"]))
    return available[0] if len({x[0] for x in available}) == 1 else (None, None)
