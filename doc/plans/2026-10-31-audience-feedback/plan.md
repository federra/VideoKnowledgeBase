# 观众反馈AI情绪判定与分析实施计划

用户已授权继续落实已有观众反馈功能，并回复已在控制台配置模型。本轮复用已采集评论，不重新采集、不重跑选题或题材解释。首轮真实验收最多3部作品／每部≤20评论、每部1次模型调用，失败不自动重试。

## 一、方案与边界

沿用现有反馈抽屉及封存反馈／评论／claim／原文引用表，以audience.feedback/v2统一接通红果、博主首集、微电影以及旧抖音评论来源。采用控制台当前业务feedback环节与统一文本适配器，不直接读取密钥作业务回退，不自动配置或借用其他环节。保留v1任务及历史结果，不修改已有封存事实。GET只读，POST显式授权执行；同样本／配置的重复提交复用任务，失败仅允许显式重试并保存旧失败。

每条评论须得到情感倾向（正面／负面／中性／混合／无法判断）及具体情绪／触发依据，允许多情绪但同评论倾向一致；无法判断不计入已分类分母。归纳受欢迎点／问题点、明确期待与推测、反馈→调整→验证建议，均绑定输入comment_ids。服务器计算支持数与比例，不接受模型捏造统计。无关或不足样本保留原文，不强凑市场结论。

冻结业务日期、平台、作品、entry／snapshot／样本原包与评论ID、精确模型配置；提交、执行、发布和读取重检权限、来源及同日版本。保留博主首集／红果播放页跨集未验证／微电影首屏采样限制。新采集样本不得沿用旧样本分析，不跨业务／日期／作品回退；通用raw与模型输入／输出文件也遵守全部来源撤回与失效边界。新约束优先复用原表，不扩大应用权限。

## 二、实施分工与检查

- [x] 后端代理：app/ai/feedback_v2.py与intelligence/feedback_v2.py，canonical多来源样本／v2模型校验／任务冻结及持久化；改现反馈early return及正确latest投影；必要0034 typed迁移、来源权限继承与请求内批量读取；纯／隔离PG／受限角色回归。
- [x] Root：contracts/models.py新增FeedbackAnalysisView／AnalyzeFeedbackRequest及EntryFeedback兼容字段，contracts/api.py与intelligence/http.py挂载显式POST／任务GET；专用feedback队列worker与路由，契约生成、有限实测、服务启动与证据／索引。
- [x] 前端代理：FeedbackDrawer、APIclient严格校验／调用、现有抽屉内按钮与状态，caller-owned幂等／响应未知恢复／轮询与关闭隔离，新增情感倾向及无法判断显示；Demo同步与前端测试。
- [x] 整体：隔离迁移升降级、普通后端与前端／契约构建、独立审阅、原数据指纹保护、最多3次真实调用和实际前端结果验证，更新AGENTS／字典／技术说明／清单。

API：POST `/intelligence/entries/{entry_id}/feedback/analyze` body `{business_code,business_date,expected_sample_key,retry_of?}`，202返回FeedbackAnalysisView；GET `/intelligence/feedback-analyses/{analysis_id}`。EntryFeedback保持not_acquired／sampled／ready，新增sample_key、analysis_model_ready、analysis及summary；旧响应字段兼容。View包括id、entry_id、snapshot_id、business/date、sample_key、task state、result_state、safe_error_code及feedback_id。

## 三、验收重点

不重复付费、无配零调用、失败保留及显式重试；引用、分母及无法判断；旧v1不变；三来源当前真实证据及日期、来源撤回／权限到期／样本更新、迟到／失租约；raw/file旁路与页面读取性能；关闭／切业务日期不得串结果。历史大脏基线保留，当前工作区开发，不提交／推送Git。研判室入口继续隐藏，不借本轮扩展生产或知识发布流程。

实际3部／3次调用成功，历史指纹不变、零采集；14受限PG、497普通后端／225前端通过，独立复核已关闭问题。完整结果及限制见[实施验收](verification.md)。
