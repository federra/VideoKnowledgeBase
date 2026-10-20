# TikHub抖音评论能力核验

版本：v0.1｜日期：2026-10-17｜状态：单作品一次真实调用通过。

用户指定[TikHub市场接口](https://user.tikhub.io/dashboard/api-marketplace/%2Fapi%2Fv1%2Fdouyin%2Fapp%2Fv3%2Ffetch_video_comments)，取代JustOneAPI。核对[官方接口文档](https://docs.tikhub.io/186826225e0)及[官方OpenAPI](https://api.tikhub.io/openapi.json)：GET `/api/v1/douyin/app/v3/fetch_video_comments`，固定主机`https://api.tikhub.io`，Bearer鉴权，密钥仅后端读取.env的`TIKHUB_API_KEY`。

本轮仅对已有作品7687517065535605369请求一次，`cursor=0,count=20`；无翻页、无自动重试、未采回复。返回20条有效原文，原始响应保存为不可变raw_asset，原文ID、作品ID、点赞、Unix秒及采集时昵称已规范化。真实响应字段为`code=200,data.status_code=0,data.comments[]`，评论字段`cid,aweme_id,text,digg_count,create_time,user.nickname`。公开OpenAPI未定义完整data内层；以上内层映射来自本次真实证据，不冒充公开契约。原响应其他用户资料／平台token不进入模型白名单或公开日志。

原视频作品快照评论数2338与本次响应total2340属于不同时刻；不覆盖旧快照，也不把20条样本视作全量。has_more=1已保留，未继续采集。采集来源执行后暂停，Worker／Beat未启动。

[采集结果](verification/2026-10-17/s064-tikhub-live-summary.json)、[规范化](verification/2026-10-17/s064-live-normalization.json)、[模型封存](verification/2026-10-17/s064-live-feedback-result.json)、[零外部调用洞察](verification/2026-10-17/s064-live-insight-result.json)。模型仅收到评论ID／正文／点赞／时间，不含昵称和用户ID。DeepSeek调用1次，20条有效样本中6条有情绪证据；标签可重叠。

[TikHub价格页](https://tikhub.io/pricing)不能证明该端点本次实际扣费额；实际账单金额未核验，系统不填估算费用。不得为核对价格再次采样。
