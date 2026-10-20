"""Latest Shanghai slot only; durable unique(plan, slot) provides scheduling idempotency."""

from datetime import UTC, timedelta
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from app.collection.console import FREQUENCIES
from app.collection.service import get, submit
from app.connectors.redfox import VERSION
from app.contracts.models import CollectionCreate
from app.core.repository import create_task
from app.security.errors import Denied
from app.security.sessions import MemberPrincipal, refresh
from app.security.storage import audit
from app.tasks.service import TaskError, input_digest

ZONE = ZoneInfo("Asia/Shanghai")


def due_slot(frequency, now):
    if now.tzinfo is None:
        raise ValueError("aware time required")
    local = now.astimezone(ZONE)
    if frequency == "daily_0900":
        slot = local.replace(hour=9, minute=0, second=0, microsecond=0)
        if local < slot:
            slot -= timedelta(days=1)
    elif frequency in ("every_2h", "every_4h"):
        hours = 2 if frequency == "every_2h" else 4
        slot = local.replace(hour=(local.hour // hours) * hours, minute=0, second=0, microsecond=0)
    else:
        raise ValueError("unsupported frequency")
    return slot.astimezone(UTC)


def schedule(runner, *, now=None):
    with runner.engine.connect() as c:
        now = now or c.exec_driver_sql("SELECT clock_timestamp()").scalar_one()
        plans = list(
            c.exec_driver_sql(
                "SELECT org_id,id FROM collection_plans WHERE enabled ORDER BY created_at,id"
            )
        )
    count = 0
    for org, pid in plans:
        try:
            with runner.engine.begin() as c:
                from app.security.storage import lock_org

                lock_org(c, org)
                plan = get(c, "collection_plans", org, pid)
                if not plan or not plan["enabled"]:
                    continue
                source = get(c, "sources", org, plan["source_id"])
                if not source or not source["enabled"]:
                    continue
                frequency = next(
                    (k for k, v in FREQUENCIES.items() if v == plan["schedule_expression"]), None
                )
                if frequency is None:
                    continue
                slot = due_slot(frequency, now)
                # Newly enabled/re-enabled plans never backfill periods they were paused.
                if (
                    slot < max(plan["created_at"], plan["updated_at"])
                    or slot.astimezone(ZONE).date() != now.astimezone(ZONE).date()
                ):
                    continue
                exists = c.exec_driver_sql(
                    "SELECT 1 FROM collection_jobs WHERE org_id=%s AND plan_id=%s AND scheduled_for=%s",
                    (org, pid, slot),
                ).first()
                if exists:
                    continue
                p = MemberPrincipal(org, plan["authorized_by"])
                refresh(c, p)
                request = CollectionCreate(
                    source_id=plan["source_id"],
                    provider_connection_id=plan["connection_id"],
                    capability_code=plan["capability_code"],
                    max_requests=plan["max_requests_per_run"],
                    max_items=plan["max_items_per_run"],
                )
                submit(
                    c,
                    p,
                    request,
                    str(uuid5(NAMESPACE_URL, "cip:plan:" + str(pid) + ":" + slot.isoformat())),
                    runner.handlers[("collect.redfox", VERSION)],
                    plan=plan,
                    scheduled_for=slot,
                )
                count += 1
        except (Denied, TaskError, ValueError, KeyError):
            # Stale authority/config cannot authorize fresh paid work; disable, preserve jobs.
            with runner.engine.begin() as c:
                from app.core.repository import compare_and_swap
                from app.security.storage import lock_org

                lock_org(c, org)
                plan = get(c, "collection_plans", org, pid)
                if plan and plan["enabled"]:
                    compare_and_swap(
                        c, "collection_plans", org, pid, plan["lock_version"], {"enabled": False}
                    )
                    audit(c, org, None, "plan.disabled_invalid_authority", "collection_plan", pid)
    return count


def handoff(c, task, raw):
    job = get(c, "collection_jobs", task["org_id"], raw["collection_job_id"])
    plan = get(c, "collection_plans", task["org_id"], job["plan_id"])
    if plan["request_options"].get("purpose") not in ("knowledge", "both"):
        return
    values = {
        "org_id": task["org_id"],
        "kind": "collection.knowledge-intake",
        "handler_version": "1",
        "business_code": task["business_code"],
        "source_id": task["source_id"],
        "raw_asset_id": raw["id"],
        "requested_by": task["requested_by"],
        "execution_authorized_by": task["execution_authorized_by"],
        "idempotency_key": "raw:" + str(raw["id"]),
        "max_attempts": 1,
        "max_external_calls": 0,
    }
    payload = {"raw_id": str(raw["id"]), "sha256": raw["sha256"]}
    values["input_sha256"] = input_digest(values, payload)
    tid, _ = create_task(c, values, [{"role": "collected_evidence", "raw_asset_id": raw["id"]}])
    audit(
        c,
        task["org_id"],
        task["execution_authorized_by"],
        "knowledge.intake_dispatched",
        "task",
        tid,
    )


class KnowledgeIntake:
    """A truthful handoff marker, not a substitute for S07 extraction/dual review."""

    action = "knowledge.edit"

    def freeze(self, c, task, az):
        source = az.require("sources", task["source_id"], "collection.run")
        if not az.allowed("knowledge.edit", az.scopes("sources", source)):
            raise Denied("ACCESS_DENIED")
        raw = az.read("raw_assets", task["raw_asset_id"])
        if task["max_external_calls"] != 0:
            raise TaskError("INVALID_INPUT")
        return {"raw_id": str(raw["id"]), "sha256": raw["sha256"]}

    def execute(self, payload, checkpoint):
        checkpoint()
        # Only metadata exists in the current verified connector; do not invent knowledge.
        raise TaskError("INSUFFICIENT_MATERIAL")
