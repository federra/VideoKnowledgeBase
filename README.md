# 内容智库

内容智能服务系统，提供情报、知识、评价与复盘，覆盖AI漫剧、故事短片、电商短视频。产品及研发纪律见 [AGENTS.md](AGENTS.md)。

当前已接真实控制台采集配置／运行状态及情报流，其余12个工作区仍保留Demo适配层。后端已接采集、任务、文件与权限服务，项目库为0009_collection_lock／74表；AI与评论洞察、研判链路按后续阶段继续。按用户决定，本地`.env`设置`LOCAL_SINGLE_USER=true`，直接打开页面即可进入本地工作区，无需手动登录；默认配置仍关闭该模式。说明见[情报快照与本地工作区](doc/technical/情报快照与本地工作区.md)。

## 本地启动

已核验 Node 26.7.0、pnpm 11.24.0、Python 3.12.14、uv 0.12.7。建议使用相同版本；依赖分别锁定在 `pnpm-lock.yaml`、`backend/uv.lock`。

```bash
pnpm install --frozen-lockfile
pnpm dev
```

访问 [前端](http://127.0.0.1:5173) 或 [内容研判](http://127.0.0.1:5173/#2/0)。真实情报和控制台需要后端及数据库运行；其他页面仍可对照Demo。

后端另开终端：

```bash
cd backend
uv sync --frozen
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

[健康检查](http://127.0.0.1:8000/api/health) · [OpenAPI文档](http://127.0.0.1:8000/docs)。Vite将 `/api` 代理至8000端口，真实请求失败不会回退演示数据。

本地数据库和Redis使用独立Colima profile及15432／16379端口。启动engine后运行 `pnpm infra up`；`pnpm infra check`检查真实依赖连接，`pnpm infra stop`仅停止容器并保留卷。首次私有配置用 `pnpm infra init` 创建，不覆盖已有.env。完整启动／重启验收说明见[本地开发说明](doc/technical/本地开发说明.md)。

红狐单次来源探测用 `pnpm probe:redfox --dry-run` 查看计划；配置私有.env的REDFOX_API_KEY后才可显式执行 `pnpm probe:redfox`。本轮关键词为“漫剧”，最多1次请求、无自动重试／分页；已有调用记录拒绝意外重复，来源覆盖与实测结果见[采集清单](doc/technical/采集能力与样本清单.md)。

## 验证与目录

```bash
pnpm demo:check
pnpm check
pnpm test
pnpm build
cd backend
uv run ruff check .
uv run pytest -q
```

`frontend/src/app` 为React导航壳与路由；`modules` 为四模块工作区入口；`components` 为共用组件；`api` 为真实请求层；`demo` 为可移除的原型适配层；`styles` 沿用Demo CSS。`backend/app` 按技术方案保留API、业务模块、连接器、处理、AI、任务、存储和核心配置目录；`migrations` 已有6次冻结迁移及74表（B1业务70表＋公共服务4表）；`infra` 是已验收的专用本地依赖配置；`data` 不提交运行数据。

详细边界、路由、演示存储与后续接入步骤见 [本地开发说明](doc/technical/本地开发说明.md)。原Demo保留在 [doc/prototypes/index.html](doc/prototypes/index.html)，不随工程运行自动修改或同步。

S04数据库命令：`pnpm db:status`、`pnpm db:test`（临时隔离库）、`pnpm db:upgrade`、`pnpm db:app-role`、`pnpm db:audit`。角色／凭据边界、字段映射、存量升级与恢复说明见[数据库迁移与恢复](doc/technical/数据库迁移与恢复.md)；当前仅4条代码配置，业务路由及前端真实数据分阶段接入。

S05.1已建立[首条链路接口契约](doc/technical/接口契约.md)：`pnpm api:generate`生成运行／设计OpenAPI及前端类型，`pnpm api:check`只读检查漂移，工程检查会执行该命令。工具工作区tools/contracts独立锁定TypeScript5，前端保留TypeScript6。40项操作中3个session及3个文件已实现、其余34项为设计态，运行API含health、session及文件；S05.5前端客户端已接会话／文件，业务页面仍未消费真实数据。

S05.2新增真实会话接口、受控开户与公共权限／审计、持久幂等回执，项目库升级0005_auth（73表），无默认账号或新增业务数据；入口见[登录权限与审计](doc/technical/登录权限与审计.md)。Demo页面暂不变，文件流及前端请求联通分别为S05.3／S05.5。

S05.3文件上传、实时授权下载、可信HTTPS抓取及journal恢复已完成；命令、限制和增量字段见[文件存储与访问](doc/technical/文件存储与访问.md)。文件主机白名单默认空，未接前端页面；不要以接收成功代替可解析／可研判。

S05.4：Celery／Redis／Beat与数据库持久任务、有限重试、租约续期、取消和中断恢复已接通，0007_tasks不增表（仍74表）。运行`pnpm worker`与`pnpm beat`，受控CLI用`pnpm tasks`；真实采集／AI处理器及前端仍按后续阶段接入，见[任务队列与调度](doc/technical/任务队列与调度.md)。

S05.5：已有会话／文件服务接入生成类型的前端客户端与Query Provider，统一空态、失败、拒权、取消及缓存边界；`pnpm api:test`另跑真实TS／HTTP／受限PG文件链路。原业务页面保持Demo，真实页面从S06迁移。见[前端请求与反馈](doc/technical/前端请求与反馈.md)。

S06.1采集后端已接固定红狐账号发现与广域库作品元数据，受控命令`pnpm collection --help`，预算与证据规则见[采集连接器与证据](doc/technical/采集连接器与证据.md)。本轮新增付费调用0，控制台已在S06.2接入，真实情报页已在S06.3接入。

S06.2控制台采集配置及运行状态、S06.3真实情报流已接服务；[直接检查方法](doc/technical/情报快照与本地工作区.md)提供本地免手动登录、日期、指标与权限口径。新来源默认暂停，不启用采集或填入演示数据。历史缺失显示空态，未知指标显示未获取；当前供应商无榜单／评论／洞察能力，后续按S06.4接入。

已按用户授权调用红狐一次，保存10条“漫剧”关键词作品；在情报流选择AI漫剧／2026-10-17／达人查看，搜索结果不当榜单。来源已暂停，详情见[真实填充记录](doc/plans/2026-10-17-漫剧关键词真实填充.md)。
