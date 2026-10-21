"""Durable task runtime; queue messages carry IDs only, all effects commit with the fence."""

import logging
from dataclasses import dataclass
from threading import Event, Thread
from uuid import UUID

from sqlalchemy import select

from app.core.models import metadata
from app.core.repository import claim_task, create_task, finish_task
from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.primitives import digest
from app.security.sessions import MemberPrincipal, authenticate, refresh
from app.security.storage import audit, lock_org
from app.tasks.policy import retry_delay

log = logging.getLogger(__name__)


def row(c, org, ident):
    c.exec_driver_sql("SET LOCAL lock_timeout='2s'")
    c.exec_driver_sql("SET LOCAL statement_timeout='5s'")
    lock_org(c, org)
    t = metadata.tables["tasks"]
    return (
        c.execute(select(t).where(t.c.org_id == org, t.c.id == ident).with_for_update())
        .mappings()
        .one_or_none()
    )


def control(c, task, operation, *, attempt=None, token=None, seconds=0, code=None):
    return c.exec_driver_sql(
        "SELECT cip_task_control(%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            task["org_id"],
            task["id"],
            task["lock_version"],
            operation,
            attempt,
            token,
            seconds,
            code,
        ),
    ).scalar_one()


def input_digest(task, payload):
    return digest(
        {
            "kind": task["kind"],
            "handler_version": task["handler_version"],
            "requested_by": str(task["requested_by"]),
            "execution_authorized_by": str(task["execution_authorized_by"]),
            "payload": payload,
        }
    )


@dataclass(frozen=True)
class Ticket:
    org: UUID
    task: UUID
    attempt: UUID
    token: UUID
    version: int
    payload: dict


