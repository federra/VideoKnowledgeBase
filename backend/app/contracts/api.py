"""Unregistered design application. Never mount this router on app.main.app.

The offline schema is the S05.1 contract target. Preview handlers validate shapes
and return 503; no database connection or external request is made.
"""

import inspect
import re
from dataclasses import dataclass
from datetime import date
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Body, Depends, FastAPI, Header, Query, Request, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import APIKeyCookie
from pydantic import Field

from app.api.health import router as health_router
from app.contracts import models as m
from app.intelligence import novel_contracts as n
from app.knowledge import contracts as k
from app.research import analysis_contracts as a
from app.research import contracts as r
from app.research import prediction_contracts as pr


class BusinessQuery(m.Contract):
    business_code: m.Business
    cursor: str | None = Field(default=None, max_length=2048)
    limit: int = Field(default=20, ge=1, le=100)
    q: str | None = Field(default=None, max_length=100)


class SnapshotQuery(m.Contract):
    business_code: m.Business
    business_date: date
    source_id: UUID | None = None
    view_kind: str | None = Field(
        default=None, pattern="^(account_discovery|creator_works|keyword_works|board)$"
    )


class FeedQuery(m.Contract):
    business_code: m.Business
    business_date: date
    lane: str = Field(default="board", pattern="^(board|creator)$")
    page: int = Field(default=1, ge=1, le=2147483647)
    q: str | None = Field(default=None, max_length=100)
    source_id: UUID | None = None
    accounts: str | None = Field(default=None, max_length=4096)
    video_catalog: str | None = Field(default=None, pattern="^(hongguo|tikhub)$")
    video_board: str | None = Field(
        default=None, pattern="^(hot-drama|hot-real-drama|hot-ai-drama|hot-comic-drama)$"
    )
    video_genre: str | None = Field(default=None, min_length=1, max_length=80)
    video_subgenre: str | None = Field(default=None, min_length=1, max_length=80)


class FeedbackQuery(m.Contract):
    business_code: m.Business
    business_date: date


class EntryQuery(m.Contract):
    page: int = Field(default=1, ge=1, le=2147483647)
    page_size: int = Field(default=10, ge=1, le=10)
    q: str | None = Field(default=None, max_length=100)
    account_id: UUID | None = None


class KnowledgeQuery(BusinessQuery):
    source_report_id: UUID | None = None
    browse_category: str | None = Field(
        default=None, pattern="^(genre|quote|payoff|failure|dna_case)$"
    )
    tag: str | None = Field(
        default=None, max_length=100, pattern=r"^(stage|task|genre|platform):\S.*$"
    )
    mode: str = Field(default="keyword", pattern="^(keyword|semantic)$")


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    name: str
    response: type
    actions: tuple[str, ...]
    stage: str
    request: type | None = None
    query: type | None = None
    status: int = 200
    permission_note: str = "本体、全部输入证据及文件依赖分别授权后取交集；组织来自会话。"
    public: bool = False
    implementation: str = "planned"
    binary: bool = False
    download: bool = False


