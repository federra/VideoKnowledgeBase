# 市场承重AI推断评分调整

用户已明确：市场承重五维可由AI推断判断。按现有框架直接实施，不重复方案审批；维持十维每项0～5／总50，无新增合格分数线，市场推断不作为实测用户规模、CPI或收益。评分仍统一控制台topic_score、1次调用／1次attempt，无自动重试；输出长度空值保持。

新评分使用topic.score/v2＋genre-load-v3-inferred，五个市场维度按创作定位／常识／文本进行推断，须说明推断理由与不确定性；不能凭空引用真实数据或编造CPI数字。允许null仅为模型确实无法判断，不再服务端强制市场全空。总分仍服务端严格整数校验后求和，未知不作0。旧v1／genre-load-v2及其市场null原始规则保留，旧评分不改写。新视图增加market_basis='ai_inference'|'unavailable'标识，评分结果／市场分组以紧凑“AI推断”标签区分，保留当前Demo布局与仅问题分数条，不展开分析长文。

0032_market_inference只修改评分表允许的量表CHECK和typed评分guard：legacy仍市场null，新rubric必须绑定v2任务／精确配置／来源／修订／执行，允许市场0～5并核总分。无新表列、无新增权限，不改旧表数据；下调已有v3记录时拒绝，避免破坏真实推断评分。迁移先隔离升降级和受限角色测试，再部署。

- [x] M1 后端：score_model保留legacy验证／prompt、新inferred验证／prompt；scoring Score默认v2、LegacyScore处理v1；contracts增加量表与market_basis派生；0032与manifest、metadata CHECK、纯／PG／错绑测试。
- [x] M2 前端：strictparse两量表及market_basis，市场推断紧凑标签，数值/总分沿用条形；legacy空值保留；Demo相应标识、前端测试与同步。
- [x] M3 Root：worker/registry双版本集成、契约类型、隔离与受限角色验证、0032升级且无额外授权、通过控制台现有配置对《市井隐锋》同版显式重评1次；旧评分不改写、旧11卡／榜单保持。
- [x] M4 独立审阅和实屏核验，更新AGENTS、模块、研发计划、字典与技术文档；保留旧验收为历史，最新口径覆盖市场强制未知规则。不Git提交／推送。

文件归属：后端代理仅topics/score_model.py、scoring.py、score_contracts.py、0032/core.models CHECK/manifest及后端测试；前端代理仅topics/contracts.ts、ScorePanel.tsx、前端测试与Demo；Root负责worker/registry、main/契约生成、迁移安装与实际验证／文档。新模型调用最多1次评分，不做全量11卡重评、不重跑生成。

Final verification: [verification.md](verification.md).
