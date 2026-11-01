"""Synthetic users in disposable PostgreSQL, without collection or model calls."""

from uuid import uuid4

import pytest

from app.security.authorization import Authorizer
from app.security.errors import Denied
from app.security.sessions import MemberPrincipal
from app.topics import generation, scoring, service
from app.topics.contracts import SparkWrite, TopicHandoff, TopicSelect, TopicUpdate
from app.topics.score_contracts import EvaluateRequest
from tests.integration.test_security import grant
from tests.integration.test_topics import create, fields, principal

pytest_plugins = ("tests.integration.test_security",)
pytestmark = pytest.mark.database


def people(engine, setup):
    admin = principal(engine, setup)
    users = []
    with engine.begin() as c:
        for _ in range(2):
            mid = uuid4()
            c.exec_driver_sql(
                "INSERT INTO members(id,org_id,login_name,display_name) VALUES (%s,%s,%s,'private user')",
                (mid, admin.org_id, str(mid)),
            )
            grant(
                c,
                admin.org_id,
                admin.member_id,
                mid,
                [
                    "content.read",
                    "content.write",
                    "content.export",
                    "task.read",
                    "task.manage",
                    "evidence.read",
                    "file.read",
                ],
            )
            users.append(MemberPrincipal(admin.org_id, mid))
    return admin, *users


def test_personal_lists_counts_and_admin_explicit_read(engine, setup):
    admin, alice, bob = people(engine, setup)
    a, b = create(engine, alice, "Alice private"), create(engine, bob, "Bob private")
    with engine.begin() as c:
        s = service.save_spark(c, alice, str(uuid4()), SparkWrite(text="Alice spark"))
        for p, expected in [(alice, a["id"]), (bob, b["id"])]:
            result = service.listing(c, p, "motion_comic", "candidate", 1)
            assert result["total"] == "1"
            assert [x["id"] for x in result["items"]] == [expected]
        assert service.listing(c, admin, "motion_comic", "candidate", 1)["total"] == "0"
        assert service.sparks(c, bob)["items"] == []
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.topic(c, bob, a["id"])
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.spark(c, bob, s["id"])
        assert service.topic(c, admin, a["id"])["id"] == a["id"]


@pytest.mark.parametrize("operation", ["edit", "select", "export", "score"])
def test_other_user_and_admin_cannot_mutate(engine, setup, operation):
    admin, alice, bob = people(engine, setup)
    a = create(engine, alice)
    for actor in (bob, admin):
        with engine.begin() as c, pytest.raises(Denied, match="NOT_FOUND"):
            if operation == "edit":
                service.revise(
                    c,
                    actor,
                    str(uuid4()),
                    a["id"],
                    TopicUpdate(expected_version=1, fields=fields("changed")),
                )
            elif operation == "select":
                service.choose(c, actor, str(uuid4()), a["id"], TopicSelect(expected_version=1))
            elif operation == "export":
                service.handoff(
                    c,
                    actor,
                    str(uuid4()),
                    a["id"],
                    TopicHandoff(expected_version=1, method="copy", phase="authorize"),
                )
            else:
                scoring.start(c, actor, str(uuid4()), a["id"], EvaluateRequest(expected_version=1))