OPERATIONS = [
    Operation(
        "POST",
        "/files",
        "uploadFile",
        m.FileInfo,
        ("content.write",),
        "S05.3",
        query=m.FileUploadQuery,
        status=201,
        implementation="implemented",
        binary=True,
        permission_note="先验作品及content.write；流限大小并重验权限，文件固定归属作品，回执及审计同事务。",
    ),
    Operation(
        "POST",
        "/files/from-url",
        "importFile",
        m.FileInfo,
        ("content.write",),
        "S05.3",
        request=m.FileFromUrl,
        status=201,
        implementation="implemented",
        permission_note="显式可信HTTPS素材主机；逐跳公网解析并固定连接IP；落库前重验权限，无通用分享页解析。",
    ),
    Operation(
        "GET",
        "/files/{file_id}/content",
        "downloadFile",
        bytes,
        ("file.read",),
        "S05.3",
        query=m.FileDownloadQuery,
        implementation="implemented",
        download=True,
        permission_note="每次当前鉴权，父对象实际关联；accepted文件仅attachment，无长期免鉴权URL。",
    ),
    Operation(
        "POST",
        "/session",
        "login",
        m.Session,
        (),
        "S05.2",
        request=m.Login,
        public=True,
        implementation="implemented",
        permission_note="受限本地开户，无开放自注册；组织及登录错误统一AUTH_INVALID。",
    ),
    Operation(
        "GET",
        "/session",
        "getSession",
        m.Session,
        (),
        "S05.2",
        permission_note="仅当前有效会话。",
        implementation="implemented",
    ),
    Operation(
        "DELETE",
        "/session",
        "logout",
        m.Acknowledged,
        (),
        "S05.2",
        permission_note="当前会话撤销，重复退出可成功。",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/sources",
        "listSources",
        m.Page[m.ConsoleSource],
        ("source.configure",),
        "S06",
        query=BusinessQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/sources",
        "createSource",
        m.ConsoleSource,
        ("source.configure",),
        "S06",
        request=m.ConsoleSourceCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "PATCH",
        "/sources/{source_id}",
        "updateSource",
        m.ConsoleSource,
        ("source.configure",),
        "S06",
        request=m.SourcePatch,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/collection-jobs",
        "startCollection",
        m.Accepted,
        ("collection.run",),
        "S06",
        request=m.CollectionCreate,
        implementation="implemented",
        status=202,
        permission_note="来源、连接能力及执行授权重检；总付费预算默认1，供应商分页不可自动扩散。",
    ),
    Operation(
        "GET",
        "/intelligence/novels",
        "getNovelFeed",
        n.NovelFeed,
        ("content.read",),
        "S08",
        query=n.NovelQuery,
        implementation="implemented",
        permission_note="小说独立快照，成员筛选后去重；在读人数不作播放量。",
    ),
    Operation(
        "GET",
        "/intelligence/feed",
        "getIntelligenceFeed",
        m.IntelligenceFeed,
        ("content.read",),
        "S06",
        query=FeedQuery,
        implementation="implemented",
        permission_note="仅指定上海业务日期的最新封存版本，来源及全部证据当前授权；缺失不回退、不补零。",
    ),
    Operation(
        "GET",
        "/intelligence/snapshots",
        "listSnapshots",
        list[m.Snapshot],
        ("content.read",),
        "S06",
        query=SnapshotQuery,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/intelligence/snapshots/{snapshot_id}/entries",
        "listSnapshotEntries",
        m.SnapshotPage,
        ("content.read",),
        "S06",
        query=EntryQuery,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/intelligence/feedback/{feedback_id}",
        "getFeedback",
        m.Feedback,
        ("content.read",),
        "S06.4",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/intelligence/entries/{entry_id}/feedback",
        "getEntryFeedback",
        m.EntryFeedback,
        ("content.read",),
        "S06.4",
        query=FeedbackQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/intelligence/entries/{entry_id}/research-evidence",
        "freezeResearchEvidence",
        m.ResearchEvidencePackage,
        ("content.read", "research.submit"),
        "S06.4",
        request=m.ResearchEvidenceCreate,
        status=201,
        implementation="implemented",
        permission_note="服务端冻结指定快照、条目、反馈与原文引用；当前全部证据授权及research.submit，幂等重放亦重验，无任务／付费调用。",
    ),
    Operation(
        "GET",
        "/intelligence/research-evidence/{handoff_id}",
        "getResearchEvidence",
        m.ResearchEvidencePackage,
        ("content.read",),
        "S06.4",
        implementation="implemented",
        permission_note="读取独立冻结包，重验全部原始依赖与摘要，不自动替换新版本。",
    ),
    Operation(
        "GET",
        "/works",
        "listWorks",
        r.WorkPage,
        ("content.read",),
        "S07.2",
        query=r.ResearchListQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/works",
        "createWork",
        m.Work,
        ("content.write",),
        "S07",
        request=m.WorkCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/works/{work_id}",
        "getWork",
        r.WorkDetail,
        ("content.read",),
        "S07.2",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/artifact-versions",
        "createArtifactVersion",
        m.ArtifactVersion,
        ("content.write",),
        "S07",
        request=m.ArtifactVersionCreate,
        status=201,
    ),
    Operation(
        "GET",
        "/artifact-versions/{version_id}",
        "getArtifactVersion",
        m.ArtifactVersion,
        ("content.read",),
        "S07",
    ),
    Operation(
        "POST",
        "/input-sets",
        "createInputSet",
        m.InputSet,
        ("research.submit",),
        "S07",
        request=m.InputSetCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/input-sets/{input_set_id}",
        "getInputSet",
        m.InputSet,
        ("content.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/research/submissions",
        "submitIntelligence",
        r.ImportResult,
        ("research.submit", "content.write"),
        "S06",
        request=m.IntakeCreate,
        status=202,
        implementation="implemented",
        permission_note="原Source与目标Work/业务同时授权；跨业务需显式确认；只提交不隐式授权AI执行。",
    ),
    Operation(
        "GET",
        "/research/submissions/{submission_id}",
        "getSubmission",
        m.Submission,
        ("content.read",),
        "S06",
    ),
    Operation(
        "POST",
        "/research/direct",
        "submitDirectResearch",
        r.ImportResult,
        ("research.submit", "content.write"),
        "S07.2",
        request=r.DirectIntake,
        status=202,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/works/{work_id}/materials",
        "createResearchMaterial",
        r.ImportResult,
        ("research.submit", "content.write"),
        "S07.2",
        request=r.MaterialIntake,
        status=202,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/analysis-runs",
        "startAnalysis",
        a.AnalysisAccepted,
        ("research.submit",),
        "S07",
        request=a.AnalysisRequest,
        implementation="implemented",
        status=202,
        permission_note="execute_now=true另外要求research.run和明确调用预算；服务端固定处理器、标准及模型版本，不接受客户端配置或actor。",
    ),
    Operation(
        "GET",
        "/tasks",
        "listTasks",
        m.Page[m.Task],
        ("task.read",),
        "S06",
        query=BusinessQuery,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/tasks/{task_id}",
        "getTask",
        m.Task,
        ("task.read",),
        "S05.4",
        permission_note="只返回安全状态与有权输出引用；task授权不自动授予输入/原始输出正文。",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/tasks/{task_id}/authorize",
        "authorizeTask",
        m.Task,
        (),
        "S05.4",
        request=m.TaskAuthorize,
        permission_note="按服务端固定处理器映射校验精确执行动作；首次领取后不能换执行人，加预算必须当前执行人本人确认。",
    ),
    Operation(
        "POST",
        "/tasks/{task_id}/cancel",
        "cancelTask",
        m.Task,
        ("task.manage",),
        "S05.4",
        request=m.TaskControl,
        status=202,
        permission_note="running只进入cancel_requested；外部效果未知不能假记cancelled。",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/tasks/{task_id}/retry",
        "retryTask",
        m.Task,
        ("task.manage",),
        "S05.4",
        request=m.TaskControl,
        status=202,
        permission_note="还需原处理器执行权限、当前依赖与剩余预算；EXTERNAL_RESULT_UNKNOWN禁止自动重发。",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/reports/{report_id}",
        "getReport",
        a.ReportView,
        ("content.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/evaluations/{evaluation_id}",
        "getEvaluation",
        m.Evaluation,
        ("content.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge/revisions/{revision_id}/sources",
        "getKnowledgeSources",
        k.KnowledgeSources,
        ("content.read",),
        "S07.5",
        permission_note="确切正式版本或候选权限，逐项重检原文依赖。",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge/candidates/{knowledge_id}",
        "getKnowledgeCandidate",
        k.KnowledgeView,
        ("knowledge.candidate.read",),
        "S07.4",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge/candidates",
        "listKnowledgeCandidates",
        m.Page[k.KnowledgeView],
        ("knowledge.candidate.read",),
        "S07.4",
        query=KnowledgeQuery,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/reports/{report_id}/knowledge-extractions",
        "extractKnowledge",
        a.AnalysisAccepted,
        ("knowledge.edit", "research.run"),
        "S07.4",
        request=k.ExtractCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/reviews/{request_id}/approve-publication",
        "approveKnowledgePublication",
        m.Publication,
        ("knowledge.review", "knowledge.publish"),
        "S07.4",
        request=k.ApprovePublish,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge",
        "searchKnowledge",
        m.Page[k.KnowledgeView],
        ("content.read",),
        "S07",
        query=KnowledgeQuery,
        permission_note="只搜索当前正式Publication的标题/正文/业务；先授权再计数、分页，不用候选标签扩大正式可见性。",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/knowledge",
        "createKnowledge",
        k.KnowledgeView,
        ("knowledge.edit",),
        "S07",
        request=k.KnowledgeWrite,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge/{knowledge_id}",
        "getPublishedKnowledge",
        k.KnowledgeView,
        ("content.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/knowledge/{knowledge_id}/revisions",
        "reviseKnowledge",
        m.KnowledgeRevision,
        ("knowledge.edit",),
        "S07",
        request=k.KnowledgeRevisionWrite,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/knowledge/revisions/{revision_id}",
        "getCandidateRevision",
        m.KnowledgeRevision,
        ("knowledge.candidate.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/reviews",
        "requestReview",
        k.ReviewView,
        (),
        "S07",
        request=m.ReviewCreate,
        status=201,
        permission_note="knowledge_release普通送审需knowledge.edit，execute_ai=true则需knowledge.review.run；report_review需report.review.run；evaluation_review需evaluation.review；standard_approval需standard.approve，后两类禁止额外AI调用。AI执行另查明确预算。",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/reviews/{request_id}",
        "getReview",
        k.ReviewView,
        (),
        "S07",
        permission_note="按purpose检查目标读取动作，知识候选须knowledge.candidate.read。",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/reviews/{request_id}/human-decisions",
        "submitHumanDecision",
        m.ReviewDecision,
        (),
        "S07",
        request=m.HumanDecisionCreate,
        status=201,
        permission_note="purpose固定映射knowledge.review/report.review/evaluation.review/standard.approve；知识/报告人工approved必须绑定当前approved AI。不接受AI决定、actor或输入摘要。",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/knowledge/{knowledge_id}/publications",
        "publishKnowledge",
        m.Publication,
        ("knowledge.publish",),
        "S07",
        request=m.PublishCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/prediction-drafts/{draft_id}/freeze",
        "freezePrediction",
        m.FrozenPrediction,
        ("prediction.freeze",),
        "S07",
        request=m.PredictionFreeze,
        status=201,
        permission_note="仅已有estimable草稿；数据库时间和执行身份由服务端生成，第一次提交后另事务确认再响应；未知确认失败同key只补确认。",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/predictions/{prediction_id}",
        "getPrediction",
        m.FrozenPrediction,
        ("content.read",),
        "S07",
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/works/{work_id}/analysis-history",
        "getAnalysisHistory",
        a.AnalysisHistory,
        ("content.read",),
        "S07.3",
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/prediction-drafts",
        "createPredictionDraft",
        pr.DraftView,
        ("prediction.edit",),
        "S07.3",
        request=pr.DraftCreate,
        status=201,
        implementation="implemented",
    ),
    Operation(
        "GET",
        "/prediction-drafts/{draft_id}",
        "getPredictionDraft",
        pr.DraftView,
        ("content.read",),
        "S07.3",
        implementation="implemented",
    ),
    Operation(
        "PATCH",
        "/prediction-drafts/{draft_id}",
        "updatePredictionDraft",
        pr.DraftView,
        ("prediction.edit",),
        "S07.3",
        request=pr.DraftUpdate,
        implementation="implemented",
    ),
    Operation(
        "POST",
        "/predictions/{prediction_id}/retract",
        "retractPrediction",
        m.FrozenPrediction,
        ("prediction.retract",),
        "S07.3",
        request=pr.Retraction,
        implementation="implemented",
    ),
]

cookie = APIKeyCookie(name="cip_session", scheme_name="SessionCookie", auto_error=False)
contract_app = FastAPI(
    title="内容智库首条链路契约（设计态）",
    version="0.1.0",
    description="S05.1离线设计：所有/api/v1业务操作均未实现。此app不挂入运行服务。",
)
contract_app.include_router(health_router, prefix="/api")


def failure(code="SERVICE_NOT_READY", paths=None):
    return m.ErrorEnvelope(
        request_id=uuid4(),
        error=m.ErrorInfo(
            code=code,
            message="接口尚未就绪" if code == "SERVICE_NOT_READY" else "请求参数不符合契约",
            field_paths=paths or [],
        ),
    )


def error_response(code="SERVICE_NOT_READY", paths=None, request_id=None):
    payload = failure(code, paths)
    if request_id is not None:
        payload = payload.model_copy(update={"request_id": request_id})
    return JSONResponse(
        status_code=m.ERROR_STATUS[code],
        content=payload.model_dump(mode="json"),
        headers={"X-Request-ID": str(payload.request_id), "Cache-Control": "no-store"},
    )


@contract_app.exception_handler(RequestValidationError)
async def invalid_request(request, error):
    # Never echo Pydantic input, user passwords, raw text, URLs or provider responses.
    paths = [
        ".".join(str(p) for p in (e["loc"][:-1] if e["type"] == "extra_forbidden" else e["loc"]))
        for e in error.errors()
    ][:20]
    return error_response("VALIDATION_FAILED", paths, getattr(request.state, "request_id", None))


def add_operation(spec, target_app=contract_app, handler=None, engine_dependency=None):
    if handler and inspect.iscoroutinefunction(handler):

        async def planned(**kwargs):
            return await handler(**kwargs)
    else:

        def planned(**kwargs):
            return handler(**kwargs) if handler else error_response()

    params = []
    for key in re.findall(r"{(\w+)}", spec.path):
        params.append(inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY, annotation=UUID))
    if spec.request:
        params.append(
            inspect.Parameter(
                "body", inspect.Parameter.KEYWORD_ONLY, annotation=spec.request, default=Body(...)
            )
        )
    if spec.query:
        params.append(
            inspect.Parameter(
                "filters", inspect.Parameter.KEYWORD_ONLY, annotation=Annotated[spec.query, Query()]
            )
        )
    if not spec.public:
        params.append(
            inspect.Parameter(
                "session",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=Security(cookie),
            )
        )
        if spec.method != "GET":
            params.append(
                inspect.Parameter(
                    "csrf_token",
                    inspect.Parameter.KEYWORD_ONLY,
                    annotation=str,
                    default=Header(..., alias="X-CSRF-Token", min_length=16, max_length=256),
                )
            )
            if spec.name != "logout":
                params.append(
                    inspect.Parameter(
                        "idempotency_key",
                        inspect.Parameter.KEYWORD_ONLY,
                        annotation=UUID,
                        default=Header(..., alias="Idempotency-Key"),
                    )
                )
    if handler:
        params += [
            inspect.Parameter("request", inspect.Parameter.KEYWORD_ONLY, annotation=Request),
            inspect.Parameter(
                "engine", inspect.Parameter.KEYWORD_ONLY, default=Depends(engine_dependency)
            ),
        ]
    planned.__signature__ = inspect.Signature(params)
    headers = {
        "X-Request-ID": {
            "schema": {"type": "string", "format": "uuid"},
            "description": "服务端关联ID",
        }
    }
    responses = {
        status: {"model": m.ErrorEnvelope, "description": description, "headers": headers}
        for status, description in {
            401: "未登录或登录失败",
            403: "动作或CSRF被拒绝",
            404: "不存在或对象不可访问（同一响应）",
            409: "版本、幂等、审核、预算或来源冲突",
            413: "文件或请求体过大",
            502: "外链素材获取失败",
            422: "请求不符合契约；不回显输入",
            429: "请求限流",
            500: "安全内部错误",
            503: "服务未就绪；设计预览只返回此状态或参数错误",
        }.items()
    }
    responses[spec.status] = {"headers": headers}
    extra = {}
    if spec.binary:
        extra["requestBody"] = {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    if spec.download:
        responses[spec.status]["content"] = {
            "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
        }
    target_app.add_api_route(
        "/api/v1" + spec.path,
        planned,
        methods=[spec.method],
        operation_id=spec.name,
        response_model=None if spec.download else m.Envelope[spec.response],
        response_class=Response if spec.download else JSONResponse,
        status_code=spec.status,
        tags=[spec.path.split("/")[1]],
        responses=responses,
        summary=spec.name,
        description=spec.permission_note,
        openapi_extra={
            **extra,
            "x-implementation-status": spec.implementation,
            "x-implementation-stage": spec.stage,
            "x-required-actions": list(spec.actions),
            "x-permission-rule": spec.permission_note,
            "x-idempotency": spec.method != "GET" and not spec.public and spec.name != "logout",
        },
    )


for operation in OPERATIONS:
    add_operation(operation)
