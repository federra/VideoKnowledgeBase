"""S05.1 contracts are executable validation, not implemented business services."""

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.contracts.api import contract_app
from app.contracts.models import Count, ErrorEnvelope, IntakeCreate
from app.main import app


def intake():
    return {
        "snapshot_entry_id": str(uuid4()),
        "feedback_id": None,
        "target": {"kind": "existing", "work_id": str(uuid4()), "expected_lock_version": "1"},
        "confirmed_business_code": "motion_comic",
        "material_kind": "reference",
        "assessment": {
            "quality_grade": "A",
            "genre_tags": ["悬疑"],
            "learning_tags": ["节奏"],
            "additional_learning": None,
            "total_episode_count": None,
            "episode_no": None,
        },
        "cross_business_confirmed": False,
    }


def test_planned_operations_are_separate_from_runtime():
    actual = TestClient(app).get("/openapi.json").json()
    planned = contract_app.openapi()
    assert set(actual["paths"]) == {
        "/api/health",
        "/api/v1/session",
        "/api/v1/files",
        "/api/v1/files/from-url",
        "/api/v1/files/{file_id}/content",
        "/api/v1/collection-jobs",
        "/api/v1/sources",
        "/api/v1/sources/{source_id}",
        "/api/v1/tasks",
        "/api/v1/tasks/{task_id}",
        "/api/v1/tasks/{task_id}/cancel",
        "/api/v1/tasks/{task_id}/retry",
        "/api/v1/intelligence/feed",
        "/api/v1/intelligence/novels",
        "/api/v1/intelligence/snapshots",
        "/api/v1/intelligence/snapshots/{snapshot_id}/entries",
        "/api/v1/intelligence/feedback/{feedback_id}",
        "/api/v1/intelligence/entries/{entry_id}/feedback",
        "/api/v1/intelligence/entries/{entry_id}/research-evidence",
        "/api/v1/intelligence/research-evidence/{handoff_id}",
        "/api/v1/works",
        "/api/v1/works/{work_id}",
        "/api/v1/works/{work_id}/materials",
        "/api/v1/research/submissions",
        "/api/v1/research/direct",
        "/api/v1/input-sets",
        "/api/v1/input-sets/{input_set_id}",
        "/api/v1/analysis-runs",
        "/api/v1/reports/{report_id}",
        "/api/v1/evaluations/{evaluation_id}",
        "/api/v1/works/{work_id}/analysis-history",
        "/api/v1/prediction-drafts",
        "/api/v1/prediction-drafts/{draft_id}",
        "/api/v1/prediction-drafts/{draft_id}/freeze",
        "/api/v1/predictions/{prediction_id}",
        "/api/v1/predictions/{prediction_id}/retract",
        "/api/v1/knowledge",
        "/api/v1/knowledge/candidates",
        "/api/v1/knowledge/candidates/{knowledge_id}",
        "/api/v1/knowledge/revisions/{revision_id}/sources",
        "/api/v1/knowledge/{knowledge_id}",
        "/api/v1/knowledge/{knowledge_id}/revisions",
        "/api/v1/knowledge/revisions/{revision_id}",
        "/api/v1/reviews",
        "/api/v1/reviews/{request_id}",
        "/api/v1/reviews/{request_id}/human-decisions",
        "/api/v1/knowledge/{knowledge_id}/publications",
        "/api/v1/reviews/{request_id}/approve-publication",
        "/api/v1/reports/{report_id}/knowledge-extractions",
    }
    assert "/api/v1/research/submissions" in planned["paths"]
    for path, methods in planned["paths"].items():
        if path == "/api/health":
            continue
        for op in methods.values():
            assert op["x-implementation-status"] == (
                "implemented"
                if path == "/api/v1/session"
                or path.startswith("/api/v1/files")
                or path
                in {
                    "/api/v1/intelligence/feed",
        "/api/v1/intelligence/novels",
                    "/api/v1/intelligence/snapshots",
                    "/api/v1/intelligence/snapshots/{snapshot_id}/entries",
                    "/api/v1/intelligence/feedback/{feedback_id}",
                    "/api/v1/intelligence/entries/{entry_id}/feedback",
                    "/api/v1/intelligence/entries/{entry_id}/research-evidence",
                    "/api/v1/intelligence/research-evidence/{handoff_id}",
                    "/api/v1/works",
                    "/api/v1/works/{work_id}",
                    "/api/v1/works/{work_id}/materials",
                    "/api/v1/research/submissions",
                    "/api/v1/research/direct",
                    "/api/v1/input-sets",
                    "/api/v1/input-sets/{input_set_id}",
                    "/api/v1/analysis-runs",
                    "/api/v1/reports/{report_id}",
                    "/api/v1/evaluations/{evaluation_id}",
                    "/api/v1/works/{work_id}/analysis-history",
                    "/api/v1/prediction-drafts",
                    "/api/v1/prediction-drafts/{draft_id}",
                    "/api/v1/prediction-drafts/{draft_id}/freeze",
                    "/api/v1/predictions/{prediction_id}",
                    "/api/v1/predictions/{prediction_id}/retract",
                    "/api/v1/knowledge",
                    "/api/v1/knowledge/candidates",
                    "/api/v1/knowledge/candidates/{knowledge_id}",
                    "/api/v1/knowledge/revisions/{revision_id}/sources",
                    "/api/v1/knowledge/{knowledge_id}",
                    "/api/v1/knowledge/{knowledge_id}/revisions",
                    "/api/v1/knowledge/revisions/{revision_id}",
                    "/api/v1/reviews",
                    "/api/v1/reviews/{request_id}",
                    "/api/v1/reviews/{request_id}/human-decisions",
                    "/api/v1/knowledge/{knowledge_id}/publications",
                    "/api/v1/reviews/{request_id}/approve-publication",
                    "/api/v1/reports/{report_id}/knowledge-extractions",
                }
                or path
                in {
                    "/api/v1/collection-jobs",
                    "/api/v1/sources",
                    "/api/v1/sources/{source_id}",
                    "/api/v1/tasks",
                    "/api/v1/tasks/{task_id}",
                    "/api/v1/tasks/{task_id}/cancel",
                    "/api/v1/tasks/{task_id}/retry",
                }
                else "planned"
            )
            assert "503" in op["responses"]
            assert op.get("x-required-actions") is not None


