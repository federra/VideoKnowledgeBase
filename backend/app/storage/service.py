"""Authenticated file lifecycle. No network inside tenant transactions."""

import hashlib
import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.models import metadata
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import authenticate
from app.security.storage import audit, lock_org, receipt
from app.storage.validation import validate


def authorize(c, raw, meta):
    p = authenticate(c, raw)
    row = Authorizer(c, p).require("works", meta.work_id, "content.write")
    return p, row


def file_info(c, org, ident):
    t = metadata.tables["file_objects"]
    row = c.execute(select(t).where(t.c.org_id == org, t.c.id == ident)).mappings().one()
    if row["validation_state"] != "accepted":
        raise Denied("FILE_NOT_ACCEPTED")
    return {
        **{
            k: row[k]
            for k in [
                "id",
                "original_name",
                "media_type",
                "sha256",
                "validation_state",
                "created_at",
            ]
        },
        "byte_size": str(row["byte_size"]),
    }


def request_payload(meta, staged=None, *, external=False):
    payload = {"metadata": meta.model_dump(mode="json"), "normalization_version": 1}
    if not external:
        payload.update(sha256=staged.sha256, byte_size=staged.size)
    return payload


def replay_external(engine, raw, key, meta):
    with engine.begin() as c:
        p, work = authorize(c, raw, meta)
        t = metadata.tables["http_receipts"]
        row = (
            c.execute(
                select(t).where(
                    t.c.org_id == p.org_id,
                    t.c.member_id == p.member_id,
                    t.c.operation == "importFile",
                    t.c.key == key,
                )
            )
            .mappings()
            .one_or_none()
        )
        if row:
            if row["input_sha256"] != digest(request_payload(meta, external=True)):
                raise Denied("IDEMPOTENCY_CONFLICT")
            return file_info(c, p.org_id, UUID(row["response"]["id"]))
        if work["lock_version"] != int(meta.expected_work_lock_version):
            raise Denied("VERSION_CONFLICT")
        return None


def save(engine, store, raw, key, meta, staged, *, source_url=None, request_id=None):
    validate(staged.file, meta.original_name, meta.media_type)
    fid = uuid4()
    journal_created = False
    try:
        with engine.begin() as c:
            p, work = authorize(c, raw, meta)
            payload = request_payload(meta, staged, external=bool(source_url))

            def perform():
                nonlocal journal_created
                if work["lock_version"] != int(meta.expected_work_lock_version):
                    raise Denied("VERSION_CONFLICT")
                store.journal(staged, p.org_id, fid)
                journal_created = True
                store.publish(staged, p.org_id, fid)
                c.execute(
                    metadata.tables["file_objects"]
                    .insert()
                    .values(
                        id=fid,
                        org_id=p.org_id,
                        storage_backend="local",
                        storage_key=f"{p.org_id}/{fid}",
                        original_name=meta.original_name,
                        media_type=meta.media_type,
                        byte_size=staged.size,
                        sha256=staged.sha256,
                        uploaded_by=p.member_id,
                        validation_state="accepted",
                    )
                )
                c.execute(
                    metadata.tables["file_intakes"]
                    .insert()
                    .values(
                        org_id=p.org_id,
                        file_id=fid,
                        work_id=meta.work_id,
                        created_by=p.member_id,
                        origin_kind="external" if source_url else "upload",
                        source_url=source_url,
                    )
                )
                audit(c, p.org_id, p.member_id, "file.upload", "file", fid, request_id or key)
                return {"id": str(fid)}

            result = receipt(
                c, p, "importFile" if source_url else "uploadFile", key, payload, perform
            )
            info = file_info(c, p.org_id, UUID(result["id"]))
    except BaseException:
        if journal_created:
            # Resolve uncertain commits under a new tenant lock. If DB is unavailable,
            # retain the journal and object; never delete a possibly committed file.
            try:
                reconcile(
                    engine,
                    store,
                    {"org_id": str(p.org_id), "file_id": str(fid), "stage": staged.name},
                )
            except (SQLAlchemyError, OSError, Denied) as recovery_error:
                logging.getLogger(__name__).warning(
                    "File reconciliation deferred (%s)", type(recovery_error).__name__
                )

        raise
    if journal_created:
        store.forget(fid)
    return info


def reconcile(engine, store, entry):
    org, fid = UUID(entry["org_id"]), UUID(entry["file_id"])
    with engine.begin() as c:
        c.exec_driver_sql("SET LOCAL lock_timeout='2s'")
        c.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        lock_org(c, org)
        t = metadata.tables["file_objects"]
        row = c.execute(select(t).where(t.c.org_id == org, t.c.id == fid)).mappings().one_or_none()
        if row:
            with store.open(org, fid) as file:
                sha = hashlib.file_digest(file, "sha256").hexdigest()
                if file.tell() != row["byte_size"] or sha != row["sha256"]:
                    raise Denied("FILE_NOT_ACCEPTED")
            outcome = "kept"
        else:
            store.remove(org, fid)
            outcome = "removed"
        # A live stage is not removed even when its DB operation already committed.
        if store.clean_stage(entry["stage"]):
            audit(c, org, None, "file.recover_" + outcome, "file", fid)
            store.forget(fid)
        return outcome


def recover(engine, store):
    result = {"kept": 0, "removed": 0, "unresolved": 0}
    for entry in list(store.journals()):
        try:
            result[reconcile(engine, store, entry)] += 1
        except (OSError, Denied, SQLAlchemyError):
            result["unresolved"] += 1
    result["staging_removed"] = store.cleanup_staging(
        exclude={e["stage"] for e in store.journals()}
    )
    return result


def download_auth(c, raw, fid, parent):
    p = authenticate(c, raw)
    row = Authorizer(c, p).file(fid, parent)
    if row["storage_backend"] != "local" or row["storage_key"] != f"{p.org_id}/{fid}":
        raise Denied("FILE_NOT_ACCEPTED")
    return p, row


def open_download(engine, store, raw, fid, parent):
    with engine.begin() as c:
        p, row = download_auth(c, raw, fid, parent)
        try:
            file = store.open(p.org_id, fid)
        except OSError as exc:
            raise Denied("FILE_NOT_ACCEPTED") from exc
    try:
        if (
            row["byte_size"] > store.maximum
            or hashlib.file_digest(file, "sha256").hexdigest() != row["sha256"]
            or file.tell() != row["byte_size"]
        ):
            raise Denied("FILE_NOT_ACCEPTED")
        file.seek(0)
        # Re-check after reading bytes, before returning response headers.
        with engine.begin() as c:
            download_auth(c, raw, fid, parent)
            audit(c, p.org_id, p.member_id, "file.download", "file", fid)
        return file, row
    except BaseException:
        file.close()
        raise


def read_chunk(engine, raw, fid, parent, file):
    with engine.begin() as c:
        download_auth(c, raw, fid, parent)
        return file.read(65536)
