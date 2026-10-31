# 选题素材抽象、相似性筛查与版本评分实施计划

> 按用户“按建议补充，开始执行”直接落实，不重复方案审批。使用writing-plans／subagent-driven-development：固定接口后按独立文件分工，测试先行，末尾独立审阅。延续原目录必要未提交基线，不重置、不Git提交／推送。

目标：避免把热榜简介换标题当新选题；把既有Demo的AI漫剧十维评估变成真实、可追溯、版本隔离的执行。技术沿用FastAPI／PostgreSQL、持久任务、独立topics队列、React及当前Demo，不新增供应商或依赖。当前用户已明确同意推荐补充并开始执行；本文是实现细化，不虚构用户已逐项选过技术实现。

## 一、实现选择与边界

单纯加强提示词不能隔离原故事，只有字面相似度也不能识别换名照搬，因此采用：独立一次模型抽象→独立一次创作→服务端本地相似性检查，最多2次外调／1次attempt，无自动纠错重试。原始情报／知识保留冻结引用；第二次生成只接抽象后的情绪、冲突、代价与结构机制，不传平台简介全文。用户私有闪念为创作意图，允许保留其完整原文与版本。抽象须合法来源ID、无凭空新来源；模型声明的专有名称必须在原文出现，生成不得重复。筛查是启发式“与本批来源未见明显文字重合／发现风险”，不是版权或全网原创性证明；相似风险不发布新卡，原始响应仍留档。人工编辑和脑暴保存也再筛查，不悄悄删除旧6卡，旧卡显示当前检查结果。

保留topic.generate/v1和旧任务可读；新生成走v2、预算2，使用现有topic控制台绑定（两阶段共用），原版历史及来源不重写。v2抽象与创作分别保存AIExecution、私有响应、请求清单／SHA及token；第二阶段的输入明确可证明没有原情报全文。共享call执行函数保留checkpoint、实时权限／配置校验及错误用量，不改变旧v1预算。

评分独立topic.score/v1，最多1次外调／1次attempt，使用控制台topic_score绑定；不静默借用topic。当前唯一模型来源可通过控制台绑定AI漫剧topic_score后实测，保存不调用模型。量表genre-load-v2（国内80集）仅AI漫剧，故事短片返回RUBRIC_UNAVAILABLE并明确提示，不能硬套量表；不增加未经用户确认的立项分数线。十项每项0～5整数或证据不足null，分组内容／市场各25，服务端求和；缺一项总分null，不能把未知当0，市场无真实依据必须null，不虚构CPI／用户规模。analysis与不足原因留存，UI按Demo展示问题／分数／比例条，缺项为—，旧分数不能用于新版。

## 二、接口／数据约定（分工共同依据）

TopicView新增可选originality:{status:'no_obvious_overlap'|'risk'|'unchecked',matches:[object],limitations:string}；evaluation_status扩展not_evaluated|needs_review|pending|scoring|scored|insufficient_evidence|failed；assessment:null|AssessmentView，evaluation_task:null|ScoreTaskView，score_model_ready:boolean。旧客户端/测试缺新增字段须兼容；新增响应真实服务始终返回，不能把非法分数容错为有效评分。

AssessmentView={id:uuid,topic_version:int,rubric_version:'genre-load-v2',dimensions:[{key,score:int|null,analysis:string}],content_total:int|null,market_total:int|null,total:int|null,limitations:[string],created_at:datetime}。维度固定顺序：emotion,conflict,contrast,antagonist,twist,audience,platform,acquisition,sequel,differentiation；market信息不足允许5项全null。ScoreTaskView={id:uuid,task_id:uuid,state:任务标准状态,safe_error_code:string|null,topic_id:uuid,topic_version:int,assessment:AssessmentView|null}。

POST /api/v1/topics/{topic_id}/evaluate {expected_version:int}→202 ScoreTaskView；GET /api/v1/topics/evaluations/{evaluation_id}→ScoreTaskView。使用现有session／CSRF／幂等协议，动作content.write执行、content.read读取。相同当前版本任务并发／重复启动有门禁；实质编辑后评分需新修订，旧评分留历史但不回填新版。任务冻结确切选题修订／字段SHA／来源／量表／配置；发布再核当前head，不接受过期完成污染新版。评分中修改应安全失败或仅保留旧版结果，不改变新版本状态。

0031_topic_assessments仅新增不可变评分表，组织/选题/修订/任务/AIExecution同组织绑定且不能错绑；body JSON冻结评分，任务唯一，数据字典与权限表同步。不改变旧六张卡／旧配置；旧表权限不扩展，新增表必要SELECT/INSERT，生产升级前先隔离升降级及受限角色测试。

## 三、任务与文件归属

- [x] Q1 素材抽象与筛查：topics/quality.py、generation_v2.py、generation.py v2默认/兼容、worker.py双版本、test_topic_quality.py与独立PG tests。v2两阶段、第二请求无原简介、来源伪造拒绝、抄句／风险响应拒绝、用户闪念不误判、旧v1仍可读。生成实现负责人，不改service/models/contracts/http。
- [x] Q2 评分持久化：topics/scoring.py／score_model.py／score_http.py／score_contracts.py、core/models新增表、0031 SQL+Alembic／manifest、topics/contracts.py扩展view、topics/service.py投影与保存门禁、评分纯与PG测试及字典。评分负责人；score worker root挂接。
- [x] Q3 React评分与检查展示：topics/contracts.ts、TopicEditor/TopicsPage及新ScorePanel，绑定当前版本任务轮询；卡片左上角恢复Demo分数徽标，同详情十维，null不画有效比例；保存并重新评分确实提交，新增详情“评分”按钮用于旧未评卡。仅显式动作执行，不在页面读取时付费，按钮忙碌防重、同key恢复。Demo对应按钮/说明同步、局部草稿及身份边界保持。前端负责人。
- [x] Q4 Root实现共享topics/execution.py调用执行／验证助手，集成handlers/worker routes/main契约，生成OpenAPI/types；冻结接口后集成、隔离迁移与受限角色验收、旧快照/6卡指纹保持；真实少量验证（新生成1次最多2模型调用＋单卡评分1次最多1模型调用），既有成功任务不重跑，无自动额外调用。
- [x] Q5 最终独立审阅修复、完整相应测试、真实页面和Demo对照，更新AGENTS／研发计划与执行证据。评分缺市场依据则验收“内容部分可评、市场未知”，不伪造完整总分。下一步观众反馈另行实施，不混入本任务。

共享execute_call签名：execute_call(runner,ticket,checkpoint,config,system,user,schema,*,invocation_no,prompt_version,validator,model=None,store=None)→{execution_id:str,output:dict}；validator(decoded)返回规范化dict。读取已存响应可复核SHA与validator一致；所有caller沿用task budget。Root负责此文件，子任务调用，不重复实现。

## 四、关键风险与验收

相似性仅对实际冻结来源，不全网宣称原创；缺来源／失败／撤权／配置变更不发布；整批任一非法全部不发。评分不能偷偷制造市场依据，服务端必须检查缺项总分null和整数范围。修改旧卡或生成后手工改稿再保存必须重新筛查；旧评价不得混入新版、导出或复制。个人闪念及来源撤回仍保留现有访问控制，页面后台轮询不得自动发模型请求。用户允许自定义输出上限空值的配置保持，模型返回过长或非法不自动重试。

最终证据：[验收记录](verification.md)。真实新增5候选与1评分、3模型调用，原6卡与30,424榜单成员不变；市场数据不足保留未知。
