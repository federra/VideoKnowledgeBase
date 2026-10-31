# 市场承重AI推断评分验收

日期：2026-10-31。用户明确要求市场承重五维根据AI自身推断评分；本记录覆盖此前“缺独立市场证据则市场五项强制null”的新评分口径，旧评分事实保留。[计划](plan.md)／[长期技术](../../technical/选题素材抽象与版本评分.md)。

## 一、最终行为

新提交使用topic.score/v2、genre-load-v3-inferred，市场五项结合创作定位、文本和常识推断，保存理由及不确定性，不因缺实测数据强制空值。十维各0～5严格整数；确实无法判断才null，相应小计／总计保留未知。内容25、市场25、总50由服务端计算，无新增合格线。市场组沿用Demo紧凑布局并标“市场：AI推断”，不展开分析长文。推断不得冒充用户统计、CPI实测、收益或平台验证。

API的market_basis按量表服务端派生：新量表ai_inference，旧量表unavailable，不接受模型自报为实测。原topic.score/v1仍由LegacyScore执行旧prompt／验证，旧市场五项null；新旧handler、冻结量表及数据库守卫必须匹配，不允许相互借用。

0032_market_inference已安装，仅修改评分量表CHECK及typed守卫，无新增表列、GRANT或修改旧评分。空库head→0031→head通过，存在v3事实时拒绝降级，避免不可变记录丢失。现有控制台topic_score绑定保持，Deepseek／deepseek-flash；max_tokens空值继续省略，无自动模型重试。

## 二、真实验收

对《市井隐锋：一锅汤牵出的旧案合谋》原v1显式评分一次：topic `58c076f9-d0ab-4cdb-a81b-5d262448ebcb`，revision `c85f3c00-e1f8-4a60-a515-563bd0077947`，task `94cc900a-89ec-43de-bea8-bdb1ee124020`，assessment `78c67709-561c-40f1-a469-055ac7e1bd2b`。任务succeeded，实际1次模型调用；本轮未生成新卡、不重跑之前生成及评分。

内容维度4／4／3／3／3＝17/25；市场维度用户基数、平台调性、投流潜力、复购预期、竞品差异均3＝15/25；总分32/50。此为AI推断评分，不是实际市场表现或付费投放预测。旧assessment `e6d5cf8a-310f-4ac8-987b-8fb33d743bd4`仍原18/25、市场及总分null；新调用重新评价全部十维，内容分与旧值差1分，未编辑原题目。

首次worker claim在领取前遇到组织advisory锁超时，任务仍queued且AIExecution为0。确认后只重投同一个任务，未创建新任务、未重复模型调用；最终调用总数由6增至7。此处是本地并发事务等待，未修改数据库锁保护或模型重试策略。

旧30,424榜单成员SHA `13ac112352f0dc8f7d0a21323a7a8874679fec68d86d1b9687e4d0430794081b`、11卡正文／来源／当前修订SHA `2c11631b0165add4d8343fd07762d8d93df8ee66ef0660f35239983c9c72e389`、旧评分SHA `71a38d513f8132fb73c4538520856e3336607c8efb9cc40a03b54a4db32598da`均前后相同。最终活动任务0。私有安全回执位于data/runtime/market-inference-2026-10-31/{before,install-result,real-evidence}.json，不含密钥；真实响应依据仍按既有私有文件／不可变事实留档。

![真实十维评分](../../technical/verification/2026-10-31/market-inference/real-inferred-score.png)

## 三、验证与边界

481普通后端通过（346环境集成项按默认跳过），另50隔离PG、39受限角色PG通过；186前端通过。新增registry回归先RED后GREEN，覆盖v1/v2派发；纯验证与PG覆盖严格整数、合计、null、错绑、同修订重评及旧事实不变，前端覆盖AI推断标识、旧量表及Demo。类型／lint、构建、OpenAPI与生成类型校验、Demo检查均通过，Demo基线e8be8f68348d。构建仍提示已有bundle超过500kB；不影响本评分链路，本轮未做包拆分。

独立审阅无未解决Important／Critical。已实屏确认卡片32/50、详情内容17/25、市场15/25、AI推断标识及十条评分条。无新增采集、权限、Git提交或推送。故事短片量表仍待定义，观众反馈AI情绪分析属于下一项独立工作，不以本轮选题评分完成代替。
