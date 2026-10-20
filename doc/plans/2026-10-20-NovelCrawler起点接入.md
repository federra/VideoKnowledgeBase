# NovelCrawler起点接入

用户授权：完成作品标签修正后，仅调整起点数据，参考https://github.com/laujjxx/NovelCrawler；每榜最多30项，成功方法及资料须落文档。番茄现有接口、参数、任务、原始数据不改，不重新采集。

已验证：固定移动Safari公开请求，https://m.qidian.com/rank/yuepiao HTTP200，pageContext.pageProps.pageData.records含20条真实榜项。官方男频目录/rank/ HTTP200，实际发现9类（月票、畅销、阅读、书友、推荐、更新、签约、新书、新人），不同于参考项目旧6类枚举；目录链接女频https://m.qdmm.com/rank/，实测202无业务数据。只据当前官方目录发现，不猜旧shoucang/changxiao等别名，不用榜单预览或搜索摘要替代完整榜项。

实现：独立QidianMobile连接器／QidianCollect和显式CLI，复用现有collect.novels任务、一次预算、原始响应、不可变快照、来源暂停；不改番茄连接器。目录仅留证不发榜；每个可访问榜型仅第一页，最多30，不翻页重试，女频失败明确受限。单来源参考NovelCrawler的内嵌JSON解析，固定官方移动域名，保持TLS，无代理／登录／验证码绕过。月票／排行值独立保存，不计作在读人数。

作品题材取book.cat，并以同份官方filters.catId目录校验；作品男女频字段缺失仍null，不把页面/榜单gender当作品标签。各平台题材目录独立验证，不能让新起点“都市”分类补回番茄4条宽泛“都市”。只在起点新增分类过滤与榜型名称，旧番茄筛选语义不变。旧失败证据保留，页面优先本轮移动方法状态。

步骤：RED解析／固定域名预算／权限与跨平台分类测试 → 实现与生成契约 → Qidian-only正式一次批次、全部来源暂停 → 页面／普通与PG回归 → 一次独立审阅及必要修复 → 技术文档／AGENTS索引／逐榜证据回填。完整首期及全部女频受限部分不因男频通过而勾选。

## 执行与验收

已完成：独立连接器／处理器／显式CLI、中文榜型、每平台与同响应作品分类、部分来源受限展示、生成契约及用户页面；不改番茄采集。正式11次公开请求：男频目录200、女频目录202、男频9榜各200，均第一页20条，共180条榜单成员／118个独立作品。前置另3次公开探针，未重复算入库；付费／模型／番茄请求均0。11份原始响应SHA一致，11新来源全部暂停；番茄9表前后指纹一致，2,213本保持，两平台当日去重数2,331。

一次独立只读终审：无Critical、1 Important（其他响应分类目录借用）和1 Minor（超限／解码／中途网络失败丢失已收证据）；两项均完成RED→GREEN修复。作品只用本条不可变meta.taxonomy校验，平台并集仅供筛选选项；增加同一平台两份不同分类目录回归。失败读取保留3MiB有界已收正文，截断／中断明确标记，非法UTF-8以base64留证，保留HTTP失败状态；不能把有正文记成空响应。异常证据SHA针对保存的文本表示，不冒称完整线缆字节哈希。没有为修复重新请求平台或重写业务快照。

验证：最终`bash scripts/check.sh`通过，225普通后端／87前端、静态检查、契约生成漂移、Demo基线85e09ee05552和生产构建通过；9项起点单测。完整PG／Redis217项及空库／存量升级、回退重建通过（在终审修复前）；修复后再跑4项起点／标签PG专项通过。未再次重跑全部PG，最终针对变更复验；构建大包及Starlette弃用提示为已知非失败提示。保持无HEAD本地仓库现状，不做全量初始提交、清理或PR。

实屏：AI漫剧／2026-10-20／小说／起点中文网，9类榜名、118本、作品题材与未获取指标均正确；月票榜20本，叠加都市3本，保留原榜5／7／15名。页面已停留起点全榜，概览2,331为两平台总数；不随局部筛选变化。作品男女频缺失仍—，页级男频只属榜单条件；女频202单独提示部分受限。男频9类默认全站第一页通过，女频与全部题材／日期子榜仍未完成，不勾S08整体。

证据：[真实批次与指纹](../technical/verification/2026-10-20/qidian-mobile-live-acceptance.json)、[实屏](../technical/verification/2026-10-20/qidian-mobile-real.png)、[最终综合检查](../technical/verification/2026-10-20/qidian-final-check.txt)、[完整PG](../technical/verification/2026-10-20/qidian-postgresql-full.txt)、[审阅PG红](../technical/verification/2026-10-20/qidian-review-postgresql-red.txt)／[绿](../technical/verification/2026-10-20/qidian-review-postgresql-green.txt)、[留证单测红](../technical/verification/2026-10-20/qidian-review-unit-red.txt)／[绿](../technical/verification/2026-10-20/qidian-review-unit-green.txt)。探针三份JSON位于同目录qidian-novelcrawler-probe／qidian-mobile-directory-probe／qidian-female-directory-probe，原始HTTP正文与正式收据在忽略的data/qidian中保留。

持续方法与参考资料入口：[小说榜单接入第五节](../technical/小说榜单接入.md)；字段、模块、技术方案、本地运行、实施总表和AGENTS索引已同步。下一步先人工检查起点真实榜单及简介交接；女频需待官方可访问目录或用户另给数据来源后补，不影响番茄现有链路。
