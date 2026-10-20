"""S07.1 real PG task/execution evidence; HTTP is synthetic, no paid traffic."""

import json
from uuid import UUID, uuid4

import httpx
import pytest
from pydantic import SecretStr

from tests.integration.test_collection import prepared

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def seed(engine, setup):
    from app.collection.series import (
        CaptureSeries,
        NormalizeSeries,
        submit_capture,
        submit_normalization,
    )
    from app.connectors.tikhub_series import VERSION, Series
    from app.security.sessions import authenticate
    from app.tasks.service import Runner
    from tests.test_tikhub_series import payload

    *_, token = prepared(engine, setup)
    capture = CaptureSeries(
        Series(
            lambda: "offline",
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload())),
        ),
        min_interval=0,
    )
    with engine.begin() as c:
        p = authenticate(c, token)
        out = submit_capture(c, p, str(uuid4()), capture)
    assert (
        Runner(engine, {("collect.tikhub-series", VERSION): capture}).run(
            p.org_id, UUID(out["task_id"])
        )
        == "succeeded"
    )
    with engine.begin() as c:
        raw = c.exec_driver_sql(
            "SELECT id FROM raw_assets WHERE collection_job_id=%s", (UUID(out["job_id"]),)
        ).scalar_one()
        tid = submit_normalization(c, p, raw)
    assert (
        Runner(engine, {("series.normalize", VERSION): NormalizeSeries()}).run(p.org_id, tid)
        == "succeeded"
    )
    with engine.connect() as c:
        snap = c.exec_driver_sql(
            "SELECT id FROM intelligence_snapshots WHERE job_id=%s", (UUID(out["job_id"]),)
        ).scalar_one()
        entry = c.exec_driver_sql(
            "SELECT id FROM snapshot_entries WHERE snapshot_id=%s ORDER BY position LIMIT 1",
            (snap,),
        ).scalar_one()
    return p, snap, entry


@pytest.mark.parametrize(
    "case",
    [
        "success",
        "invalid",
        "timeout",
        "revoked",
        "revoked_after_call",
        "model401",
        "run_revoked",
        "submit_revoked",
        "outer_array",
    ],
)
def test_research_probe_budget_evidence_and_no_business_publication(engine, setup, tmp_path, case):
    from app.ai.deepseek import DeepSeek
    from app.ai.research_probe import Probe, submit_probe
    from app.storage.local import LocalStore
    from app.tasks.service import Runner

    p, snap, entry = seed(engine, setup)
    from tests.integration.test_security import grant

    with engine.begin() as c:
        grant(
            c,
            p.org_id,
            p.member_id,
            p.member_id,
            ["research.submit", "research.run", "model.configure"],
        )
    calls = []

    def transport(request):
        calls.append(request)
        if case == "revoked_after_call":
            with engine.begin() as c:
                c.exec_driver_sql(
                    "UPDATE provider_connections SET enabled=false,lock_version=lock_version+1 WHERE id=(SELECT provider_connection_id FROM ai_config_revisions WHERE config_key=%s AND org_id=%s)",
                    ("research.decompose.v1", p.org_id),
                )
        if case == "outer_array":
            return httpx.Response(200, content=b"[]")
        if case == "model401":
            return httpx.Response(401, text="private provider body")
        if case == "timeout":
            raise httpx.ReadTimeout("private", request=request)
        data = json.loads(json.loads(request.content)["messages"][1]["content"])
        claim = {
            "key": "c1",
            "dimension": "主线",
            "finding": "原始简介片段",
            "evidence": [
                {
                    "segment_id": "p1",
                    "quote": data["segments"][0]["text"] if case != "invalid" else "foreign",
                }
            ],
        }
        body = {
            "result_state": "completed",
            "coverage": "partial",
            "limitations": ["仅简介，未覆盖全剧"],
            "claims": [claim],
        }
        return httpx.Response(
            200,
            json={
                "id": "fixture",
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(body)}}],
                "usage": {"prompt_tokens": 200, "completion_tokens": 80},
            },
        )

    handler = Probe(
        DeepSeek(lambda: SecretStr("offline"), transport=httpx.MockTransport(transport)),
        LocalStore(tmp_path / "private"),
    )
    with engine.begin() as c:
        tid = submit_probe(c, p, snap, entry, handler)
        assert submit_probe(c, p, snap, entry, handler) == tid
        if case == "submit_revoked":
            c.exec_driver_sql(
                "DELETE FROM role_actions WHERE org_id=%s AND action_code='research.submit'",
                (p.org_id,),
            )
        if case == "run_revoked":
            c.exec_driver_sql(
                "DELETE FROM role_actions WHERE org_id=%s AND action_code='research.run'",
                (p.org_id,),
            )
        if case == "revoked":
            c.exec_driver_sql(
                "UPDATE provider_connections SET enabled=false,lock_version=lock_version+1 WHERE id=(SELECT provider_connection_id FROM ai_config_revisions WHERE config_key=%s AND org_id=%s)",
                ("research.decompose.v1", p.org_id),
            )
    runner = Runner(engine, {("research.definition-probe", "1"): handler})
    state = runner.run(p.org_id, tid)
    assert state == ("succeeded" if case == "success" else "failed")
    assert len(calls) == (0 if case in ("revoked", "run_revoked", "submit_revoked") else 1)
    assert runner.run(p.org_id, tid) == ("ignored" if case == "success" else "failed")
    with engine.connect() as c:
        executions = (
            c.exec_driver_sql("SELECT * FROM ai_executions WHERE task_id=%s", (tid,))
            .mappings()
            .all()
        )
        assert len(executions) == len(calls)
        if executions:
            e = executions[0]
            assert e["input_manifest_file_id"]
            assert e["result_state"] == (
                "completed" if case in ("success", "revoked_after_call") else "failed"
            )
            assert e["safe_error_code"] == (
                None
                if case in ("success", "revoked_after_call")
                else "EXTERNAL_RESULT_UNKNOWN"
                if case == "timeout"
                else "MODEL_NOT_CONFIGURED"
                if case == "model401"
                else "INVALID_RESPONSE"
            )
        if case == "model401":
            assert (
                c.exec_driver_sql(
                    "SELECT safe_error_code FROM tasks WHERE id=%s", (tid,)
                ).scalar_one()
                == "MODEL_NOT_CONFIGURED"
            )
        for table in ("analysis_reports", "quality_evaluations", "predictions", "knowledge_items"):
            assert (
                c.exec_driver_sql(
                    f"SELECT count(*) FROM {table} WHERE org_id=%s", (p.org_id,)
                ).scalar_one()
                == 0
            )


