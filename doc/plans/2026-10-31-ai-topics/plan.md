# AI选题与闪念生成实施计划

> 实施采用测试先行；后端模型配置、前端选题和后端选题按明确接口分工，最终独立审阅。用户已明确直接执行，不重复等待方案审批；本计划按项目要求存doc。

目标：保留Demo布局，把“AI再来5个”、闪念胶囊及头脑风暴单题生成接成真实服务；所有新增模型调用统一引用控制台配置。暂缓电商选题；本轮不启动观众反馈AI改造、不把生成视为已评分，不自动执行多轮模型调用。

架构：FastAPI＋PostgreSQL版本数据＋现有持久任务Runner／独立topics队列＋React真实页面。只引用已授权正式知识和真实情报，不发送演示数据；生成素材和模型配置版本冻结。原Demo及用户本地记录保持，不静默导入演示数据。当前大量未提交工程为必要基线，原目录增量开发，不重置／切到缺少该基线的HEAD工作树；不代为Git提交或推送。

模型配置：沿用Demo模型源两类text/vision、多来源、按业务及处理环节分配。使用服务端密钥引用（本轮DEEPSEEK_KEY／OPENAI_API_KEY），不把密钥写入浏览器或接口回包；新增统一解析服务，仅选择并保存的配置可用，不自动复用.env。保留模型／参数不可变修订，任务冻结精确版本。endpoint仅HTTPS公开主机，禁止私网、重定向和凭证URL；失败保留，默认无自动重试。用户保存配置前不得真实调用。初期文本接口DeepSeek／OpenAI兼容，其他适配器明确不可执行。

产品：AI再来5个=一次模型调用，校验恰好5题成功后原子保存候选卡；闪念为独立跨业务个人记录，编辑形成版本；头脑风暴选择去重闪念＋方向，一次调用得1题，只有保存才成为卡片；改组合后旧结果不能保存。标题／目标人群／Logline／自由角色设定／全局节奏一致，编辑无变化不增版本、实质修改创建修订并标待重评；选中与交接绑定具体版本。保留候选／待生产与复制／导出，禁止伪造评分；评分请求留存为待配置／待实现，不创建无人处理的任务。

接口约定（data envelope、现有会话／CSRF／Idempotency-Key）：
- GET /api/v1/model-config?business_code=... → {sources:[{id,name,provider,capability,endpoint,model,secret_ref,timeout,retries,max_tokens,version,lock_version,enabled,credential_ready}],bindings:{stage:source_id},lock_version:string}。
- POST /api/v1/model-config/sources → {id?:uuid,expected_lock_version?:string,name,provider,capability,endpoint,model,secret_ref,timeout,retries,max_tokens,enabled:true}；回完整source。
- POST /api/v1/model-config/bindings → {business_code,expected_lock_version:string,bindings:{stage:source_id}}；回同GET配置。新增source／保存分配都不请求模型。
- GET /api/v1/topics?business_code=...&pool=candidate|production&page=1 → {items:Topic[],total:string,page:number,page_size:9,model_ready:boolean}。
- POST /api/v1/topics/generate → {business_code,mode:'batch'|'brainstorm',spark_ids:uuid[],instructions:string}；回Generation。
- GET /api/v1/topics/generations/{id} → Generation={id,task_id,state,safe_error_code,business_code,mode,saved_topic_id:null|uuid,result:null|{topics:TopicFields[]},created_at,input:{spark_ids:uuid[],instructions:string}}。
- POST /api/v1/topics/generations/{id}/save → {fields:TopicFields}，仅brainstorm成功且未保存，返回Topic。
- POST /api/v1/topics → {business_code,fields:TopicFields}；PATCH /api/v1/topics/{id} → {expected_version:number,fields:TopicFields}；GET /api/v1/topics/{id} → Topic。
- POST /api/v1/topics/{id}/select → {expected_version:number}；POST /api/v1/topics/{id}/handoff → {expected_version:number,method:'copy'|'export',phase:'authorize'|'confirm'}。
- TopicFields={title,audience,logline,character_settings,global_rhythm}; Topic={id,business_code,version:number,status:'candidate'|'production',fields,origin:'manual'|'batch'|'brainstorm',created_at,updated_at,evaluation_status:'not_evaluated'|'needs_review',source_refs:object,history:[{version,fields,created_at}],handed_off:boolean}。
- GET /api/v1/sparks → {items:Spark[]}；POST /api/v1/sparks → {text,expected_version?:number,id?:uuid} → Spark={id,version:number,text,title,created_at,updated_at}。当前成员隔离，无输入空白不创建，每次显式保存形成版本；UI输入自动保存需防竞态。
- 统一前端客户端扩展public json<T>(path,method,body,key,decoder,signal)调用原transport与headers，不能旁路会话／CSRF处理。

数据库：0029模型源／环节分配，由模型配置任务负责；0030选题卡／不可变修订、闪念／不可变修订、单题生成保存绑定及交接事实。真实数据库受限角色增量权限、同组织FK、版本并发、sealed/immutable约束按既有模式；不放宽旧表／鉴权。所有生产库迁移先隔离库验证。

- [x] T1 控制台真实模型源／版本／分配、统一模型调用适配及React模型页；配置表迁移与无网络测试。接口及权限／CSRF／乐观锁／SSRF回归。完成后告知用户配置并保留待配置状态。
- [x] T2 选题／闪念契约、数据字典及0030迁移；修订不可变、跨组织拒绝、幂等、无变化不增版／重复保存拒绝。隔离PG及回退升级验收。
- [x] T3 冻结真实上下文和模型配置、结构校验／证据引用与持久任务；批次5题原子入库、单题草稿显式保存；取消／撤权／重复点击／模型错误不发布假卡。纯模型假传输单测＋真实PG任务链。
- [x] T4 React选题／待生产／闪念／头脑风暴替换Demo岛，沿用页面布局／文案和9项分页，轮询任务、错误／待配置、编辑修订及交接。语义测试、类型／lint／构建及Demo对照。
- [x] T5 独立审阅、修复及最终回归完成；用户控制台配置后真实脑暴1题／批量5题通过，首次失败后另获1次补测授权，总3次，无自动重试；文档／AGENTS／计划已回填，S08整体不勾选。

风险验证：模型输出不合规不落库；素材含指令不执行；模型配置变动／撤权让在途任务失败且保留证据；生成中切业务不串结果；双击只产生一个付费任务；用户闪念不进入共享成员视图；旧Demo记录不混入真实卡片；未评分显示未知，编辑不沿用旧分数。

实施证据：[验证与待配置交接](verification.md)。T1～T4为工程／隔离验证完成，不代表真实模型效果；T5已完成一批5题和一组闪念单题真实链路验收；首次批量失败后用户额外批准1次补测，总3次，原失败保留。原创性与评分待后续，不冒称完整S08.2。

最新输出上限：用户明确取消系统自定义限制，控制台max_tokens允许null，留空则不发送该参数，由供应商默认／硬上限控制，非无限输出；单HTML同步。
