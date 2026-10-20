# S07.5 一次独立审阅与修复

审阅者：s075_final_review；只读审阅，无外部调用或项目数据写入。3项Important，无已证实Critical或新增Minor。

1. 未标集资料已有材料版本但原文链接要求episode_no。复现UI测试null集号找不到链接；修复为既有episodes/unknown/{version}路径。
2. 共享知识从另一业务进入来源作品时缺少业务上下文。新增来源business_code安全投影，链接携带source_business，App切换已有顶部业务并恢复确切版本／段落路径。UI链接测试缺参数与App业务不切换均先失败，后通过；真实现有作品跨业务直链已核验。
3. 游标签名直接拼接字段，stage:a+bc和stage:ab+c可碰撞。新增规范JSON摘要filter_scope；旧游标不能在另一组筛选下使用。回归测试先失败后通过。

没有第二次审阅。最终79前端／201普通后端／209完整PG通过。S07.4旧审核意见显示优先级Minor沿原决定后置，不在本项扩展；真实向量生成、语义质量和移动性能未验收。