class Runner:
    def __init__(self, engine, handlers, *, lease_seconds=90, parallel=2):
        if not 1 <= lease_seconds <= 3600 or not 1 <= parallel <= 16:
            raise ValueError("Invalid worker bounds")
        self.engine, self.handlers = engine, handlers
        self.lease_seconds, self.parallel = lease_seconds, parallel

    def validate(self, c, task):
        handler = self.handlers.get((task["kind"], task["handler_version"]))
        if handler is None:
            raise TaskError("HANDLER_UNAVAILABLE")
        if not task["inputs_sealed_at"] or not task["execution_authorized_by"]:
            raise TaskError("INVALID_INPUT")
        # Background execution uses current members, not a cached grant or browser token.
        payload = None
        for member in (task["requested_by"], task["execution_authorized_by"]):
            if member is None:
                raise TaskError("ACCESS_REVOKED")
            p = MemberPrincipal(task["org_id"], member)
            refresh(c, p)
            payload = handler.freeze(c, task, Authorizer(c, p))
        if input_digest(task, payload) != task["input_sha256"]:
            raise TaskError("INVALID_INPUT")
        return handler, payload

    def claim(self, org, ident):
        with self.engine.begin() as c:
            task = row(c, org, ident)
            now = c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
            if not task or task["state"] != "queued" or task["available_at"] > now:
                return None
            try:
                handler, payload = self.validate(c, task)
            except (Denied, TaskError) as exc:
                code = exc.code if isinstance(exc, TaskError) else "ACCESS_REVOKED"
                control(c, task, "fail_queued", code=code)
                audit(c, org, task["execution_authorized_by"], "task.failed", "task", ident)
                return None
            if hasattr(handler, "defer") and handler.defer(c, task):
                return None
            active = c.exec_driver_sql(
                "SELECT count(*) FROM task_attempts WHERE org_id=%s AND finished_at IS NULL", (org,)
            ).scalar_one()
            if active >= self.parallel:
                return None
            attempt, token, version = claim_task(
                c, org, ident, task["lock_version"], lease_seconds=self.lease_seconds
            )
            audit(c, org, task["execution_authorized_by"], "task.claimed", "task", ident)
            return Ticket(org, ident, attempt, token, version, payload)

    def live(self, c, ticket, *, allow_cancel=False):
        task = row(c, ticket.org, ticket.task)
        a = (
            c.exec_driver_sql(
                "SELECT id,worker_token,lease_expires_at>clock_timestamp() AS live "
                "FROM task_attempts WHERE org_id=%s AND task_id=%s "
                "AND finished_at IS NULL",
                (ticket.org, ticket.task),
            )
            .mappings()
            .one_or_none()
        )
        if (
            not task
            or not a
            or a["id"] != ticket.attempt
            or a["worker_token"] != ticket.token
            or not a["live"]
        ):
            return None
        if allow_cancel and task["state"] == "cancel_requested":
            return task
        if task["state"] != "running" or task["lock_version"] != ticket.version:
            return None
        return task

    def heartbeat(self, ticket):
        with self.engine.begin() as c:
            task = self.live(c, ticket)
            if not task:
                return False
            # Recheck authority/input during long work; final transaction repeats it.
            try:
                self.validate(c, task)
            except (Denied, TaskError):
                return False
            return control(
                c,
                task,
                "renew",
                attempt=ticket.attempt,
                token=ticket.token,
                seconds=self.lease_seconds,
            )

    def _finish(self, c, task, ticket, code=None):
        cancelled = task["state"] == "cancel_requested"
        # Unresolved external effects prevent cancellation claims. Known completed calls
        # retain their safe failure; any reservation still blocks automatic retransmission.
        calls = unresolved_calls(c, task["id"])
        if calls:
            code = "EXTERNAL_RESULT_UNKNOWN"
            cancelled = False
        finish_task(
            c,
            ticket.org,
            ticket.task,
            ticket.attempt,
            ticket.token,
            task["lock_version"],
            outcome="cancelled" if cancelled else "failed",
            error=code,
        )
        audit(
            c,
            ticket.org,
            task["execution_authorized_by"],
            "task.cancelled" if cancelled else "task.failed",
            "task",
            ticket.task,
        )
        if cancelled:
            return "cancelled"
        return self._retry(c, row(c, ticket.org, ticket.task))

    def _retry(self, c, task, *, actor=None):
        count = c.exec_driver_sql(
            "SELECT count(*) FROM task_attempts WHERE task_id=%s", (task["id"],)
        ).scalar_one()
        delay = retry_delay(task["safe_error_code"], count, task["max_attempts"]) if count else None
        if delay is None or external_calls(c, task["id"]):
            return "failed"
        try:
            self.validate(c, task)
        except (Denied, TaskError):
            return "failed"
        if control(c, task, "retry", seconds=delay):
            audit(
                c,
                task["org_id"],
                actor if actor is not None else task["execution_authorized_by"],
                "task.retry",
                "task",
                task["id"],
            )
            return "queued"
        return "failed"

    def fail(self, ticket, code):
        # Only fixed safe codes reach storage; exception strings are never persisted.
        if code not in {
            "LOCAL_TRANSIENT",
            "TIMEOUT",
            "INVALID_INPUT",
            "ACCESS_REVOKED",
            "EXTERNAL_RESULT_UNKNOWN",
            "INTERNAL_ERROR",
            "RATE_LIMITED",
            "MODEL_NOT_CONFIGURED",
            "SOURCE_UNAVAILABLE",
            "INVALID_RESPONSE",
            "FETCH_FAILED",
            "DATE_WINDOW_MISMATCH",
            "INSUFFICIENT_MATERIAL",
        }:
            code = "INTERNAL_ERROR"
        with self.engine.begin() as c:
            task = self.live(c, ticket, allow_cancel=True)
            return self._finish(c, task, ticket, code) if task else "ignored"

    def complete(self, ticket, result):
        try:
            with self.engine.begin() as c:
                task = self.live(c, ticket, allow_cancel=True)
                if not task:
                    return "ignored"
                if task["state"] == "cancel_requested":
                    return self._finish(c, task, ticket)
                try:
                    handler, _ = self.validate(c, task)
                except (Denied, TaskError) as exc:
                    code = exc.code if isinstance(exc, TaskError) else "ACCESS_REVOKED"
                    return self._finish(c, task, ticket, code)
                handler.publish(c, task, result)
                finish_task(
                    c,
                    ticket.org,
                    ticket.task,
                    ticket.attempt,
                    ticket.token,
                    ticket.version,
                    business_outcome=result.get("business_outcome", "completed")
                    if isinstance(result, dict)
                    else "completed",
                )
                if hasattr(handler, "after_finish"):
                    handler.after_finish(c, task, result)
                audit(
                    c,
                    ticket.org,
                    task["execution_authorized_by"],
                    "task.succeeded",
                    "task",
                    ticket.task,
                )
            return "succeeded"
        except TaskError as exc:
            return self.fail(ticket, exc.code)
        except Exception:  # noqa: BLE001 - rollback products and sanitize processor failures
            # Rollback includes products/output links; record only the safe error after.
            return self.fail(ticket, "INTERNAL_ERROR")

    def run(self, org, ident):
        ticket = self.claim(org, ident)
        if ticket is None:
            with self.engine.connect() as c:
                s = c.exec_driver_sql(
                    "SELECT state FROM tasks WHERE org_id=%s AND id=%s", (org, ident)
                ).scalar_one_or_none()
            return "failed" if s == "failed" else "ignored"
        stop, lost = Event(), Event()

        def heartbeat():
            while not stop.wait(min(15, self.lease_seconds / 3)):
                try:
                    if not self.heartbeat(ticket):
                        lost.set()
                        return
                except Exception:  # noqa: BLE001 - loss of DB access fences the worker
                    lost.set()
                    return

        def checkpoint():
            if lost.is_set() or not self.heartbeat(ticket):
                raise TaskError("ACCESS_REVOKED")

        thread = Thread(target=heartbeat, daemon=True)
        thread.start()
        try:
            handler = self.handlers[(self._kind(ticket))]
            result = (
                handler.execute_ticket(self, ticket, checkpoint)
                if hasattr(handler, "execute_ticket")
                else handler.execute(ticket.payload, checkpoint)
            )
            stop.set()
            thread.join(timeout=5)
            return self.complete(ticket, result)
        except TaskError as exc:
            return self.fail(ticket, exc.code)
        except Exception as exc:  # noqa: BLE001 - processor errors are safe codes only
            from billiard.exceptions import SoftTimeLimitExceeded

            return self.fail(
                ticket, "TIMEOUT" if isinstance(exc, SoftTimeLimitExceeded) else "INTERNAL_ERROR"
            )
        finally:
            stop.set()
            thread.join(timeout=5)

    def _kind(self, ticket):
        with self.engine.connect() as c:
            return tuple(
                c.exec_driver_sql(
                    "SELECT kind,handler_version FROM tasks WHERE org_id=%s AND id=%s",
                    (ticket.org, ticket.task),
                ).one()
            )

    def recover(self, org, ident):
        with self.engine.begin() as c:
            task = row(c, org, ident)
            if not task or not control(c, task, "recover"):
                return False
            audit(c, org, task["execution_authorized_by"], "task.recovered", "task", ident)
            current = row(c, org, ident)
            if current["state"] == "failed":
                self._retry(c, current)
            return True


