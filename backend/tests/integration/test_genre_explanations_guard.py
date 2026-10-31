"""Local typed genre explanations guard; isolated PostgreSQL, no model or HTTP calls."""

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.collection.service import insert
from app.core.models import metadata
from app.core.repository import claim_task, create_task, finish_task
from tests.integration.test_knowledge import editor
from tests.integration.test_topics import configured

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def test_genre_guard_installed(engine):
    with engine.connect() as c:
        assert c.exec_driver_sql(
            "SELECT to_regprocedure('cip_genre_explanation_guard()') IS NOT NULL"
        ).scalar_one()


def prepared(engine, setup, monkeypatch):
    from app.knowledge.legacy_import import import_rows, parse_genres
    from app.knowledge.service import listing
    from app.model_config import resolve

    p = configured(engine, setup, monkeypatch)
    editor(engine, setup)
    source = (
        "# 模块16 · 海外本土化 + 140+题材库\n### 合成题材\nM01 · 合成逆袭\n## 四、A↔B对应速查表"
    )
    with engine.begin() as c:
        import_rows(
            c,
            p,
            parse_genres(source),
            source_text=source,
            source_name="synthetic.md",
            category="genre",
            reason="隔离测试",
        )
        item = listing(c, p, "motion_comic", category="genre")["items"][0]
        cfg = json.loads(json.dumps(resolve(c, p, "motion_comic", "topic"), default=str))
    return p, item, cfg


def build(c, p, item, cfg, *, mutate=None, output_mutate=None, artifact=None):
    data = {
        "schema_version": 1,
        "business_code": "motion_comic",
        "targets": [
            {
                "revision_id": str(item["revision_id"]),
                "knowledge_id": str(item["id"]),
                "publication_id": str(item["publication_id"]),
                "title": item["title"],
                "tags": item["revision"]["tags"],
            }
        ],
        "config": json.loads(json.dumps(cfg)),
        "source_reuse": "user_authorized_existing_topic_source",
        "reason": "用户明确授权",
    }
    if mutate:
        mutate(data)
    text = json.dumps(data, ensure_ascii=False)
    raw = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="manual",
        asset_kind="response",
        submitted_by=p.member_id,
        body_text=text,
        sha256="0" * 64 if artifact == "source_sha" else hashlib.sha256(text.encode()).hexdigest(),
        captured_at=datetime.now(UTC),
    )
    tid, _ = create_task(
        c,
        {
            "org_id": p.org_id,
            "kind": "knowledge.genre_explain",
            "handler_version": "1",
            "business_code": "motion_comic",
            "raw_asset_id": raw,
            "requested_by": p.member_id,
            "execution_authorized_by": p.member_id,
            "max_attempts": 1,
            "max_external_calls": 1,
            "idempotency_key": str(uuid4()),
            "input_sha256": "a" * 64,
        },
        [
            {"role": "freeze", "raw_asset_id": raw},
            {"role": "model", "ai_config_revision_id": UUID(cfg["revision_id"])},
            {"role": "target", "knowledge_revision_id": item["revision_id"]},
        ],
    )
    lock = c.exec_driver_sql("SELECT lock_version FROM tasks WHERE id=%s", (tid,)).scalar_one()
    attempt, token, version = claim_task(c, p.org_id, tid, lock)
    output = {
        "items": [
            {"revision_id": str(item["revision_id"]), "explanation": "主角通过行动改变处境的题材。"}
        ]
    }
    if output_mutate:
        output_mutate(output)
    body = json.dumps(output, ensure_ascii=False)
    sha = hashlib.sha256(body.encode()).hexdigest()
    fid = insert(
        c,
        "file_objects",
        p.org_id,
        storage_backend="local",
        storage_key=str(uuid4()),
        media_type="application/json",
        byte_size=len(body.encode()),
        sha256=sha,
        uploaded_by=p.member_id,
        validation_state="accepted",
    )
    eid = insert(
        c,
        "ai_executions",
        p.org_id,
        task_id=tid,
        attempt_id=attempt,
        config_revision_id=UUID(cfg["revision_id"]),
        invocation_no=1,
        input_sha256="b" * 64,
        input_manifest_file_id=fid,
    )
    c.exec_driver_sql(
        "UPDATE ai_executions SET output_file_id=%s,result_state='completed',finished_at=clock_timestamp() WHERE id=%s",
        (fid, eid),
    )
    out = insert(
        c,
        "raw_assets",
        p.org_id,
        origin="processing",
        asset_kind="response",
        processing_task_id=tid,
        parent_raw_asset_id=raw,
        body_text=body + " " if artifact == "body_sha" else body,
        sha256="0" * 64 if artifact == "output_sha" else sha,
        captured_at=datetime.now(UTC),
    )
    for position, values in enumerate(
        [
            {"role": "genre_explanations", "raw_asset_id": out},
            {"role": "model", "ai_execution_id": eid},
        ]
    ):
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(org_id=p.org_id, task_id=tid, position=position, **values)
        )
    if artifact == "extra_output":
        c.execute(
            metadata.tables["task_outputs"]
            .insert()
            .values(org_id=p.org_id, task_id=tid, position=2, role="extra", raw_asset_id=out)
        )
    finish_task(c, p.org_id, tid, attempt, token, version)
    return tid


