# Just One API 抖音评论能力核验

2026-10-17最新决定：用户改用TikHub，本候选未调用、不再等待token；实际接入见[TikHub核验](TikHub评论能力核验.md)。下文保留历史核验。

版本：v0.1｜日期：2026-10-17｜结论：文档层面适用，字段／价格及真实可用性待实测。本轮未调用该付费接口。

[接口文档](https://docs.justoneapi.com/zh/api/douyin-tiktok-china/video-comments-v1)定义按视频awemeId读取顶层评论的GET接口，page从1开始，token放查询参数；没有pageSize或排序参数，不能承诺恰好20条、热评排序或全量评论。楼中楼另有接口。

[OpenAPI](https://docs.justoneapi.com/openapi/douyin-tiktok-china/video-comments-v1-zh.json)只定义包装层，成功业务码0，data未定义结构；正文、评论ID、用户名、点赞及发布时间字段名均待真实响应核验。本次未取得动态响应示例。接口页未列具体单价，需账号价格与权限确认。

项目已有抖音作品ID，可作为awemeId候选，无需重搜作品。建议首次只选现有评论较多的一条作品、page=1、一次请求，不翻页／不抓回复／不自动重试；真实采集原包保存，再取最多20条有效去重原文进入一次DeepSeek分析。若第一页不足，只按实际数量处理；不能以减少入库条数推断API费用减少。

接入前还需本服务token及价格确认，建议配置名JUSTONEAPI_TOKEN（仅建议，当前未实现）；红狐和DeepSeek密钥不能复用。token不得进入浏览器、错误URL、任务safe_request或日志；网络错误只输出安全码。当前只是候选核验，不创建连接器、来源、计划或扣费调用。

日期采用本次捕获时间，不把今日抓取评论回填为过去日期的历史反馈。若实际调用跨日，须绑定当日情报快照。字典当前无评论用户名列，真实映射前须补字段设计与新迁移，不把用户名藏入不明JSON；不能据本页文档先猜字段完成连接器。