class TaskError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def unresolved_calls(c, tid):
    return c.exec_driver_sql(
        "SELECT (SELECT count(*) FROM collection_calls cc JOIN collection_jobs j "
        "ON j.id=cc.job_id WHERE j.task_id=%s AND (cc.completed_at IS NULL OR cc.outcome='network_error')) + "
        "(SELECT count(*) FROM ai_executions WHERE task_id=%s AND "
        "(finished_at IS NULL OR safe_error_code='EXTERNAL_RESULT_UNKNOWN'))",
        (tid, tid),
    ).scalar_one()


def external_calls(c, tid):
    return c.exec_driver_sql(
        "SELECT (SELECT count(*) FROM collection_calls cc JOIN collection_jobs j "
        "ON j.id=cc.job_id WHERE j.task_id=%s) + "
        "(SELECT count(*) FROM ai_executions WHERE task_id=%s)",
        (tid, tid),
    ).scalar_one()


def manage(c, p, ident, expected):
    refresh(c, p)
    task = row(c, p.org_id, ident)
    if not task:
        raise Denied("NOT_FOUND")
    az = Authorizer(c, p)
    scopes = az.scopes("tasks", task)
    for field, kind in [
        ("work_id", "works"),
        ("file_id", "file_objects"),
        ("source_id", "sources"),
    ]:
        if task[field]:
            scopes |= az.scopes(kind, az.row(kind, task[field]))
    if not az.allowed("task.manage", scopes):
        raise Denied("ACCESS_DENIED")
    if task["lock_version"] != expected:
        raise Denied("VERSION_CONFLICT")
    return task