def test_research_probe_submit_permission_cannot_authorize_execution(engine, setup, tmp_path):
    from app.ai.deepseek import DeepSeek
    from app.ai.research_probe import KIND, Probe, submit_probe
    from app.security.errors import Denied
    from app.storage.local import LocalStore
    from tests.integration.test_security import grant

    p, snap, entry = seed(engine, setup)
    with engine.begin() as c:
        grant(c, p.org_id, p.member_id, p.member_id, ["research.submit", "model.configure"])
    calls = []
    handler = Probe(
        DeepSeek(
            lambda: SecretStr("fixture"), transport=httpx.MockTransport(lambda r: calls.append(r))
        ),
        LocalStore(tmp_path / "private"),
    )
    with pytest.raises(Denied), engine.begin() as c:
        submit_probe(c, p, snap, entry, handler)
    assert calls == []
    with engine.connect() as c:
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM tasks WHERE org_id=%s AND kind=%s", (p.org_id, KIND)
            ).scalar_one()
            == 0
        )


def test_research_probe_temporary_run_grant_is_source_scoped_and_revoked(engine, setup):
    from scripts.validate_research_sample import temporary_run_grant

    from app.security.authorization import Authorizer
    from app.security.governance import revoke

    p, snap, _entry = seed(engine, setup)
    with engine.begin() as c:
        source = c.exec_driver_sql(
            "SELECT source_id FROM intelligence_snapshots WHERE id=%s", (snap,)
        ).scalar_one()
        other = c.exec_driver_sql(
            "SELECT id FROM sources WHERE org_id=%s AND id<>%s LIMIT 1", (p.org_id, source)
        ).scalar_one()
        gid = temporary_run_grant(c, p, source, "temporary-test")
        az = Authorizer(c, p)
        assert az.allowed("research.run", az.scopes("sources", az.row("sources", source)))
        assert not az.allowed("research.run", az.scopes("sources", az.row("sources", other)))
    with engine.begin() as c:
        revoke(c, p, uuid4(), gid)
        az = Authorizer(c, p)
        assert not az.allowed("research.run", az.scopes("sources", az.row("sources", source)))