def test_genre_guard_accepts_exact_success(engine, setup, monkeypatch):
    p, item, cfg = prepared(engine, setup, monkeypatch)
    with engine.begin() as c:
        build(c, p, item, cfg)
        c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize(
    "case",
    ["revision", "knowledge", "publication", "title", "tags", "source_reuse", "reason", "config"],
)
def test_genre_guard_rejects_frozen_mismatch(engine, setup, monkeypatch, case):
    p, item, cfg = prepared(engine, setup, monkeypatch)

    def tamper(data):
        if case in ("revision", "knowledge", "publication"):
            data["targets"][0][case + "_id"] = str(uuid4())
        elif case in ("title", "tags"):
            data["targets"][0][case] = "wrong" if case == "title" else []
        elif case == "config":
            data["config"]["revision_id"] = str(uuid4())
        else:
            data[case] = ""

    with pytest.raises(Exception, match="genre explanation"), engine.begin() as c:
        build(c, p, item, cfg, mutate=tamper)
        c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "duplicate",
        "wrong_revision",
        "blank",
        "long",
        "newline",
        "two_sentences",
        "not_chinese",
        "missing_period",
        "exclamation_end",
    ],
)
def test_genre_guard_rejects_invalid_output(engine, setup, monkeypatch, case):
    p, item, cfg = prepared(engine, setup, monkeypatch)

    def tamper(out):
        if case == "missing":
            out["items"] = []
        elif case == "duplicate":
            out["items"] *= 2
        elif case == "wrong_revision":
            out["items"][0]["revision_id"] = str(uuid4())
        else:
            out["items"][0]["explanation"] = {
                "blank": " ",
                "long": "长" * 181,
                "newline": "第一行\n第二行",
                "two_sentences": "第一句。第二句。",
                "not_chinese": "English only.",
                "missing_period": "主角通过行动改变处境的题材",
                "exclamation_end": "主角通过行动改变处境的题材！",
            }[case]

    with pytest.raises(Exception, match="genre explanation"), engine.begin() as c:
        build(c, p, item, cfg, output_mutate=tamper)
        c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.parametrize("artifact", ["source_sha", "output_sha", "body_sha", "extra_output"])
def test_genre_guard_rejects_digest_or_output_forgery(engine, setup, monkeypatch, artifact):
    p, item, cfg = prepared(engine, setup, monkeypatch)
    with pytest.raises(Exception, match="genre explanation"), engine.begin() as c:
        build(c, p, item, cfg, artifact=artifact)
        c.exec_driver_sql("SET CONSTRAINTS ALL IMMEDIATE")