def cancel(c, p, ident, expected):
    task = manage(c, p, ident, expected)
    if control(c, task, "cancel"):
        audit(c, p.org_id, p.member_id, "task.cancel_requested", "task", ident)
        return True
    return False


def retry(c, p, ident, expected, runner):
    task = manage(c, p, ident, expected)
    return runner._retry(c, task, actor=p.member_id)


def sweep(runner, send, *, limit=100):
    if not 1 <= limit <= 100:
        raise ValueError("Invalid sweep batch")
    with runner.engine.connect() as c:
        expired = list(
            c.exec_driver_sql(
                "SELECT t.org_id,t.id FROM tasks t JOIN task_attempts a "
                "ON a.task_id=t.id WHERE t.state IN ('running','cancel_requested') AND a.finished_at IS NULL "
                "AND a.lease_expires_at<=clock_timestamp() ORDER BY a.lease_expires_at,t.id LIMIT %s",
                (limit,),
            )
        )
    for org, tid in expired:
        runner.recover(org, tid)
    with runner.engine.connect() as c:
        queued = list(
            c.exec_driver_sql(
                "SELECT org_id,id FROM tasks WHERE state='queued' AND kind NOT IN ('collect.novels','collect.hongguo') "
                "AND available_at<=clock_timestamp() ORDER BY available_at,id LIMIT %s",
                (limit,),
            )
        )
    sent = 0
    for org, tid in queued:
        try:
            send(org, tid)
            sent += 1
        except Exception:  # noqa: BLE001 - broker outage leaves the durable task queued
            log.warning("task_dispatch_failed")
            break  # durable DB row remains; next tick retries without consuming Attempts
    return {"sent": sent, "expired_checked": len(expired)}


def submit_file(engine, raw, fid, key, *, max_attempts=1):
    from app.tasks.handlers import FileVerify

    if not 1 <= max_attempts <= 3 or not 1 <= len(key) <= 128:
        raise Denied("VALIDATION_FAILED")
    handler = FileVerify()
    with engine.begin() as c:
        p = authenticate(c, raw)
        intake = c.exec_driver_sql(
            "SELECT work_id FROM file_intakes WHERE org_id=%s AND file_id=%s", (p.org_id, fid)
        ).scalar_one_or_none()
        if not intake:
            raise Denied("NOT_FOUND")
        task = {
            "org_id": p.org_id,
            "kind": "file.verify",
            "handler_version": "1",
            "work_id": intake,
            "file_id": fid,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": max_attempts,
            "max_external_calls": 0,
            "idempotency_key": key,
        }
        payload = handler.freeze(c, task, Authorizer(c, p))
        task["input_sha256"] = input_digest(task, payload)
        ident, created = create_task(c, task)
        if created:
            audit(c, p.org_id, p.member_id, "task.created", "task", ident)
        return ident, created
