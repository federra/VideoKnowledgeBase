"""Four fixed channel adapters; no arbitrary URLs, source expansion, retries or AI calls."""

from app.intelligence.refresh_worker import ChildJobs
from app.tasks.service import TaskError

MESSAGES = {
    "RATE_LIMITED": "来源限频或冷却中；未追加请求，旧数据保留",
    "ACCESS_REVOKED": "执行权限已变化；采集停止，旧数据保留",
    "DATE_WINDOW_MISMATCH": "已跨上海日期；采集停止，旧数据保留",
    "SOURCE_UNAVAILABLE": "来源受限或配置不可用；未重试，旧数据保留",
    "SOURCE_VERIFICATION_REQUIRED": "抖音要求人工验证：请在独立采集浏览器中完成验证码；采集已停止，不自动重试，旧数据保留",
    "INVALID_RESPONSE": "来源格式校验失败；原包保留，旧数据保留",
    "EXTERNAL_RESULT_UNKNOWN": "外部请求结果不确定；未重试，旧数据保留",
}


class Channels(ChildJobs):
    def __init__(self, *args):
        super().__init__(*args)
        self.specs = self.ticket.payload["specs"]
        self.completed = 0
        self.total = 0
        self.current = ""

    def one(self, spec, handler, kind, **kwargs):
        self.checkpoint()
        raw, saved = self.run_job(self.current, spec, handler, kind, **kwargs)
        self.completed += 1
        self.progress(self.current, "running", self.completed, self.total, "正在采集；旧快照暂保留")
        return raw, saved

    def run(self, channel):
        self.current, self.completed, self.total = channel, 0, 0
        try:
            state, message = getattr(self, channel)()
            if state in ("succeeded", "partial"):
                self.publish_channel(channel)
        except TaskError as exc:
            if exc.code in ("ACCESS_REVOKED", "DATE_WINDOW_MISMATCH"):
                raise
            state, message = "failed", MESSAGES.get(exc.code, "采集未完成；未重试，旧数据保留")
        except Exception:  # noqa: BLE001 - never expose source text, URLs or credentials
            state, message = "failed", "采集未完成；未重试，旧数据保留"
        if state == "failed" and getattr(self, "last_http_status", None):
            message += f"（HTTP {self.last_http_status}）"
        self.progress(channel, state, self.completed, self.total, message)
        return state

    def configured(self, cap):
        return [s for s in self.specs if s["capability_code"] == cap]

    def begin(self, total):
        self.total = total
        self.progress(self.current, "running", 0, total, "正在采集")

    def hongguo(self):
        from app.collection.hongguo import CaptureHongguo
        from app.connectors.hongguo import BOARDS, Hongguo

        specs = self.configured("hongguo.board")
        if not specs:
            return "unavailable", "当前业务线未配置红果来源"
        by_board = {s["safe_request"]["board"]: s for s in specs}
        if set(by_board) != set(BOARDS):
            return "unavailable", "红果四榜配置不完整，未开始请求"
        self.begin(4)
        handler = CaptureHongguo(Hongguo())
        snapshots = []
        for board in BOARDS:
            _, job = self.one(by_board[board], handler, "collect.hongguo")
            with self.runner.engine.connect() as c:
                snapshots.append(
                    c.exec_driver_sql(
                        "SELECT id FROM intelligence_snapshots WHERE org_id=%s AND job_id=%s AND sealed_at IS NOT NULL",
                        (self.p.org_id, job["job_id"]),
                    ).scalar_one()
                )
        with self.runner.engine.connect() as c:
            members = (
                c.exec_driver_sql(
                    "SELECT DISTINCT ON(o.content_id) o.content_id,x.platform_content_id,s.id snapshot_id FROM intelligence_snapshots s JOIN snapshot_entries e ON e.org_id=s.org_id AND e.snapshot_id=s.id JOIN content_observations o ON o.org_id=e.org_id AND o.id=e.content_observation_id JOIN external_contents x ON x.org_id=o.org_id AND x.id=o.content_id WHERE s.org_id=%s AND s.id=ANY(%s) ORDER BY o.content_id,s.created_at DESC",
                    (self.p.org_id, snapshots),
                )
                .mappings()
                .all()
            )
        if len(members) > 80:
            raise TaskError("INVALID_RESPONSE")
        self.total = 4 + len(members)
        for item in members:
            spec = {
                **by_board["hot-drama"],
                "source_id": None,
                "capability_code": "hongguo.comments",
                "max_items": 15,
            }
            self.one(
                spec,
                handler,
                "collect.hongguo",
                request={"series_id": item["platform_content_id"]},
                content_id=item["content_id"],
                snapshot_id=item["snapshot_id"],
            )
        return "succeeded", f"四榜已更新，每榜最多20部；已采集{len(members)}部评论，每部最多15条"

    def tikhub(self):
        from app.collection.series import CaptureSeries, NormalizeSeries, submit_normalization
        from app.connectors.tikhub_series import VERSION, Series
        from app.core.config import settings
        from app.security.sessions import refresh
        from app.tasks.service import Runner

        specs = self.configured("douyin.series.hot")
        if not specs:
            return "unavailable", "当前业务线未配置TikHub来源"
        self.begin(1)
        handler = CaptureSeries(
            Series(
                lambda: (
                    settings.tikhub_api_key.get_secret_value() if settings.tikhub_api_key else None
                )
            )
        )
        raw, _ = self.one(specs[0], handler, "collect.tikhub-series")
        self.checkpoint()
        # Normalization reads the just-captured raw response and makes zero external calls.
        with self.runner.engine.begin() as c:
            refresh(c, self.p)
            tid = submit_normalization(c, self.p, raw["id"])
        worker = Runner(self.runner.engine, {("series.normalize", VERSION): NormalizeSeries()})
        if worker.run(self.p.org_id, tid) != "succeeded":
            raise TaskError("INVALID_RESPONSE")
        return "succeeded", "已更新短剧热榜，最多10条；本批仅一次供应商请求"

    def fanqie(self):
        from app.collection.font_verification import verify_font
        from app.collection.novels import NovelCollect
        from app.connectors.fontcodec import spec as font_spec
        from app.connectors.novels import PublicNovels, catalog
        from app.core.config import settings

        specs = self.configured("novel.fanqie.board")
        catalogs = self.configured("novel.fanqie.catalog")
        if not specs or not catalogs:
            return "unavailable", "当前业务线未配置完整番茄来源"
        by_code = {s["safe_request"]["code"]: s for s in specs}
        self.begin(1 + len(by_code))
        handler = NovelCollect(PublicNovels())
        raw, _ = self.one(catalogs[0], handler, "collect.novels")
        boards = catalog(raw["body_text"])
        if len(boards) > 74 or not boards:
            raise TaskError("INVALID_RESPONSE")
        directory = settings.storage_root / "novels/fonts"
        directory.mkdir(parents=True, exist_ok=True)
        reads = (
            self.reuse_verified_font()
            if getattr(self, "resume_batch", None)
            else verify_font(raw["body_text"], directory, checkpoint=self.checkpoint)
        )
        from uuid import uuid4

        from app.core.models import metadata

        with self.runner.engine.begin() as c:
            c.execute(
                metadata.tables["audit_events"]
                .insert()
                .values(
                    id=uuid4(),
                    org_id=self.p.org_id,
                    actor_member_id=self.p.member_id,
                    action_code="intelligence.refresh.font_verified",
                    target_kind="task",
                    target_id=self.ticket.task,
                    request_id=str(uuid4()),
                    safe_details={
                        "metadata_reads": reads,
                        "font_sha256": font_spec()["font_sha256"],
                    },
                )
            )
        matched = [b for b in boards if b["code"] in by_code]
        if len(matched) != len(by_code):
            raise TaskError("SOURCE_UNAVAILABLE")
        for board in matched:
            self.wait(2.1)
            board["font_sha256"] = font_spec()["font_sha256"]
            self.one(by_code[board["code"]], handler, "collect.novels", request=board)
        return "succeeded", f"已更新{len(matched)}个已配置子榜，每榜最多30条"

    def qidian(self):
        from app.collection.qidian_mobile import QidianCollect
        from app.connectors.qidian_mobile import METHOD, QidianMobile

        specs = self.configured("novel.qidian.board")
        mobile = [
            s
            for s in specs
            if s["safe_request"].get("method") == METHOD
            and s["safe_request"].get("gender") == "male"
        ]
        if not mobile:
            return "unavailable", "起点自动采集配置不可用；女频需Chrome辅助，旧数据保留"
        if len(mobile) > 20:
            raise TaskError("INVALID_INPUT")
        self.begin(len(mobile))
        handler = QidianCollect(QidianMobile())
        for index, spec in enumerate(mobile):
            if index:
                self.wait(2.1)
            self.one(spec, handler, "collect.novels")
        return "partial", f"男频{len(mobile)}榜已更新；女频仍需Chrome辅助采集，保留当日原数据"

    def qimao(self):
        from app.collection.qimao import QimaoCollect
        from app.connectors.qimao import CAPABILITY, Qimao, boards

        specs = self.configured(CAPABILITY)
        if {s["safe_request"]["code"] for s in specs} != {b["code"] for b in boards()} or len(specs) != 10:
            return "unavailable", "七猫10个榜单配置不完整，未开始请求"
        self.begin(10)
        handler = QimaoCollect(Qimao())
        for spec in specs:
            # Public novel sources share one connection fence; respect the preceding platform too.
            self.wait(10)
            self.one(spec, handler, "collect.novels")
        return "succeeded", "七猫男女频10榜已更新，每榜≤20条；热度缺失保留空值，各子榜保留官方顺序"

    def creators(self):
        from app.intelligence.creator_collection import collect_creators

        return collect_creators(self)


    def microfilm(self):
        from app.collection.microfilm import Microfilm, run
        from app.connectors.douyin_search import CAPABILITY
        from app.intelligence.refresh_worker import child_key
        specs = self.configured(CAPABILITY)
        if not specs:
            return "unavailable", "当前业务线未配置微电影综合搜索榜"
        self.begin(1)
        result = run(self.runner.engine, self.p,
                     key=child_key(getattr(self, "resume_batch", self.ticket.task), "microfilm", CAPABILITY, {"keyword":"微电影"}),
                     handler=Microfilm(parent_checkpoint=self.checkpoint))
        if result["state"] != "succeeded":
            if result.get("error") == "SOURCE_VERIFICATION_REQUIRED":
                return "failed", MESSAGES["SOURCE_VERIFICATION_REQUIRED"]
            return "failed", "微电影接口未完成；已保存原包，旧数据保留；未自动追加补试"
        self.completed = 1
        if result.get("verification_required"):
            return "partial", "已保存本次已采集部分；" + MESSAGES["SOURCE_VERIFICATION_REQUIRED"]
        return ("partial" if result["outcome"] == "insufficient_evidence" else "succeeded",
                "已保存微电影综合顺序视频与可用评论；最多50条，每条≤15评论，缺项保留缺失状态")
