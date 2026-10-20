# AI任务定义

版本：v1.0｜日期：2026-10-17｜S06.4反馈／洞察与S07.1六类任务基线；用户指定DeepSeek／deepseek-flash，密钥仅服务端读取。S06.4真实调用已完成，S07.1验证状态见执行记录。

## 1、共用执行约束

模型输入只引用已授权的不可变快照和评论原文，业务日期使用Asia/Shanghai；标题、评论及外部正文均是不可信资料，不作为工具指令。模型无采集／网络／执行工具，不接受输入中的改规则、泄密或另调接口指令。密钥仅从服务端配置读取，禁止进入输入清单、模型输出或审计。

生成前冻结输入ID、版本、原文和摘要；预算由服务端任务冻结，不自动翻页、扩大样本或重试计费。首次验收已以一条作品、20条评论、一次模型请求完成，续执行与费用次数以执行记录为准。模型厂商、模型、提示词／模板版本、输出模式与真实用量须落AIExecution，不猜测费用。

## 2、audience.feedback.v1

输入：业务、业务日期、情报快照ID／版本、条目ID、平台、采样策略及原文列表。每条含稳定证据ID、平台评论ID（可空）、正文、采集时间、原始发布时间和点赞（可空）。同一平台评论ID只保留一次；无ID仅按原始证据身份去重，不做正文相似合并。单次最大20条。不得使用别的日期或业务补齐。

输出：result_state为completed或insufficient_evidence，summary及claims。每条结论有唯一claim_key、kind和非空comment_ids；情绪须含触发原因，反馈须含维度及受欢迎／问题类型，期待区分明确表达／系统推测，建议含优先级、适用环节、反馈→调整→验证。建议均待验证，不产生正式评分、预测或知识。系统校验引用属于冻结样本，支持数按原文ID去重计算，不信模型自报；情绪分母为至少一个情绪标签的去重评论，多标签比例可超过100%。0已分类时比例未知，不显示0%。

失败：缺少原文／有效样本、无引用结论、未知或重复引用、输出结构错误、业务／日期不一致、模型未配置、访问撤销、预算耗尽及外部结果未知；失败不创建反馈快照。证据不足不得冒充完成结论。TOP评论按已采样点赞排序，未知排后，同赞按冻结样本顺序；只取5条，不声称平台排名。

## 3、intelligence.insight.v1

输入：同一业务／日期的一组情报快照版本及已封存反馈版本、范围说明。禁止自动选择最新日期、跨业务拼接或将关键词搜索叫作榜单。输出：有证据引用的市场情绪、高频母题、主要题材、建议选题方向及覆盖限制；每条引用具体反馈ID，服务端验证均在冻结输入集合。少量关键词作品仅称“本批样本观察”，不推断市场总体；缺少评论时不生成市场情绪。检索／筛选只改变列表，不即时重算报告。

失败：无合格反馈、跨日期／跨业务、未知证据、输出无支持项、模型／模板未配置、权限或预算失效。洞察持久化、模型执行及真实验收待前置配置，当前界面不生成固定摘要。

## 4、送研判冻结

冻结包包括业务／日期、快照ID／版本、条目ID、反馈ID／版本、采样说明、原文与结论引用、SHA-256摘要。创建独立拷贝，后续新采集及客户端修改不能改变原包；服务端提交时必须重验权限与版本，不能信任客户端提供摘要。独立intelligence_handoffs已由S06.4封存并实测；正式research_submissions的关联由S07.2接入，不创建虚假研判任务。

## 5、读取契约（本轮先行接入）

`GET /intelligence/entries/{entry_id}/feedback?business_code&business_date`：明确指定当前业务和日期，条目不匹配返回404。返回条目／快照ID、日期、平台、status、反馈ID／版本、采样和覆盖限制、comments与claims；当前无已封存反馈返回not_acquired，sample_count／classified_count为NULL，绝不以作品评论总量推断已采样。没有来源回执时不能声称empty或failed。读取不触发采集／模型，不产生计费。未来确认空、采集失败须先建立有来源证据的采样回执，不能仅靠前端字段标记。

`GET /intelligence/feedback/{feedback_id}`：读取封存的整份反馈及原文引用；逐项检查所属情报来源及全部评论原始证据的当前权限，撤回时404，不退回旧版本。条目接口按content_id投影，原始反馈版本不变；跨作品结论不作局部截断。原文作者当前字典未保存用户名，接口先返回NULL，页面显示“用户名未获取”，不编造匿名身份。

