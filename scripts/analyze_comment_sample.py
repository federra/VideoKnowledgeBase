"""Normalize the saved sample; optional single budgeted DeepSeek execution. No collection."""

import argparse
import json
import os
import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.ai.feedback_task import FeedbackTask, submit_feedback
from app.collection.comment_normalize import NormalizeComments, submit_normalization
from app.core.config import settings
from app.core.database import application_engine
from app.intelligence.service import shanghai_date
from app.security.local import enter
from app.security.sessions import MemberPrincipal
from app.tasks.service import Runner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-model", action="store_true")
    args = parser.parse_args()
    if not settings.local_single_user:
        raise RuntimeError("Local workspace required")
    capture = json.loads(
        (ROOT / f"data/tikhub/live-comment-probe-{shanghai_date()}.json").read_text()
    )
    if capture["status"] != "succeeded" or capture["external_request_reservations"] != 1:
        raise RuntimeError("No successful captured response")
    raw = UUID(capture["raw_asset_id"])
    entry = UUID(capture["entry_id"])
    engine = application_engine()
    try:
        normalizer = NormalizeComments()
        with engine.begin() as c:
            _, context = enter(c)
            org = context["org_id"]
            p = MemberPrincipal(org, context["member_id"])
            snapshot = c.exec_driver_sql(
                "SELECT snapshot_id FROM snapshot_entries WHERE org_id=%s AND id=%s", (org, entry)
            ).scalar_one()
            norm = submit_normalization(c, p, raw, snapshot, normalizer)
        state = Runner(engine, {("comments.normalize", "1"): normalizer}).run(org, norm)
        with engine.connect() as c:
            count = c.exec_driver_sql(
                "SELECT count(*) FROM comment_evidence WHERE org_id=%s AND raw_asset_id=%s",
                (org, raw),
            ).scalar_one()
            norm_state = c.exec_driver_sql(
                "SELECT state FROM tasks WHERE id=%s", (norm,)
            ).scalar_one()
        result = {
            "normalization_task_id": str(norm),
            "normalization_state": norm_state,
            "normalized_comments": count,
            "collection_calls_added": 0,
            "model_calls_added": 0,
        }
        if norm_state != "succeeded":
            raise RuntimeError("Normalization failed")
        if args.execute_model:
            if not settings.deepseek_key or not settings.deepseek_key.get_secret_value().strip():
                raise RuntimeError("DeepSeek key missing")
            marker = ROOT / f"data/tikhub/feedback-model-{raw}.json"
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as file:
                json.dump({"status": "reserved", "raw_asset_id": str(raw)}, file)
            handler = FeedbackTask()
            with engine.begin() as c:
                tid = submit_feedback(c, p, raw, snapshot, handler)
            marker.write_text(json.dumps({"status": "submitted", "task_id": str(tid)}) + "\n")
            state = Runner(engine, {("audience.feedback", "1"): handler}).run(org, tid)
            with engine.connect() as c:
                executions = c.exec_driver_sql(
                    "SELECT count(*) FROM ai_executions WHERE org_id=%s AND task_id=%s", (org, tid)
                ).scalar_one()
                feedback = (
                    c.exec_driver_sql(
                        "SELECT id,version_no,sample_count,classified_count FROM feedback_snapshots WHERE org_id=%s AND task_id=%s",
                        (org, tid),
                    )
                    .mappings()
                    .one_or_none()
                )
                error = c.exec_driver_sql(
                    "SELECT safe_error_code FROM tasks WHERE org_id=%s AND id=%s", (org, tid)
                ).scalar_one()
            result.update(
                model_task_id=str(tid),
                model_state=state,
                model_calls_added=executions,
                safe_error_code=error,
                feedback={k: str(v) if isinstance(v, UUID) else v for k, v in feedback.items()}
                if feedback
                else None,
            )
            marker.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(result, ensure_ascii=False))
    finally:
        engine.dispose()


if __name__ == "__main__":
    try:
        main()
    except FileExistsError:
        print(
            "A model request intent already exists; inspect it without reissuing.", file=sys.stderr
        )
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001 - never print provider bodies or secret-bearing exceptions
        print("Sample processing stopped: " + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