def test_personal_task_raw_file_closure(engine, setup, monkeypatch, tmp_path):
    from app.tasks.service import manage
    from tests.integration.test_topic_scoring import setup_score

    owner, handler, calls = setup_score(engine, setup, monkeypatch, tmp_path)
    _, alice, bob = people(engine, setup)
    a = create(engine, owner)
    with engine.begin() as c:
        value = scoring.start(
            c, owner, str(uuid4()), a["id"], EvaluateRequest(expected_version=1), handler
        )
        task = service.row(c, owner, "tasks", value["id"])
    from app.tasks.service import Runner

    assert (
        Runner(engine, {(scoring.KIND, handler.version): handler}).run(owner.org_id, value["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        fid = c.exec_driver_sql(
            "SELECT output_file_id FROM ai_executions WHERE org_id=%s AND task_id=%s",
            (owner.org_id, task["id"]),
        ).scalar_one()
        for actor in (alice, bob):
            az = Authorizer(c, actor)
            for kind, ident in [
                ("tasks", task["id"]),
                ("raw_assets", task["raw_asset_id"]),
                ("file_objects", fid),
            ]:
                with pytest.raises(Denied, match="NOT_FOUND"):
                    az.read(kind, ident)
            assert az.list("tasks") == []
            from app.collection.console import list_tasks, task_view

            assert list_tasks(c, actor, "motion_comic")["total"] == "0"
            with pytest.raises(Denied, match="NOT_FOUND"):
                task_view(c, actor, task["id"])
            with pytest.raises(Denied, match="NOT_FOUND"):
                scoring.read(c, actor, task["id"])
            with pytest.raises(Denied, match="NOT_FOUND"):
                manage(c, actor, task["id"], task["lock_version"])
        assert len(calls) == 1


def test_explicit_admin_space_sources_business_audit_and_revocation(engine, setup):
    from app.accounts.personal_http import space

    admin, alice, bob = people(engine, setup)
    with engine.begin() as c:
        s = service.save_spark(c, alice, str(uuid4()), SparkWrite(text="Private lineage"))
        rid = c.exec_driver_sql(
            "SELECT current_revision_id FROM topic_sparks WHERE id=%s", (s["id"],)
        ).scalar_one()
        tid = service.add(
            c,
            alice,
            "motion_comic",
            fields().model_dump(),
            source_refs={"sparks": [{"id": str(s["id"]), "revision_id": str(rid)}]},
        )
        service.add(c, alice, "story_short", fields("story private").model_dump())
        result = space(c, admin, alice.member_id, "motion_comic")
        assert result["member"]["id"] == alice.member_id
        assert [x["id"] for x in result["topics"]] == [tid]
        assert [x["id"] for x in result["sparks"]] == [s["id"]]
        assert (
            c.exec_driver_sql(
                "SELECT count(*) FROM audit_events WHERE org_id=%s AND actor_member_id=%s AND action_code='member.space.read'",
                (admin.org_id, admin.member_id),
            ).scalar_one()
            == 1
        )
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            space(c, bob, alice.member_id, "motion_comic")
        # A scoped member.manage grant must never act as an administrator.
        grant(
            c,
            admin.org_id,
            admin.member_id,
            bob.member_id,
            ["member.manage"],
            "business",
            "motion_comic",
        )
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            space(c, bob, alice.member_id, "motion_comic")
    with engine.begin() as c:
        c.exec_driver_sql(
            "UPDATE grants SET revoked_at=clock_timestamp(),lock_version=lock_version+1 WHERE org_id=%s AND member_id=%s AND role_id IN (SELECT role_id FROM role_actions WHERE org_id=%s AND action_code='member.manage')",
            (admin.org_id, admin.member_id, admin.org_id),
        )
    with engine.begin() as c:
        with pytest.raises(Denied, match="ACCESS_DENIED"):
            space(c, admin, alice.member_id, "motion_comic")
        with pytest.raises(Denied, match="NOT_FOUND"):
            service.topic(c, admin, tid)


def test_generation_private_manifest_output_file_and_admin_cannot_control(
    engine, setup, monkeypatch, tmp_path
):
    from app.security.read_authorizer import ReadAuthorizer
    from app.tasks.service import Runner, manage
    from app.topics.contracts import GenerateRequest, GenerationSave
    from tests.integration.test_topics import configured, handler_for

    owner = configured(engine, setup, monkeypatch)
    _, alice, bob = people(engine, setup)
    calls = []
    handler = handler_for(tmp_path, {"topics": [fields().model_dump()]}, calls)
    with engine.begin() as c:
        grant(
            c,
            owner.org_id,
            owner.member_id,
            owner.member_id,
            ["task.read", "task.manage", "file.read"],
        )
        seed = service.save_spark(
            c, owner, str(uuid4()), SparkWrite(text="Private generation spark")
        )
        value = generation.start(
            c,
            owner,
            str(uuid4()),
            GenerateRequest(
                business_code="motion_comic", mode="brainstorm", spark_ids=[seed["id"]]
            ),
            handler,
        )
    # Reading or saving a foreign generation fails before state/output processing.
    with engine.begin() as c:
        task = service.row(c, owner, "tasks", value["id"])
        for actor in (alice, bob):
            with pytest.raises(Denied, match="NOT_FOUND"):
                generation.read(c, actor, task["id"])
            with pytest.raises(Denied, match="NOT_FOUND"):
                generation.save(c, actor, str(uuid4()), task["id"], GenerationSave(fields=fields()))
            with pytest.raises(Denied, match="NOT_FOUND"):
                ReadAuthorizer(c, actor).read("raw_assets", task["raw_asset_id"])
    # Fake model writes the same immutable execution/files as production; no network.
    assert (
        Runner(engine, {(generation.KIND, handler.version): handler}).run(owner.org_id, value["id"])
        == "succeeded"
    )
    with engine.begin() as c:
        output = c.exec_driver_sql(
            "SELECT raw_asset_id FROM task_outputs WHERE org_id=%s AND task_id=%s AND role='topic_generation' AND raw_asset_id IS NOT NULL",
            (owner.org_id, task["id"]),
        ).scalar_one()
        files = c.exec_driver_sql(
            "SELECT input_manifest_file_id,output_file_id FROM ai_executions WHERE org_id=%s AND task_id=%s",
            (owner.org_id, task["id"]),
        ).one()
        for actor in (alice, bob):
            az = ReadAuthorizer(c, actor)
            for kind, ident in [("raw_assets", output), *[("file_objects", f) for f in files]]:
                with pytest.raises(Denied, match="NOT_FOUND"):
                    az.read(kind, ident)
                if kind == "file_objects":
                    with pytest.raises(Denied, match="NOT_FOUND"):
                        az.file(ident)
        # A second administrator can inspect but cannot cancel/retry another owner.
        grant(c, owner.org_id, owner.member_id, alice.member_id, ["member.manage"])
        from app.tasks.service import TaskError

        with pytest.raises(TaskError, match="INVALID_INPUT"):
            handler.freeze(c, task, Authorizer(c, alice))
        from app.topics.generation_v2 import GenerateV2

        with pytest.raises(TaskError, match="INVALID_INPUT"):
            GenerateV2().freeze(
                c, dict(task, handler_version="2", max_external_calls=2), Authorizer(c, alice)
            )
        assert Authorizer(c, alice).read("tasks", task["id"])["id"] == task["id"]
        assert Authorizer(c, alice).read("raw_assets", output)["id"] == output
        for fid in files:
            assert Authorizer(c, alice).file(fid)["id"] == fid
        with pytest.raises(Denied, match="NOT_FOUND"):
            manage(c, alice, task["id"], task["lock_version"])
        with pytest.raises(Denied, match="NOT_FOUND"):
            Authorizer(c, alice).require("tasks", task["id"], "task.manage")
    assert len(calls) == 1