def test_contract_preview_never_returns_fake_success():
    response = TestClient(contract_app).get("/api/v1/tasks/" + str(uuid4()))
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_NOT_READY"


@pytest.mark.parametrize(
    "change",
    [
        {"org_id": str(uuid4())},
        {
            "assessment": {
                "quality_grade": "A",
                "genre_tags": [],
                "learning_tags": [],
                "additional_learning": None,
            }
        },
        {
            "assessment": {
                "quality_grade": "A",
                "genre_tags": ["悬疑"],
                "learning_tags": [],
                "additional_learning": " ",
            }
        },
        {
            "assessment": {
                "quality_grade": "A",
                "genre_tags": ["悬疑"],
                "learning_tags": ["节奏"],
                "total_episode_count": 2,
                "episode_no": 3,
            }
        },
        {"target": {"kind": "existing", "work_id": str(uuid4()), "expected_lock_version": 1}},
        {
            "confirmed_business_code": "story_short",
            "assessment": {
                "quality_grade": "A",
                "genre_tags": ["悬疑"],
                "learning_tags": ["节奏"],
                "episode_no": 1,
            },
        },
    ],
)
def test_intake_rejects_unknown_identity_empty_learning_invalid_episodes_and_numeric_version(
    change,
):
    with pytest.raises(ValidationError):
        IntakeCreate.model_validate_json(json.dumps({**intake(), **change}))


def test_intake_keeps_exact_source_version_and_unknown_episodes():
    value = IntakeCreate.model_validate_json(json.dumps(intake()))
    assert value.assessment.total_episode_count is None
    assert value.feedback_id is None
    assert value.model_dump(mode="json")["target"]["expected_lock_version"] == "1"


@pytest.mark.parametrize("value", [9007199254740993, "-1", "01", "9223372036854775808"])
def test_int64_wire_values_do_not_silently_round_or_coerce(value):
    with pytest.raises(ValidationError):
        TypeAdapter(Count).validate_python(value)


def test_int64_above_javascript_precision_is_preserved():
    assert TypeAdapter(Count).validate_python("9007199254740993") == "9007199254740993"


def test_frozen_prediction_does_not_accept_client_generated_time_or_actor():
    from app.contracts.models import PredictionFreeze

    with pytest.raises(ValidationError):
        PredictionFreeze.model_validate(
            {"expected_lock_version": "1", "frozen_at": "2000-01-01T00:00:00Z"}
        )


def test_error_has_no_unvalidated_input_echo():
    with pytest.raises(ValidationError):
        ErrorEnvelope.model_validate(
            {
                "request_id": str(uuid4()),
                "error": {"code": "anything", "message": "x", "input": "secret"},
            }
        )


def test_preview_validation_never_echoes_password_or_private_body():
    client = TestClient(contract_app)
    response = client.post(
        "/api/v1/session",
        json={"org_id": "bad", "login_name": "tester", "password": "private-secret"},
    )
    assert response.status_code == 422
    assert "private-secret" not in response.text
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
    assert "input" not in response.text