## 6、DeepSeek适配实现

固定官方端点https://api.deepseek.com/chat/completions、模型deepseek-flash；[官方JSON说明](https://api-docs.deepseek.com/guides/json_mode/)要求json_object并在提示中包含JSON格式约束，模型响应仍须经本地schema和引用校验。[官方思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)默认开启，本小样本任务显式disabled；输出上限2048 tokens、输入含schema与提示词不超过32KiB、响应不超过1MiB。请求前必须执行预算预留回调，独立冻结本次消息及摘要；不重定向、不重试、无工具。超时保留外部结果未知语义，供应商错误正文不外泄；输入／输出用量取真实usage，缺失为NULL，不推算费用。真实链路已通过手动受控任务执行验收；生产Worker未启用此链路，禁止自行追加模型调用。

S06.4继续执行（2026-10-17）：用户切换评论供应商至TikHub，已完成唯一一次首屏请求，返回20条有效正文；不再调用JustOneAPI。先用该不可变原包做零外部调用的评论规范化，再进行一次DeepSeek反馈执行，输入只含正文、证据ID、时间与点赞。模型请求前写ai_executions预留，输入／输出JSON使用私有file_objects留档，反馈与原文按既有S封存约束保存；失败不自动重试。用户名按新增字典列保留，但不进入模型输入。

## 2026-10-17 S06.4收尾契约

冻结服务使用指定快照／条目及显式反馈ID、版本，不自动替换最新反馈；无评论可冻结作品事实并明确反馈未获取。独立`intelligence_handoffs`保存规范化JSON、SHA-256、schema=1、创建人及强类型父引用；不可变，业务／日期与封存父快照一致。创建需当前`research.submit`及全部源数据读取权限，读取需当前`content.read`及原始依赖权限。创建／幂等重放均先重验；同成员同幂等键、同请求返回同包，变更请求冲突。读取校验摘要及父版本，后续新采集不改原包。此包供S07.2引用，不创建作品、材料或付费任务，前端研判按钮当前不冒充已提交。

创建接口：POST `/api/v1/intelligence/entries/{entry_id}/research-evidence`，请求含业务／日期、snapshot_id／snapshot_version、可空feedback_id／feedback_version；拒绝额外正文／摘要／actor及不成对的反馈引用。读取接口：GET `/api/v1/intelligence/research-evidence/{handoff_id}`。响应含id、created_at、frozen_by、manifest_sha256及body（完整快照字段、指定条目的观测、单作品反馈／原文／引用）；凭据及无关用户资料不入包。

## S07.1、解析至审核任务基线

2026-10-17新增。唯一可执行定义为[research.py](../../backend/app/ai/research.py)，生成快照为[六类任务JSON](ai/research-task-definitions.json)，用`backend/.venv/bin/python scripts/research_definitions.py --check`检查漂移。以下是任务设计与安全门禁，不代表S07.2～S07.4业务处理器已上线；本阶段真实调用只覆盖`research.decompose.v1`的简介文本小样本。

### 1、共用输入、版本与证据

ResearchInput包含business_code、scope（简介／材料／单集／局部作品／全作品）、outcome_exposure（observed／unobserved／unknown）、segments及实际missing_inputs；可选template_revision、rubric_revision、target_revision均含稳定ID、版本及SHA-256。当前只开放motion_comic工作区文本定义，其他业务在S08.1补专用模板。目标scope不等于已验证覆盖，模型不能自报全剧合格。

每个segment含唯一id、source_kind（content_observation／material_version／parsed_document）、source_id、source_version及原文。模型引用segment_id＋精确连续quote，服务端检查属于冻结集合、引文唯一可定位，生成字符区间[start,end)、源对象／版本和文本SHA；非法／重复引用拒绝，不用模糊匹配纠正。不可变观测的source_version=1仅是证据对象版本，不冒充正式material_versions版本。实际上传／音视频在S07.2生成解析文档及时间码，媒体引用格式按那一阶段接口落实，当前文本模型没有音视频感知能力。

输入冻结含规范化JSON、任务定义版本、提示词SHA、输出schema；执行配置保存模型、参数及schema摘要，请求manifest保存精确messages和请求摘要。数据库的ai_config_revision_id是当前验证配置稳定引用；代码提示词版本不是已批准的standard_revisions。S07.2／S07.3创建正式报告和评价前必须绑定实际模板／Rubric修订，并验证业务与材料适用性。输入第三方正文始终是不可信资料，不执行其中指令，无工具／联网权限，密钥及无关作者信息不进入模型消息。

