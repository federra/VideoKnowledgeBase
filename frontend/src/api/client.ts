/** Same-origin transport; only explicit runtime services below may mutate business state. */
import type { components, operations } from './generated/runtime';
export type KnowledgeItem = components['schemas']['KnowledgeView'];
export type KnowledgeInput = components['schemas']['KnowledgeWrite'];
export type KnowledgeRevisionInput = components['schemas']['KnowledgeRevisionWrite'];
export type KnowledgeSources = components['schemas']['KnowledgeSources'];
export type KnowledgeReview = components['schemas']['ReviewView'];
type KnowledgeApproval = components['schemas']['ApprovePublish'];
const parseKnowledge: Decoder<KnowledgeItem> = value => {
 if(!record(value)||!id(value.id)||!version(value.lock_version)||typeof value.title!=='string'||!id(value.revision_id)||!strings(value.business_codes)||!Array.isArray(value.tags)||!record(value.revision)||value.revision.id!==value.revision_id||typeof value.revision.body_text!=='string'||!Array.isArray(value.revision.evidence_ids)||!Array.isArray(value.revision.business_codes)||!['draft','pending_ai','ai_error','needs_changes','pending_human','ready_to_publish','published'].includes(String(value.state))||!(value.review_request_id===null||id(value.review_request_id)))throw new Error('shape');return value as KnowledgeItem;
};
const parseKnowledgeReview: Decoder<KnowledgeReview> = value => {
 if(!record(value)||!id(value.id)||!id(value.target_id)||!Array.isArray(value.decisions)||!value.decisions.every(d=>record(d)&&id(d.id)&&['ai','human'].includes(String(d.reviewer_kind))&&['approved','rejected','needs_changes','error'].includes(String(d.verdict))&&typeof d.reason==='string')||!['ai_head_id','human_head_id'].every(k=>value[k]===null||id(value[k]))||!['ai_head_lock_version','human_head_lock_version'].every(k=>value[k]===null||version(value[k])))throw new Error('shape');return value as KnowledgeReview;
};
export type Session = components['schemas']['Session'];
export type FileInfo = components['schemas']['FileInfo'];
type Login = operations['login']['requestBody']['content']['application/json'];
type UploadMetadata = operations['uploadFile']['parameters']['query'];
type ImportMetadata = operations['importFile']['requestBody']['content']['application/json'];
type DownloadParent = operations['downloadFile']['parameters']['query'];
type Decoder<T> = (value: unknown) => T;
type ClientOptions = {
    fetcher?: typeof fetch;
    timeoutMs?: number;
    onBoundary?: () => void;
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const version = (v: unknown) => typeof v === 'string' && /^[1-9][0-9]{0,18}$/.test(v) && BigInt(v) <= 9223372036854775807n;
const count = (v: unknown) => v === '0' || version(v);
const id = (v: unknown): v is string => typeof v === 'string' && uuid.test(v);
const hasControls = (v: string) => [...v].some(c => c.charCodeAt(0) <= 32 || c.charCodeAt(0) === 127);
const timestamp = (v: unknown) => typeof v === 'string' && /^\d{4}-\d\d-\d\dT.*Z$/.test(v) && Number.isFinite(Date.parse(v));
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(x => typeof x === 'string');
const parseSession: Decoder<Session> = value => {
    if (!record(value) || !id(value.org_id) || !id(value.member_id) || !version(value.authz_version)
        || typeof value.display_name !== 'string' || !strings(value.actions) || !timestamp(value.expires_at)
        || typeof value.csrf_token !== 'string' || !/^[a-f0-9]{64}$/.test(value.csrf_token))
        throw new Error('shape');
    return value as Session;
};
const parseFile: Decoder<FileInfo> = value => {
    if (!record(value) || !id(value.id) || !count(value.byte_size) || !timestamp(value.created_at)
        || typeof value.original_name !== 'string' || typeof value.media_type !== 'string'
        || value.validation_state !== 'accepted' || typeof value.sha256 !== 'string' || !/^[a-f0-9]{64}$/.test(value.sha256))
        throw new Error('shape');
    return value as FileInfo;
};
type ServerCode = components['schemas']['ErrorInfo']['code'];
type LocalCode = 'AUTH_CHANGE_IN_PROGRESS' | 'INVALID_RESPONSE' | 'INVALID_REQUEST' | 'REQUEST_CANCELLED' | 'TIMEOUT' | 'NETWORK_ERROR';
const messages: Record<ServerCode | LocalCode, string> = {
    AUTH_REQUIRED: '当前工作区身份已失效，请重试', AUTH_INVALID: '登录信息无效，请重新核对',
    ACCESS_DENIED: '无权执行此操作', CSRF_INVALID: '会话校验失败，请刷新会话后重试',
    NOT_FOUND: '内容不存在或无权访问', VERSION_CONFLICT: '内容版本已更新，请重新读取后操作',
    IDEMPOTENCY_CONFLICT: '此提交标识已用于不同内容，请核对原请求',
    VALIDATION_FAILED: '提交内容不符合要求，请检查字段', RATE_LIMITED: '请求过于频繁，请稍后再试',
    SERVICE_NOT_READY: '服务尚未就绪，请稍后再试', INTERNAL_ERROR: '服务处理失败，请保留请求编号以便排查',
    FILE_TOO_LARGE: '文件超过大小限制', INVALID_FILE: '文件格式或内容校验未通过',
    UNSAFE_URL: '素材地址未获准访问', FETCH_FAILED: '素材获取失败',
    EXTERNAL_RESULT_UNKNOWN: '外部调用结果未知，请先核验，不要重复提交',
    BUDGET_EXHAUSTED: '调用预算已用尽', FILE_NOT_ACCEPTED: '文件尚未通过校验',
    AUTH_CHANGE_IN_PROGRESS: '正在切换会话，请等待当前操作完成',
    REVIEW_STALE: '审核依据已更新，请重新读取', CURSOR_EXPIRED: '查询条件或权限已变化，请从第一页重新查询',
    IMMUTABLE_INPUT: '已封存的输入不可修改', STALE_RESULT: '任务结果已失效，请重新读取状态',
    CANCEL_UNCONFIRMED: '任务停止尚未确认，请先核验', STANDARD_NOT_APPROVED: '标准尚未批准',
    MODEL_NOT_CONFIGURED: '模型尚未配置', INSUFFICIENT_MATERIAL: '资料不足，请补充材料',
    DATE_WINDOW_MISMATCH: '资料日期与查询窗口不一致', SOURCE_UNAVAILABLE: '来源暂不可用',
    UNSUPPORTED_SOURCE: '暂不支持此来源', PROVENANCE_DEPTH_EXCEEDED: '来源依赖校验未通过',
    INVALID_RESPONSE: '服务响应格式异常，请稍后重试', INVALID_REQUEST: '请求参数或地址无效',
    REQUEST_CANCELLED: '请求已取消', TIMEOUT: '请求超时', NETWORK_ERROR: '网络连接失败',
};
export type ConsoleSource = components['schemas']['ConsoleSource'];
export type ConsoleTask = components['schemas']['Task'];
export type ConsoleCreate = components['schemas']['ConsoleSourceCreate'];
export type SourcePatch = components['schemas']['SourcePatch'];
export type ConsolePageData<T> = { items: T[]; next_cursor: string | null; total: string | null };
const states = ['queued','running','succeeded','failed','cancel_requested','cancelled'];
function entity(value: unknown): value is Record<string, unknown> {
    return record(value) && id(value.id) && version(value.lock_version) && timestamp(value.created_at) && timestamp(value.updated_at);
}
const parseSource: Decoder<ConsoleSource> = value => {
    if (!entity(value) || typeof value.archived !== 'boolean' || typeof value.name !== 'string' || !['motion_comic','story_short','ecommerce_video'].includes(String(value.business_code))
        || !['douyin','fanqie','qidian','hongguo'].includes(String(value.platform_code)) || typeof value.enabled !== 'boolean' || !record(value.target)
        || !['keyword','account','content','board'].includes(String(value.target.kind))
        || !(value.last_state === null || states.includes(String(value.last_state))) || !(value.last_at === null || timestamp(value.last_at))) throw new Error('shape');
    const target=value.target;
    if (target.kind==='keyword' && typeof target.keyword!=='string' || target.kind==='account' && !id(target.account_id)) throw new Error('shape');
    const plan=value.plan;
    if (plan!==null && (!record(plan) || !id(plan.id) || !id(plan.connection_id) || !version(plan.lock_version) || !timestamp(plan.created_at)
        || typeof plan.enabled!=='boolean' || !['daily_0900','every_2h','every_4h'].includes(String(plan.frequency))
        || !['intelligence','knowledge','both'].includes(String(plan.purpose)) || plan.max_requests!==1 || !Number.isInteger(plan.max_items) || Number(plan.max_items)<1 || Number(plan.max_items)>3)) throw new Error('shape');
    return value as ConsoleSource;
};
const parseTask: Decoder<ConsoleTask> = value => {
    if (!entity(value) || typeof value.kind!=='string' || !states.includes(String(value.state)) || !Array.isArray(value.outputs)
        || !value.outputs.every(o=>record(o)&&id(o.id)&&typeof o.kind==='string') || !(value.safe_error_code===null||typeof value.safe_error_code==='string')
        || !timestamp(value.available_at) || !(value.started_at===null||timestamp(value.started_at)) || !(value.finished_at===null||timestamp(value.finished_at))
        || !Number.isInteger(value.max_attempts) || Number(value.max_attempts)<1 || !Number.isInteger(value.max_external_calls) || Number(value.max_external_calls)<0) throw new Error('shape');
    return value as ConsoleTask;
};
function parsePage<T>(decode: Decoder<T>): Decoder<ConsolePageData<T>> {
    return value=>{
        if (!record(value) || !Array.isArray(value.items) || !(value.next_cursor===null||typeof value.next_cursor==='string') || !(value.total===null||count(value.total))) throw new Error('shape');
        return {items:value.items.map(decode),next_cursor:value.next_cursor,total:value.total as string|null};
    };
}
export type IntelligenceFeed = components['schemas']['IntelligenceFeed'];
export type FeedItem = components['schemas']['FeedItem'];
const parseFeed: Decoder<IntelligenceFeed> = value => {
    if (!record(value) || !['motion_comic','story_short','ecommerce_video'].includes(String(value.business_code))
        || typeof value.business_date!=='string' || !/^\d{4}-\d\d-\d\d$/.test(value.business_date) || typeof value.has_snapshot!=='boolean'
        || !record(value.metrics) || !['videos','creators','comments','likes'].every(k=>value.metrics && record(value.metrics) && (value.metrics[k]===null || count(value.metrics[k])))
        || !Number.isInteger(value.page) || Number(value.page)<1 || value.page_size!==10 || !count(value.total)
        || !(value.keyword_works_count===undefined || count(value.keyword_works_count))
        || !(value.keyword_ranking_status===undefined || ['not_acquired','no_content_matches','insufficient_metrics','ready','default_order','provider_order','series_order'].includes(String(value.keyword_ranking_status)))
        || !(value.video_latest_dates===undefined||record(value.video_latest_dates)&&Object.entries(value.video_latest_dates).every(([k,v])=>['hongguo','tikhub'].includes(k)&&typeof v==='string'&&/^\d{4}-\d\d-\d\d$/.test(v)))
        || !(value.video_subgenres===undefined||Array.isArray(value.video_subgenres)&&value.video_subgenres.every(x=>typeof x==='string'&&x.trim()))
        || !(value.video_genres===undefined||Array.isArray(value.video_genres)&&value.video_genres.every(x=>typeof x==='string'&&x.trim()))
        || !Array.isArray(value.items) || value.items.length>10
        || !['boards','creators'].every(k=>Array.isArray(value[k]) && (value[k] as unknown[]).every(o=>record(o)&&id(o.id)&&typeof o.name==='string'))) throw new Error('shape');
    const report=value.insight;
    if(report!==null && (!record(report)||!id(report.id)||!timestamp(report.created_at)||!id(report.feedback_id)
        ||report.business_code!==value.business_code||report.business_date!==value.business_date||!Number.isInteger(report.version_no)||Number(report.version_no)<1
        ||!Number.isInteger(report.sample_count)||Number(report.sample_count)<1||!Number.isInteger(report.classified_count)||Number(report.classified_count)<0||Number(report.classified_count)>Number(report.sample_count)
        ||!Array.isArray(report.emotions)||!report.emotions.every(e=>record(e)&&typeof e.name==='string'&&e.name.trim()&&Number.isInteger(e.count)&&Number(e.count)>0&&Number(e.count)<=Number(report.classified_count)&&Number.isInteger(e.percent)&&Number(e.percent)>=0&&Number(e.percent)<=100)
        ||!['motif','genre'].every(k=>report[k]===null||typeof report[k]==='string')||!Array.isArray(report.suggestions)||!report.suggestions.every(x=>typeof x==='string'&&x.trim())||typeof report.coverage_note!=='string')) throw new Error('shape');
    for(const item of value.items){
        if(!record(item)||!['heat_display','score_display'].every(k=>item[k]===undefined||item[k]===null||typeof item[k]==='string'&&item[k].trim())||!(item.genre_tags===undefined||Array.isArray(item.genre_tags)&&item.genre_tags.every(x=>typeof x==='string'&&x.trim()))||!(item.feedback_emotions===undefined||Array.isArray(item.feedback_emotions)&&item.feedback_emotions.length<=2&&item.feedback_emotions.every(x=>typeof x==='string'&&x.trim()))||!id(item.source_id)||typeof item.source_name!=='string'||!Number.isInteger(item.snapshot_version)||Number(item.snapshot_version)<1
            ||!(item.account_id===null||id(item.account_id))||!(item.author===null||typeof item.author==='string')||!record(item.entry)||!id(item.entry.id)||!timestamp(item.entry.created_at))throw new Error('shape');
        if(!(item.heat_value===undefined||item.heat_value===null||count(item.heat_value))||!(item.comment_sample_count===undefined||item.comment_sample_count===null||Number.isInteger(item.comment_sample_count)&&Number(item.comment_sample_count)>=0&&Number(item.comment_sample_count)<=15))throw new Error('shape');
        const entry=item.entry, o=entry.observation;
        if(!id(entry.snapshot_id)||!Number.isInteger(entry.position)||Number(entry.position)<0||!(entry.provider_rank===null||Number.isInteger(entry.provider_rank)&&Number(entry.provider_rank)>0)
            ||!(entry.feedback_id===null||id(entry.feedback_id))||!record(o)||!id(o.id)||!['content','account'].includes(String(o.kind))||!['douyin','fanqie','qidian','hongguo'].includes(String(o.platform_code))
            ||typeof o.platform_id!=='string'||!timestamp(o.observed_at)||!(o.published_at===null||timestamp(o.published_at))
            ||!['description','display_name','original_url','published_at_raw'].every(k=>o[k]===null||typeof o[k]==='string')
            ||!['follower_count','work_count','like_count','comment_count','share_count','collect_count','repost_count','view_count'].every(k=>o[k]===null||count(o[k]))) throw new Error('shape');
    }
    return value as IntelligenceFeed;
};
export type NovelFeed = components['schemas']['NovelFeed'];
export type NovelItem = components['schemas']['NovelItem'];
const parseNovels: Decoder<NovelFeed> = value => {
 if(!record(value)||!['motion_comic','story_short','ecommerce_video'].includes(String(value.business_code))||typeof value.business_date!=='string'||!/^\d{4}-\d\d-\d\d$/.test(value.business_date)||!(value.novel_count===null||count(value.novel_count))||!Number.isInteger(value.page)||Number(value.page)<1||value.page_size!==10||!count(value.total)||!Array.isArray(value.items)||value.items.length>10
 ||!['rank_types','genders','genres'].every(k=>Array.isArray(value[k])&&(value[k] as unknown[]).every(o=>record(o)&&typeof o.value==='string'&&typeof o.label==='string'&&(o.disabled===undefined||typeof o.disabled==='boolean')&&(o.reason===undefined||o.reason===null||typeof o.reason==='string')))
 ||!Array.isArray(value.statuses)||!value.statuses.every(s=>record(s)&&['fanqie','qidian'].includes(String(s.platform))&&typeof s.board==='string'&&states.includes(String(s.state))&&(s.http_status===null||Number.isInteger(s.http_status))))throw new Error('shape');
 for(const n of value.items){
  if(!record(n)||!(n.work_gender===null||n.work_gender==='male'||n.work_gender==='female')||!(n.work_genre===null||typeof n.work_genre==='string'&&(value.genres as {value:string}[]).some(g=>g.value===n.work_genre))||!(n.reader_count===null||count(n.reader_count))||!Number.isInteger(n.rank)||Number(n.rank)<1||!record(n.board)||!['fanqie','qidian'].includes(String(n.board.platform))||!['code','rank_type','gender','category_id','category_name'].every(k=>typeof n.board==='object'&&n.board!==null&&typeof (n.board as Record<string,unknown>)[k]==='string'))throw new Error('shape');
 }
 parseFeed({...value,has_snapshot:true,metrics:{videos:null,creators:null,comments:null,likes:null},boards:[],creators:[],insight:null,items:value.items.map(n=>(n as Record<string,unknown>).item)});
 return value as NovelFeed;
};
export type EntryFeedback = components['schemas']['EntryFeedback'];
const parseEntryFeedback: Decoder<EntryFeedback> = value => {
    if(!record(value)||!id(value.entry_id)||!id(value.snapshot_id)||!Number.isInteger(value.snapshot_version)||Number(value.snapshot_version)<1
        ||!['motion_comic','story_short','ecommerce_video'].includes(String(value.business_code))||typeof value.business_date!=='string'||!/^\d{4}-\d\d-\d\d$/.test(value.business_date)
        ||typeof value.platform_code!=='string'||!['not_acquired','sampled','ready'].includes(String(value.status))
        ||!(value.feedback_id===null||id(value.feedback_id))||!(value.feedback_version===null||Number.isInteger(value.feedback_version)&&Number(value.feedback_version)>0)
        ||!['sampling_description','coverage_note'].every(k=>value[k]===null||typeof value[k]==='string')
        ||!['sample_count','classified_count'].every(k=>value[k]===null||Number.isInteger(value[k])&&Number(value[k])>=0)
        ||!Array.isArray(value.comments)||!Array.isArray(value.claims)) throw new Error('shape');
    const ids=new Set<string>();
    for(const c of value.comments){
        if(!record(c)||!id(c.id)||ids.has(String(c.id))||!id(c.content_id)||!timestamp(c.created_at)||!timestamp(c.captured_at)
            ||typeof c.body_text!=='string'||!c.body_text.trim()||!(c.like_count===null||count(c.like_count))
            ||!['username','posted_at_raw','platform_comment_id'].every(k=>c[k]===null||typeof c[k]==='string')||!(c.posted_at===null||timestamp(c.posted_at)))throw new Error('shape');
        ids.add(String(c.id));
    }
    const classified=new Set<string>(),claimIds=new Set<string>();
    for(const c of value.claims){
        if(!record(c)||!id(c.id)||claimIds.has(String(c.id))||!['emotion','finding','expectation','suggestion'].includes(String(c.kind))||typeof c.text!=='string'||!c.text.trim()
            ||!record(c.details)||!Array.isArray(c.comment_ids)||!c.comment_ids.length||new Set(c.comment_ids).size!==c.comment_ids.length||!c.comment_ids.every(i=>typeof i==='string'&&ids.has(i))
            ||c.support_count!==c.comment_ids.length)throw new Error('shape');
        claimIds.add(String(c.id));if(c.kind==='emotion')c.comment_ids.forEach(i=>classified.add(String(i)));
    }
    if(value.status==='ready'&&(!id(value.feedback_id)||value.feedback_version===null||!value.sampling_description||typeof value.coverage_note!=='string'||!ids.size||value.sample_count!==ids.size||value.classified_count!==classified.size))throw new Error('shape');
    if(value.status==='not_acquired'&&(ids.size||value.claims.length||value.sample_count!==null||value.classified_count!==null||value.feedback_id!==null||value.feedback_version!==null))throw new Error('shape');
    if(value.status==='sampled'&&(value.feedback_id!==null||value.feedback_version!==null||value.claims.length||value.classified_count!==0||value.sample_count!==ids.size||ids.size>15||typeof value.coverage_note!=='string'||!value.sampling_description))throw new Error('shape');
    return value as EntryFeedback;
};
export type ResearchHistory = components['schemas']['AnalysisHistory'];
export type ResearchWork = components['schemas']['WorkDetail'];
export type ResearchList = components['schemas']['WorkPage'];
export type ResearchMaterial = components['schemas']['MaterialIntake'];
export type DirectResearch = components['schemas']['DirectIntake'];
export type IntelligenceResearch = components['schemas']['IntakeCreate'];
export type ResearchImport = components['schemas']['ImportResult'];
const parseResearchImport:Decoder<ResearchImport>=v=>{if(!record(v)||!['work_id','artifact_id','artifact_version_id','task_id','submission_id'].every(k=>id(v[k]))||typeof v.reused!=='boolean')throw new Error('shape');return v as ResearchImport;};
const workShape=(v:unknown)=>record(v)&&id(v.id)&&version(v.lock_version)&&typeof v.name==='string'&&strings(v.genre_tags)&&['motion_comic','story_short','ecommerce_video'].includes(String(v.business_code))&&['collected_units','analyzed_units','material_count','processing_count','attention_count'].every(k=>typeof v[k]==='number'&&Number.isSafeInteger(v[k])&&(v[k] as number)>=0);
const parseResearchList:Decoder<ResearchList>=v=>{if(!record(v)||!Array.isArray(v.items)||!v.items.every(workShape)||!strings(v.genres)||!record(v.counts)||!['total','page','pages'].every(k=>typeof v[k]==='number'&&Number.isSafeInteger(v[k])))throw new Error('shape');return v as ResearchList;};
const parseResearchWork:Decoder<ResearchWork>=v=>{if(!workShape(v)||!record(v)||!Array.isArray(v.units)||!Array.isArray(v.materials))throw new Error('shape');for(const m of v.materials){if(!record(m)||!id(m.id)||!id(m.current_version_id)||!version(m.lock_version)||!Array.isArray(m.versions))throw new Error('shape');for(const x of m.versions){if(!record(x)||!id(x.id)||typeof x.version_no!=='number'||(x.body_text!==null&&typeof x.body_text!=='string'))throw new Error('shape');}}return v as ResearchWork;};
export class ApiError extends Error {
    constructor(public readonly status: number, public readonly code: string, public readonly requestId?: string, public readonly fieldPaths: readonly string[] = [], write = false) {
        super((messages[code as keyof typeof messages] ?? `请求未完成（${status || '连接异常'}）`)
            + (write && (status >= 500 || ['TIMEOUT', 'NETWORK_ERROR', 'INVALID_RESPONSE', 'REQUEST_CANCELLED'].includes(code)) ? '；提交结果需核验，请保留原提交标识，不要重复新建请求' : ''));
        this.name = 'ApiError';
    }
}
/** Credentials and CSRF never enter localStorage, URL parameters or query mutation caches. */
export class ApiClient {
    private readonly fetcher: typeof fetch;
    private readonly timeoutMs: number;
    private readonly listeners = new Set<() => void>();
    private readonly boundaries = new Set<() => void>();
    private csrf?: string;
    private principal?: string;
    private epoch = 0;
    private readonly cacheId = crypto.randomUUID();
    private boundaryError?: ApiError;
    private blocked = false;
    private authChanging = false;
    constructor(options: ClientOptions = {}) {
        this.fetcher = options.fetcher ?? ((input, init) => fetch(input, init));
        this.timeoutMs = options.timeoutMs ?? 30000;
        if (!Number.isFinite(this.timeoutMs) || this.timeoutMs < 1 || this.timeoutMs > 120000)
            throw new Error('Invalid request timeout');
        if (options.onBoundary)
            this.boundaries.add(options.onBoundary);
    }
    subscribe = (fn: () => void) => { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; };
    snapshot = () => `${this.cacheId}:${this.principal ?? 'unknown'}:${this.epoch}`;
    onBoundary(fn: () => void) { this.boundaries.add(fn); return () => { this.boundaries.delete(fn); }; }
    get accessError() { return this.boundaryError; }
    get accessBlocked() { return this.blocked; }
    private boundary(error?: ApiError, clearCredentials = false) {
        if (clearCredentials) {
            this.csrf = undefined;
            this.principal = undefined;
        }
        this.blocked = true;
        this.boundaryError = error;
        this.epoch++;
        for (const fn of this.boundaries)
            fn();
        for (const fn of this.listeners)
            fn();
    }
    private accept(session: Session) {
        const principal = `${session.org_id}:${session.member_id}:${session.authz_version}`;
        if (principal !== this.principal || this.blocked)
            this.boundary(undefined, true);
        this.principal = principal;
        this.csrf = session.csrf_token;
        this.blocked = false;
        this.boundaryError = undefined;
        for (const fn of this.listeners)
            fn();
        return session;
    }
    private path(path: string) {
        let decoded: string;
        try {
            decoded = decodeURIComponent(path.split('?')[0]);
        }
        catch {
            throw new ApiError(0, 'INVALID_REQUEST');
        }
        if (!decoded.startsWith('/api/') || /[\\#]/.test(path) || hasControls(path)
            || /[\\?#%]/.test(decoded) || hasControls(decoded) || decoded.includes('//')
            || decoded.split('/').some(p => p === '.' || p === '..'))
            throw new ApiError(0, 'INVALID_REQUEST');
        return path;
    }
    private async transport(path: string, options: RequestInit, decode: Decoder<unknown> | 'binary' | 'raw', signal?: AbortSignal): Promise<unknown> {
        this.path(path);
        const captured = this.epoch;
        const write = options.method !== undefined && options.method !== 'GET';
        const controller = new AbortController();
        let timedOut = false;
        const cancel = () => controller.abort();
        if (signal?.aborted)
            throw new ApiError(0, 'REQUEST_CANCELLED');
        signal?.addEventListener('abort', cancel, { once: true });
        const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, this.timeoutMs);
        try {
            const response = await this.fetcher(path, { ...options, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal });
            if (controller.signal.aborted || captured !== this.epoch)
                throw new ApiError(0, timedOut ? 'TIMEOUT' : 'REQUEST_CANCELLED', undefined, [], write);
            const headerId = response.headers.get('X-Request-ID');
            const requestId = headerId && id(headerId) ? headerId : undefined;
            const jsonType = response.headers.get('Content-Type')?.split(';')[0].trim() === 'application/json';
            if (!response.ok) {
                let payload: unknown;
                if (jsonType) {
                    try {
                        payload = await response.json();
                    }
                    catch { /* Error body is not user-facing. */ }
                }
                if (captured !== this.epoch || controller.signal.aborted)
                    throw new ApiError(0, timedOut ? 'TIMEOUT' : 'REQUEST_CANCELLED', undefined, [], write);
                const info = record(payload) && record(payload.error) ? payload.error : undefined;
                const code = info && typeof info.code === 'string' && Object.hasOwn(messages, info.code) ? info.code : 'HTTP_ERROR';
                const paths = info && strings(info.field_paths) ? info.field_paths.filter(v => /^[a-zA-Z0-9_.[\]-]{1,120}$/.test(v)).slice(0, 20) : [];
                const error = new ApiError(response.status, code, record(payload) && id(payload.request_id) ? payload.request_id : requestId, paths, write);
                if ([401, 403, 404].includes(response.status))
                    this.boundary(error, response.status === 401 || code === 'CSRF_INVALID');
                throw error;
            }
            if (decode === 'binary') {
                if (response.headers.get('Content-Type')?.split(';')[0] !== 'application/octet-stream')
                    throw new ApiError(response.status, 'INVALID_RESPONSE', requestId, [], write);
                const blob = await response.blob();
                if (captured !== this.epoch || controller.signal.aborted)
                    throw new ApiError(0, timedOut ? 'TIMEOUT' : 'REQUEST_CANCELLED');
                return blob;
            }
            if (!jsonType)
                throw new ApiError(response.status, 'INVALID_RESPONSE', requestId, [], write);
            let payload: unknown;
            try {
                payload = await response.json();
            }
            catch {
                throw new ApiError(response.status, controller.signal.aborted ? (timedOut ? 'TIMEOUT' : 'REQUEST_CANCELLED') : 'INVALID_RESPONSE', requestId, [], write);
            }
            if (captured !== this.epoch || controller.signal.aborted)
                throw new ApiError(0, timedOut ? 'TIMEOUT' : 'REQUEST_CANCELLED', undefined, [], write);
            if (decode === 'raw')
                return payload;
            if (!record(payload) || !id(payload.request_id) || !('data' in payload))
                throw new ApiError(response.status, 'INVALID_RESPONSE', requestId, [], write);
            try {
                return decode(payload.data);
            }
            catch {
                throw new ApiError(response.status, 'INVALID_RESPONSE', payload.request_id, [], write);
            }
        }
        catch (error) {
            if (error instanceof ApiError)
                throw error;
            throw new ApiError(0, timedOut ? 'TIMEOUT' : controller.signal.aborted ? 'REQUEST_CANCELLED' : 'NETWORK_ERROR', undefined, [], write);
        }
        finally {
            clearTimeout(timeout);
            signal?.removeEventListener('abort', cancel);
        }
    }
    async get<T>(path: string, decode: Decoder<T>, signal?: AbortSignal): Promise<T> {
        if (this.authChanging)
            throw new ApiError(0, 'AUTH_CHANGE_IN_PROGRESS');
        return await this.transport(path, { headers: { Accept: 'application/json' } }, decode, signal) as T;
    }
    async health(signal?: AbortSignal): Promise<components['schemas']['HealthResponse']> {
        const value = await this.transport('/api/health', { headers: { Accept: 'application/json' } }, 'raw', signal);
        if (!record(value) || typeof value.status !== 'string' || typeof value.service !== 'string' || typeof value.version !== 'string')
            throw new ApiError(200, 'INVALID_RESPONSE');
        return value as components['schemas']['HealthResponse'];
    }
    async entryFeedback(entryId:string,business:ConsoleCreate['business_code'],date:string,signal?:AbortSignal){
        const query=new URLSearchParams({business_code:business,business_date:date});
        const value=await this.get(`/api/v1/intelligence/entries/${entryId}/feedback?${query}`,parseEntryFeedback,signal);
        if(value.entry_id!==entryId||value.business_code!==business||value.business_date!==date)throw new ApiError(502,'INVALID_RESPONSE');
        return value;
    }
    async novelFeed(business:ConsoleCreate['business_code'],date:string,options:{platform?:'all'|'fanqie'|'qidian';rank_type?:string;gender?:'male'|'female'|'all';genre?:string;page?:number;q?:string}={},signal?:AbortSignal){
        const query=new URLSearchParams({business_code:business,business_date:date,platform:options.platform??'all',page:String(options.page??1)});
        for(const key of ['rank_type','gender','genre','q'] as const)if(options[key])query.set(key,options[key]);
        const result=await this.get('/api/v1/intelligence/novels?'+query,parseNovels,signal);
        if(result.business_code!==business||result.business_date!==date||result.page!==(options.page??1))throw new ApiError(502,'INVALID_RESPONSE');
        return result;
    }
    async intelligenceFeed(business: ConsoleCreate['business_code'], date: string, options: {lane: 'board'|'creator';page:number;q?:string;source?:string;accounts?:string[];videoCatalog?:'hongguo'|'tikhub';videoBoard?:string;videoGenre?:string;videoSubgenre?:string}, signal?:AbortSignal) {
        const query=new URLSearchParams({business_code:business,business_date:date,lane:options.lane,page:String(options.page)});
        if(options.q)query.set('q',options.q);
        if(options.source)query.set('source_id',options.source);
        if(options.videoCatalog)query.set('video_catalog',options.videoCatalog);
        if(options.videoBoard)query.set('video_board',options.videoBoard);
        if(options.videoGenre)query.set('video_genre',options.videoGenre);
        if(options.videoSubgenre)query.set('video_subgenre',options.videoSubgenre);
        if(options.accounts?.length)query.set('accounts',options.accounts.join(','));
        const result=await this.get('/api/v1/intelligence/feed?'+query,parseFeed,signal);
        if(result.business_code!==business||result.business_date!==date||result.page!==options.page)throw new ApiError(200,'INVALID_RESPONSE');
        return result;
    }
    async getSession(signal?: AbortSignal) {
        const expected = this.epoch;
        const session = await this.get('/api/v1/session', parseSession, signal);
        if (expected !== this.epoch)
            throw new ApiError(0, 'REQUEST_CANCELLED');
        return this.accept(session);
    }
    async login(body: Login, signal?: AbortSignal) {
        if (this.authChanging)
            throw new ApiError(0, 'AUTH_CHANGE_IN_PROGRESS');
        this.authChanging = true;
        this.boundary(undefined, true);
        try {
            const session = await this.transport('/api/v1/session', { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, parseSession, signal) as Session;
            return this.accept(session);
        }
        catch (error) {
            this.boundary(error instanceof ApiError ? error : new ApiError(0, 'NETWORK_ERROR'), true);
            throw error;
        }
        finally {
            this.authChanging = false;
        }
    }
    private headers(key?: string, contentType?: string) {
        if (!this.csrf || this.blocked)
            throw new ApiError(401, 'AUTH_REQUIRED');
        if (key !== undefined && !id(key))
            throw new ApiError(0, 'INVALID_REQUEST');
        return { Accept: 'application/json', 'X-CSRF-Token': this.csrf, ...(key ? { 'Idempotency-Key': key } : {}), ...(contentType ? { 'Content-Type': contentType } : {}) };
    }
    async logout(signal?: AbortSignal) {
        if (this.authChanging)
            throw new ApiError(0, 'AUTH_CHANGE_IN_PROGRESS');
        const csrf = this.csrf;
        this.authChanging = true;
        try {
            this.boundary(undefined, false);
            if (!csrf) throw new ApiError(401, 'AUTH_REQUIRED');
            const headers = { Accept: 'application/json', 'X-CSRF-Token': csrf };
            return await this.transport('/api/v1/session', { method: 'DELETE', headers }, value => {
                if (!record(value) || value.acknowledged !== true)
                    throw new Error('shape');
                return { acknowledged: true } as const;
            }, signal) as components['schemas']['Acknowledged'];
        }
        finally {
            this.authChanging = false;
            this.boundary(new ApiError(401, 'AUTH_REQUIRED'), true);
        }
    }
    async uploadFile(bytes: Blob, metadata: UploadMetadata, key: string, signal?: AbortSignal): Promise<FileInfo> {
        if (!id(key))
            throw new ApiError(0, 'INVALID_REQUEST');
        const headers = this.headers(key, 'application/octet-stream');
        const query = new URLSearchParams(Object.entries(metadata));
        return await this.transport(`/api/v1/files?${query}`, { method: 'POST', headers, body: bytes }, parseFile, signal) as FileInfo;
    }
    async importFile(metadata: ImportMetadata, key: string, signal?: AbortSignal): Promise<FileInfo> {
        if (!id(key))
            throw new ApiError(0, 'INVALID_REQUEST');
        return await this.transport('/api/v1/files/from-url', { method: 'POST', headers: this.headers(key, 'application/json'), body: JSON.stringify(metadata) }, parseFile, signal) as FileInfo;
    }
    async downloadFile(fileId: string, parent?: DownloadParent, signal?: AbortSignal): Promise<Blob> {
        if (this.authChanging)
            throw new ApiError(0, 'AUTH_CHANGE_IN_PROGRESS');
        if (!id(fileId) || (parent?.parent_id && !id(parent.parent_id)))
            throw new ApiError(0, 'INVALID_REQUEST');
        const query = new URLSearchParams(Object.entries(parent ?? {}).filter(([, v]) => v != null) as [
            string,
            string
        ][]);
        return await this.transport(`/api/v1/files/${fileId}/content${query.size ? '?' + query : ''}`, { headers: { Accept: 'application/octet-stream' } }, 'binary', signal) as Blob;
    }
    async listSources(business: string, signal?: AbortSignal, cursor?: string) {
        const query=new URLSearchParams({business_code:business,limit:'100',...(cursor?{cursor}:{})});
        return this.get(`/api/v1/sources?${query}`,parsePage(parseSource),signal);
    }
    async createSource(body: ConsoleCreate,key: string,signal?: AbortSignal) {
        return await this.transport('/api/v1/sources',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseSource,signal) as ConsoleSource;
    }
    async updateSource(source: string,body: SourcePatch,key: string,signal?: AbortSignal) {
        if (!id(source)) throw new ApiError(0,'INVALID_REQUEST');
        return await this.transport(`/api/v1/sources/${source}`,{method:'PATCH',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseSource,signal) as ConsoleSource;
    }
    async listTasks(business: string, signal?: AbortSignal,cursor?: string) {
        const query=new URLSearchParams({business_code:business,limit:'100',...(cursor?{cursor}:{})});
        return this.get(`/api/v1/tasks?${query}`,parsePage(parseTask),signal);
    }
    async getTask(task: string,signal?: AbortSignal) {
        if (!id(task)) throw new ApiError(0,'INVALID_REQUEST');
        return this.get(`/api/v1/tasks/${task}`,parseTask,signal);
    }
    async controlTask(task: string,action:'retry'|'cancel',body:components['schemas']['TaskControl'],key:string,signal?:AbortSignal) {
        if (!id(task)) throw new ApiError(0,'INVALID_REQUEST');
        return await this.transport(`/api/v1/tasks/${task}/${action}`,{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseTask,signal) as ConsoleTask;
    }

    async researchWorks(business:string,options:{q?:string;genre?:string;status?:string;page?:string}={},signal?:AbortSignal){
        const params=new URLSearchParams({business_code:business,...options});return this.get('/api/v1/works?'+params,parseResearchList,signal);
    }
    async researchHistory(work:string,signal?:AbortSignal){if(!id(work))throw new ApiError(404,'NOT_FOUND');return this.get('/api/v1/works/'+work+'/analysis-history',v=>{if(!record(v)||!['reports','evaluations','prediction_drafts','frozen_predictions','prediction_assessments'].every(k=>Array.isArray(v[k])))throw new Error('shape');return v as ResearchHistory;},signal);}
    async researchWork(work:string,signal?:AbortSignal){if(!id(work))throw new ApiError(404,'NOT_FOUND');return this.get('/api/v1/works/'+work,parseResearchWork,signal);}
    async submitResearch(body:DirectResearch,key:string,signal?:AbortSignal){if(!id(key))throw new ApiError(0,'INVALID_REQUEST');return this.transport('/api/v1/research/direct',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseResearchImport,signal) as Promise<ResearchImport>;}
    async submitIntelligence(body:IntelligenceResearch,key:string,signal?:AbortSignal){if(!id(key))throw new ApiError(0,'INVALID_REQUEST');return this.transport('/api/v1/research/submissions',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseResearchImport,signal) as Promise<ResearchImport>;}
    async addResearchMaterial(work:string,body:ResearchMaterial,key:string,signal?:AbortSignal){if(!id(work)||!id(key))throw new ApiError(0,'INVALID_REQUEST');return this.transport('/api/v1/works/'+work+'/materials',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseResearchImport,signal) as Promise<ResearchImport>;}
    async knowledgeItems(business:string,candidates=false,signal?:AbortSignal,report?:string,filters?:{q?:string;category?:string}){
      return this.allPages(cursor=>{const query=new URLSearchParams({business_code:business,limit:'100',...(cursor?{cursor}:{}),...(report?{source_report_id:report}:{}),...(filters?.q?{q:filters.q}:{}),...(filters?.category?{browse_category:filters.category}:{})});return this.get('/api/v1/knowledge'+(candidates?'/candidates':'')+'?'+query,parsePage(parseKnowledge),signal);});
    }
    async createKnowledge(body:KnowledgeInput,key:string,signal?:AbortSignal){return this.transport('/api/v1/knowledge',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},parseKnowledge,signal) as Promise<KnowledgeItem>;}
    async reviseKnowledge(kid:string,body:KnowledgeRevisionInput,key:string,signal?:AbortSignal){if(!id(kid))throw new ApiError(0,'INVALID_REQUEST');return this.transport('/api/v1/knowledge/'+kid+'/revisions',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},value=>{if(!record(value)||!id(value.id)||value.knowledge_id!==kid)throw new Error('shape');return value;},signal);}
    async knowledgeSources(rid:string,signal?:AbortSignal){if(!id(rid))throw new ApiError(0,'INVALID_REQUEST');return this.get('/api/v1/knowledge/revisions/'+rid+'/sources',value=>{
      if(!record(value)||value.revision_id!==rid||!id(value.knowledge_id)||!(value.source_report_id===null||id(value.source_report_id))||!Array.isArray(value.items)||!value.items.every(e=>record(e)&&id(e.id)&&['raw_asset_id','artifact_version_id','target_artifact_version_id','work_id'].every(k=>e[k]===null||id(e[k]))&&['quoted_text','attribution'].every(k=>e[k]===null||typeof e[k]==='string')&&typeof e.origin==='string'&&(e.business_code===null||['motion_comic','story_short','ecommerce_video'].includes(String(e.business_code)))&&e.independently_verified===false&&['whole','paragraph','page','time'].includes(String(e.locator_kind))&&['paragraph_no','page_no','start_ms','end_ms','episode_no','material_version_no'].every(k=>e[k]===null||Number.isSafeInteger(e[k])&&Number(e[k])>=0)))throw new Error('shape');return value as KnowledgeSources;
    },signal);}
    async knowledgeItem(kid:string,candidate:boolean,signal?:AbortSignal){if(!id(kid))throw new ApiError(0,'INVALID_REQUEST');return this.get('/api/v1/knowledge/'+(candidate?'candidates/':'')+kid,parseKnowledge,signal);}
    async knowledgeReview(rid:string,signal?:AbortSignal){if(!id(rid))throw new ApiError(0,'INVALID_REQUEST');return this.get('/api/v1/reviews/'+rid,parseKnowledgeReview,signal);}
    async approveKnowledge(rid:string,body:KnowledgeApproval,key:string,signal?:AbortSignal){if(!id(rid))throw new ApiError(0,'INVALID_REQUEST');return this.transport('/api/v1/reviews/'+rid+'/approve-publication',{method:'POST',headers:this.headers(key,'application/json'),body:JSON.stringify(body)},value=>{if(!record(value)||!id(value.id)||!id(value.revision_id))throw new Error('shape');return value;},signal);}
    private async allPages<T extends {id:string}>(load:(cursor?:string)=>Promise<ConsolePageData<T>>) {
        const records=new Map<string,T>();const seen=new Set<string>();let cursor:string|undefined;
        for (;;) {
            const page=await load(cursor);
            for (const item of page.items) records.set(item.id,item);
            if (page.next_cursor===null) return {items:[...records.values()],next_cursor:null,total:String(records.size)} as ConsolePageData<T>;
            if (!page.items.length || seen.has(page.next_cursor)) throw new ApiError(200,'INVALID_RESPONSE');
            seen.add(page.next_cursor);cursor=page.next_cursor;
        }
    }
    async listAllSources(business:string,signal?:AbortSignal) {
        return this.allPages(cursor=>this.listSources(business,signal,cursor));
    }
    async listAllTasks(business:string,signal?:AbortSignal) {
        return this.allPages(cursor=>this.listTasks(business,signal,cursor));
    }

}