def test_all_writes_have_csrf_and_idempotency_and_gets_have_no_body():
    from app.contracts.api import OPERATIONS

    schema = contract_app.openapi()
    assert len({v.name for v in OPERATIONS}) == len(OPERATIONS)
    for operation in OPERATIONS:
        item = schema["paths"]["/api/v1" + operation.path][operation.method.lower()]
        if operation.method == "GET":
            assert "requestBody" not in item
        if not operation.public:
            assert item["security"] == [{"SessionCookie": []}]
        if operation.method != "GET" and not operation.public:
            headers = {
                p["name"] for p in item["parameters"] if p["in"] == "header" and p.get("required")
            }
            assert "X-CSRF-Token" in headers
            if operation.name != "logout":
                assert "Idempotency-Key" in headers


def test_snapshot_paging_is_limited_to_demo_ten_rows():
    response = TestClient(contract_app).get(
        "/api/v1/intelligence/snapshots/" + str(uuid4()) + "/entries?page_size=11"
    )
    assert response.status_code == 422


def test_read_models_do_not_require_previous_write_preconditions():
    schema = contract_app.openapi()["components"]["schemas"]
    assert "expected_artifact_lock_version" not in schema["ArtifactVersion"]["properties"]


def test_unknown_secret_field_name_is_not_echoed_in_validation_path():
    response = TestClient(contract_app).post(
        "/api/v1/session",
        json={
            "org_id": str(uuid4()),
            "login_name": "test",
            "password": "private",
            "secret-api-key-in-field-name": "x",
        },
    )
    assert response.status_code == 422
    assert "secret-api-key-in-field-name" not in response.text


def test_preview_error_request_id_matches_header():
    response = TestClient(contract_app).get("/api/v1/tasks/" + str(uuid4()))
    assert response.headers["X-Request-ID"] == response.json()["request_id"]


def test_catalog_permissions_and_errors_match_persisted_action_directory():
    from typing import get_args

    from app.contracts.api import OPERATIONS
    from app.contracts.models import ERROR_STATUS, ErrorCode
    from app.core.models import ACTIONS

    assert {a for op in OPERATIONS for a in op.actions} <= set(ACTIONS.split())
    assert set(get_args(ErrorCode)) == set(ERROR_STATUS)


@pytest.mark.parametrize("purpose", ["evaluation_review", "standard_approval"])
def test_human_only_review_purposes_do_not_offer_an_unapproved_extra_ai_call(purpose):
    from app.contracts.models import ReviewCreate

    with pytest.raises(ValidationError):
        ReviewCreate(purpose=purpose, target_id=uuid4(), execute_ai=True, max_external_calls=1)


def test_export_refuses_to_label_a_runtime_business_route_as_planned():
    from scripts.contracts import verify_registration

    runtime = {
        "paths": {
            "/api/health": {},
            "/api/v1/research/tasks": {"post": {"operationId": "createResearchTask"}},
        }
    }
    with pytest.raises(ValueError, match="planned"):
        verify_registration(runtime, contract_app.openapi())


def test_same_reference_name_does_not_hide_response_model_drift():
    from copy import deepcopy

    from scripts.contracts import verify_registration

    planned = deepcopy(contract_app.openapi())
    planned["paths"]["/api/v1/tasks/{task_id}"]["get"]["x-implementation-status"] = "implemented"
    runtime = deepcopy(planned)
    runtime["paths"] = {
        "/api/health": runtime["paths"]["/api/health"],
        "/api/v1/tasks/{task_id}": runtime["paths"]["/api/v1/tasks/{task_id}"],
    }
    runtime["components"]["schemas"]["Task"]["properties"]["lock_version"] = {"type": "integer"}
    with pytest.raises(ValueError, match="schema.*drift|drift.*schema"):
        verify_registration(runtime, planned)


def test_knowledge_round_trips_demo_stage_tags():
    from app.contracts.models import KnowledgeCreate

    value = KnowledgeCreate(
        title="t",
        body_text="b",
        knowledge_type="fact",
        browse_category="genre",
        business_codes=["motion_comic"],
        tags=[{"kind": "stage", "code": "script"}],
    )
    assert value.model_dump()["tags"] == [{"kind": "stage", "code": "script"}]


@pytest.mark.parametrize("position", [2147483648, 9007199254740993])
def test_input_positions_fit_database_integer_and_javascript(position):
    from app.contracts.models import InputItem

    with pytest.raises(ValidationError):
        InputItem(artifact_version_id=uuid4(), role="primary", position=position)


def test_keyword_is_not_all_whitespace():
    from app.contracts.models import KeywordTarget

    with pytest.raises(ValidationError):
        KeywordTarget(kind="keyword", keyword="   ")