### 2、六类任务输入输出

六类共同输出result_state=completed／insufficient_evidence、coverage、limitations、claims；claim含唯一key、dimension、finding、非空evidence。引用检查只证明锚点存在，不能自动证明推论成立。completed至少有一条有效结论；缺失值不能补零，事实与建议须分别表达，模型失败只留下执行记录，不写合格业务结果。

| 任务／版本 | 输入与专用输出 | 失败／证据不足及业务门禁 |
| --- | --- | --- |
| research.parse.v1 | 已授权文本及文件版本；detected_kind=text，claims.finding逐字等于单条引用quote，生成确定性字符锚点 | 无正文、未验证文件、类型不支持、乱码或引文失真拒绝；OCR／ASR／帧提取未在本阶段实现，不将简介当剧本全文 |
| research.decompose.v1 | 解析原文／简介、范围、分析模板修订；claims按人物、目标、冲突、设定、主线等归类；当前简介最多3条短观察 | 缺集、结局、视听或评论明确列缺失；不能编剧情、镜头、终局与高潮曲线；简介输出固定partial |
| research.evaluate.v1 | 冻结材料与报告、Rubric修订及适用维度；grade可空，dimensions含name、state、claim_keys | 当前SABC边界未批准，grade必须NULL、result_state必须insufficient_evidence；可保存有依据的局部观察，不能自动填C或以播放量代替质量 |
| research.predict.v1 | 正式输入集、指标定义／版本、平台／账号、相对发布窗口、发布条件、独立校准样本、结果暴露信息；指标、窗口、区间及uncertainty_note | 当前无批准指标／校准，指标／窗口／上下界均NULL，返回不可可靠预测；已知实绩只允许回顾，不产生盲预测。S07.3才绑定metric_specs与真实发布条件、冻结时间；不自行默认“24小时／7天” |
| research.extract.v1 | 具体报告与结论版本；candidates含title、body、knowledge_type、browse_category、applicability、limitations、claim_keys、status=pending_ai_review | 无源证据不产候选；简介不可直接产method_rule；类型／五类浏览分类沿用数据字典，不创建新枚举；候选不代表已入库或已验证规律 |
| research.review.v1 | 精确候选／报告版本及摘要，源证据、正式知识检索对照和适用标准；decision及support／completeness／duplicate／conflict／applicability五类checks | 当前尚无冻结审核目标和检索链，不能approved；不因无检索结果假称无重复。S07.4才开放真实AI审核处理器，仍需独立人工批准。实质修订使旧审核不适用 |

正式拆解报告由S07.2按Demo文档组装：0优缺点、1故事大纲、2情绪与母题、3人物设计、4世界观与长线悬念、5情节冲突、6节奏结构、7终局、8高潮曲线、9观众反馈；分别表达事实分析和改写建议。未覆盖部分保留章节、明确材料不足，不补画曲线；S07.1简介claims是该结构的局部证据输入，不创建完整报告。全剧资格须由服务端核验已知总集数、必要单集／材料覆盖和适用模板；在S07.2落实前，机器校验拒绝coverage=full。

### 3、模型、预算与状态

