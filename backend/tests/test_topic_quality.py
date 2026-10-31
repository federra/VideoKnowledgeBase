"""Originality heuristics and the generation abstraction boundary (no external calls)."""

import copy
import json
from uuid import uuid4

import pytest

from app.tasks.service import TaskError


def refs():
    return {
        "sparks": [],
        "knowledge": [],
        "intelligence": [
            {
                "entry_id": str(uuid4()),
                "title": "星港遗嘱",
                "description": "林照野被迫回到星港调查父亲留下的机械遗嘱，却发现每次修复都会抹掉一个亲人的记忆。",
            }
        ],
    }


def abstraction(r):
    return {
        "sources": [
            {
                "source_id": "intelligence:" + r["intelligence"][0]["entry_id"],
                "emotion": "失去亲密关系的恐惧",
                "conflict": "追求真相与保护关系相互排斥",
                "cost": "每次推进都损害已有关系",
                "structure": "逐步揭露并加重选择代价",
                "forbidden_names": ["林照野", "星港"],
            }
        ]
    }


def test_copied_long_fragment_is_risk_and_spark_is_not_a_comparison_source():
    from app.topics.quality import guard, screen

    r = refs()
    copied = {"logline": r["intelligence"][0]["description"]}
    assert screen(copied, r)["status"] == "risk"
    with pytest.raises(TaskError, match="ORIGINALITY_RISK"):
        guard(copied, r)
    assert (
        screen(copied, {"sparks": [{"text": copied["logline"]}]})["status"] == "no_obvious_overlap"
    )
    assert screen(copied, {})["status"] == "unchecked"
    assert "全网" in screen(copied, r)["limitations"]


def test_shared_small_ngrams_catch_fragmented_copy_and_new_direction_is_clear():
    from app.topics.quality import screen

    r = refs()
    copied = {"logline": "被迫回到星港调查；父亲留下的机械；每次修复都会抹掉"}
    assert screen(copied, r)["status"] == "risk"
    assert (
        screen({"logline": "乡村邮递员为了救助失语儿童，决定挑战当地的保守习俗。"}, r)["status"]
        == "no_obvious_overlap"
    )


def test_abstraction_rejects_unknown_sources_false_names_and_copied_mechanisms():
    from app.topics.generation_v2 import validate_abstraction

    r = refs()
    a = abstraction(r)
    assert validate_abstraction(a, r) == a
    for mutation in ("source", "name", "copy", "missing", "extra"):
        bad = copy.deepcopy(a)
        if mutation == "source":
            bad["sources"][0]["source_id"] = "intelligence:" + str(uuid4())
        elif mutation == "name":
            bad["sources"][0]["forbidden_names"] = ["并不存在的人物"]
        elif mutation == "copy":
            bad["sources"][0]["structure"] = r["intelligence"][0]["description"]
        elif mutation == "missing":
            bad["sources"] = []
        else:
            bad["sources"][0]["unexpected"] = True
        with pytest.raises((ValueError, TaskError)):
            validate_abstraction(bad, r)


def test_second_phase_contains_only_mechanisms_and_private_intent():
    from app.topics.generation_v2 import creation_input, validate_abstraction

    r = refs()
    r["sparks"] = [{"text": "我希望保留自己取的名字阿澄", "revision_id": str(uuid4())}]
    data = {"source_refs": r, "instructions": "重视亲情"}
    value = creation_input(data, validate_abstraction(abstraction(r), r))
    text = json.dumps(value, ensure_ascii=False)
    for forbidden in [
        r["intelligence"][0]["description"],
        "林照野",
        "星港",
        r["intelligence"][0]["entry_id"],
    ]:
        assert forbidden not in text
    assert "我希望保留自己取的名字阿澄" in text
    assert "重视亲情" in text


def test_banned_names_never_publish_even_if_their_fragment_is_short():
    from app.topics.generation_v2 import validate_creation
    from tests.test_topic_generation import fields

    r = refs()
    with pytest.raises(TaskError, match="ORIGINALITY_RISK"):
        validate_creation({"topics": [fields("林照野的新人生")]}, "brainstorm", r, abstraction(r))


def test_any_risky_card_rejects_entire_batch():
    from app.topics.generation_v2 import validate_creation
    from tests.test_topic_generation import fields

    r = refs()
    batch = {"topics": [fields(str(i)) for i in range(5)]}
    batch["topics"][4]["logline"] = r["intelligence"][0]["description"]
    with pytest.raises(TaskError, match="ORIGINALITY_RISK"):
        validate_creation(batch, "batch", r, abstraction(r))


def test_declared_name_cannot_cross_source_or_leak_into_mechanisms():
    from app.topics.generation_v2 import validate_abstraction

    r = refs()
    value = abstraction(r)
    value["sources"][0]["emotion"] = "林照野渴望亲密关系"
    with pytest.raises(ValueError, match="proper name"):
        validate_abstraction(value, r)
    value = abstraction(r)
    value["sources"].append(copy.deepcopy(value["sources"][0]))
    with pytest.raises(ValueError, match="exactly"):
        validate_abstraction(value, r)


def test_context_uses_snapshot_display_name_as_frozen_title(monkeypatch):
    from types import SimpleNamespace

    from app.intelligence import service as intelligence
    from app.topics import generation

    rid, oid, eid, sid = uuid4(), uuid4(), uuid4(), uuid4()

    class Connection:
        def exec_driver_sql(self, *_):
            return SimpleNamespace(scalars=list)

    monkeypatch.setattr(generation, "Authorizer", lambda *_: None)
    monkeypatch.setattr(generation.service, "row", lambda *_: {"raw_asset_id": rid})
    monkeypatch.setattr(
        intelligence,
        "selected",
        lambda *_, **__: [
            (
                {"id": sid, "created_at": 1},
                [
                    {
                        "entry": {
                            "id": eid,
                            "observation": {
                                "id": oid,
                                "kind": "content",
                                "display_name": "冻结的真实展示名",
                                "description": "独立简介",
                            },
                        }
                    }
                ],
            )
        ],
    )
    value = generation.context(Connection(), SimpleNamespace(org_id=uuid4()), "motion_comic", [])
    assert value["intelligence"][0]["title"] == "冻结的真实展示名"
    assert value["intelligence"][0]["entry_id"] == str(eid)


def test_edited_brainstorm_save_rechecks_names_from_exact_abstraction(monkeypatch):
    from types import SimpleNamespace

    from app.topics import generation_v2
    from tests.test_topic_generation import fields

    r = refs()

    class Connection:
        def exec_driver_sql(self, *_):
            return SimpleNamespace(scalar_one=lambda: str(uuid4()))

    monkeypatch.setattr(
        generation_v2,
        "stored_output",
        lambda c, p, tid, eid, validator, **_: validator(abstraction(r)),
    )
    with pytest.raises(TaskError, match="ORIGINALITY_RISK"):
        generation_v2.validate_saved_creation(
            Connection(),
            SimpleNamespace(org_id=uuid4()),
            {"id": uuid4()},
            {"source_refs": r, "mode": "brainstorm"},
            fields("林照野的新人生"),
        )


def test_reusable_knowledge_genre_name_is_not_a_work_title():
    from app.topics.quality import screen
    refs={"knowledge":[{"revision_id":"k","title":"都市兵王","text":"M03 · 都市兵王\n来源分组：都市男频（15个）"}]}
    assert screen({"title":"都市兵王的面包铺"},refs)["status"] == "no_obvious_overlap"
