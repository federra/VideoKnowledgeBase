# 多作品评论批量分析实施计划

> For agentic workers: use subagent-driven-development for two independent backend/client units; root owns integration, real operation and evidence.

目标：用户明确要求只分析10月31日已抓取数据，以两部或多部作品的结构化整体一次调用提高效率。当前可见90部／1048评论，已成功2部／20评论，待88部／1028评论。30日不再新提交。此前两日协调器已停止，旧31日零外调排队任务取消；已发出的任务与调用保留，不改历史。

设计决策：audience.feedback/v3每批2～3部，同业务、日期、snapshot、精确feedback模型配置；每部现有评论完整打包（≤20），组内≤60。一个任务、一次模型调用，返回items[{entry_id,result:原Output}]；严格精确目标集合／逐部覆盖／引用不可跨作品。一次成功后每部独立feedback_snapshot，共用真实AIExecution；0035给feedback_snapshots增加nullable entry_id和合适唯一性／FK，v1/v2保持null及原一任务一反馈规则。新增typed v3守卫确保一执行／n结果／正确引用与任务输出闭环，无新表／数据库GRANT。批次任一非法时不伪造补全；失败原样留档，不自动拆组重试。

读取兼容v2/v3，canonical/raw/file继承整批全部来源限制，ReadAuthorizer仍只请求内缓存。旧单部按钮不能与活动／成功批次重复发起；旧成功不重跑，旧失败／取消只有显式retry_of纳入新请求。getFeedbackAnalysis增加可选entry_id查询，按所需作品返回原FeedbackAnalysisView，前端轮询传自身entry_id；不新增页面或批量按钮。CLI可显式start_batch，原feedback专队列注册v2/v3；不复用采集能力，不读浏览器。

- [ ] Backend：新feedback_v3策略与服务／批次输入及幂等、发布、读取与权限继承；0035模型及SQL、专队列注册；RED/GREEN纯测试、隔离／受限PG升降级，v2完整回归。禁止项目迁移、模型、采集、实际扩权和Git。
- [ ] Frontend：仅getFeedbackAnalysis可选entry_id契约及client调用／轮询隔离，相关测试；不改UI/Demo呈现，不发真实请求。
- [ ] Root：旧任务状态／失败诊断、类型生成、集成与独立审阅、受保护安装；冻结31日仅待分析88部清单，按相同snapshot每组2～3部（不足组剩1部可单例），每批一次、整部评论，不自动重试；真实结果及预算／原文／历史指纹核验、文档索引。

风险与验收：同task多结果的旧唯一约束；旧v2 SQL计数不得误伤v3；共享AI文件不能泄漏另部不可读评论；配置／来源／日期变化拒绝；失败批次无半成品／额外调用；同样本在单部与批量互斥；GET必须精确entry，不把首部回执发给其他作品。以源码证据、mock隔离与有限实测逐步放行。

2026-10-31用户明确暂停：后台活动0。工程已完成并安装0035，首组3部／15评论一次调用校验失败，0新报告，剩余仍88部／1028评论。禁止自动恢复，提示词澄清还未完成新验证／部署，详见[暂停交接](暂停交接.md)。