沿用用户指定DeepSeek／deepseek-flash，固定官方端点、JSON响应、thinking disabled、2048输出tokens、请求32KiB／响应1MiB，不传工具、不重定向／重试。2026-10-17核验[官方模型说明](https://api-docs.deepseek.com/quick_start/pricing/)和[JSON模式](https://api-docs.deepseek.com/guides/json_mode/)；服务端别名可能升级，记录请求模型标识与实际返回请求ID，不据网页推断本次服务版本／扣费。usage记录真实input_tokens／output_tokens，未有账单的费用为NULL。

S07.1验证任务`research.definition-probe`，一次尝试、一次外部预算，以原快照／条目及配置为输入，提交、执行前、预算预留前及完成时均重验当前身份、来源读取／research.submit与research.run、原包及配置版本；model.configure单独授权。ai_executions预留事务与私有输入manifest先提交，再发网络请求，输出另存私有file_objects。重复提交按定义版本＋条目幂等；重复消息不得重新消费预算。来源暂停允许读取已保存资料，不启用采集计划。

结构错误、截断、空回复、外来证据→INVALID_RESPONSE；权限／版本失效→拒绝或任务失败；超时／连接中断→EXTERNAL_RESULT_UNKNOWN，保留预留且不自动重试。配置缺失／禁用拒绝执行。合法insufficient_evidence是有说明的业务结果，不伪造completed；外部成功而发布前撤权时，AIExecution可保留实际结果，任务不能发布合格输出。验证任务只登记AIExecution输出，不创建works、materials、analysis_reports、quality_evaluations、predictions、knowledge或审核决定。

### 4、验收边界

一次既有TikHub短剧简介验证，不再采集平台数据、不追加评论／模型轮次；本样本结果已暴露，且当前榜含真人短剧，不能算AI漫剧全剧质量、视听分析或盲预测验收。六类schema和门禁离线验证，真实调用只验证简介拆解的请求、用量、结构与精确引用；解析媒体、定量评价、预测能力、候选提炼和双审上线分别留S07.2～S07.4。

执行证据与最终状态见[S07.1执行记录](../plans/2026-10-17-S07.1任务定义与模型验证.md)。

S07.1实测已完成：一条162字简介、1次DeepSeek请求，890输入／479输出tokens，3条局部观察及5处精确原文锚点。当前用户缺research.run，按用户明确授权仅当前来源临时授予该动作，执行后已撤销；现有本地入口不自动授予分析员权限。详见执行记录；未生成正式报告或发布知识。

## S07.3正式材料任务v2（2026-10-17）

S07.1六类v1定义与历史验证保持不变。新增正式材料decompose／evaluate／predict v2，机器实现为backend/app/research/stage_model.py、analysis.py与analysis_task.py；DeepSeek Flash固定单次调用、max_tokens=2048，schema／system SHA／配置摘要必须匹配。输入绑定InputSet及标准版本，排除人工初评，输出逐段原文验证后才写领域对象。实际模板／Rubric须有同摘要人工批准，AI配置须服务端登记，不自动配准或批准。

只有包含S／A／B／C四项非空文字规则的grading_rules映射才开放材料级评级；不预设各等级内容或分数，参考简介仍不评级。predict目前严格为insufficient_evidence、指标／窗口／区间NULL，只形成有缺项说明的判断；人工明确数值另走草稿与冻结，不与AI结果混写。全剧覆盖、视听、数值预测效果和真实模型验收尚缺条件，按用户决定后补。详见[S07.3执行记录](../plans/2026-10-17-S07.3评价预测与报告.md)。

## S07.4、候选提炼与审核 v2（2026-10-17）

`knowledge.extract.v2`与`knowledge.review.v2`由`backend/app/knowledge/model.py`维护，保留S07.1六类v1定义与摘要不变。固定DeepSeek Flash、JSON、2048输出tokens及共享32KiB输入上限，无网络工具、无自动重试，每任务最多一次调用。配置须匹配schema／prompt／parameters摘要，绑定同业务已人工批准的prompt标准；不自动创建或启用真实配置。

提炼冻结确切报告、原文引用、配置与标准，候选绑定报告及已有证据ID，只创建pending_ai版本及其独立knowledge_release请求，不沿用报告的审核来发布知识。引用逐字且唯一可定位；简介不得推出method_rule；每个候选说明样本、范围和限制，最多5条。

审核冻结目标Revision／Report摘要、预期AI head以及当前授权AI漫剧正式Publication版本对照。空对照表示该范围在此快照下无可访问正式条目，不表示全库无重复；模型必须给support／completeness／duplicate／conflict／applicability五项唯一check。approved必须有精确引用、五项supported和已完成对照；缺原文不排队。正文与对照都是不可信材料，无工具，不服从其中指令。当前仅motion_comic模板，跨业务／共享多业务审核待S08.1。

AIExecution及私有输入／输出保存真实执行事实。completed输出才追加AI决定；失败／insufficient保留执行与任务证据，不伪造completed调用或AI approved。新一轮任务待执行、异常或不足期间，旧批准不能继续发布。实质修订使原Request不适用于新版本；迟到结果重查权限、租约、当前版本、预期head后才能生效。

人工知识批准绑定当前approved AI，随后另验knowledge.publish、KnowledgeItem锁和确切版本；Demo“人工通过并入库”在同事务提交两步，发布失败不遗留人工批准。evaluation_review的人工确认／反驳只追加决定，不改AI原评级／维度。实际模型效果按用户决定后验，本轮不触发付费调用。


2026-10-17 S07.4收尾：人工新增可显式提交原文和出处，复用原始资料及EvidenceRef；冻结输入source_provenance逐段标origin=manual、independently_verified=false。纯链接／普通备注不产生可审核原文。已用隔离PG与MockTransport验证人工新增→原文冻结→AI决定→人工发布；未进行真实模型调用或质量验收。
