# 本地用户系统 Implementation Plan

> **For agentic workers:** 使用测试先行；账号服务、个人数据隔离与界面按以下明确接口分工，最后整体验收及独立审阅。

**Goal:** 本地真实多用户登录、管理员控制台及个人空间隔离。
**Architecture:** 复用组织成员会话与授权；新增一次性安装绑定；个人归属沿既有created_by／owner_member_id，管理员显式只读。
**Tech Stack:** FastAPI／SQLAlchemy／PostgreSQL、React／TypeScript、现有契约生成与Demo。
**Spec:** doc/plans/2026-11-01-user-spaces/design.md

## Global Constraints
- 本轮仅本地，不部署、不推送；保留4份历史验收文件及全部业务数据；无采集和AI调用。
- USER_ACCOUNTS_ENABLED默认false；为true时免登录自动身份完全禁用。
- 管理员有效org范围member.manage；查看他人只读，普通用户不可进入控制台API。
- 新密码8～1024字符，密码不进入日志／localStorage／回执正文；最后有效管理员保护。
- 原公共数据共享、原个人数据归原账号；跨用户详情／任务／原包／文件不可漏读。

## Review Focus
- 多标签页退出／换人时在途请求、个人草稿和缓存不能回流。
- 普通用户猜测他人topic／spark／task／file的ID不得泄漏正文或数量。
- 一次性初始化并发／重复访问不得接管已初始化管理员。
- 最后一名管理员并发降权／停用保护及旧会话立即失效。
- 管理员查看他人原文不能隐式获得写入或付费执行能力。

## Task 1：账号服务
**Files:** backend/app/accounts/*，security/http.py／config.py／main.py，迁移0036与core/models.py，tests/integration/test_user_accounts.py。
**Interfaces:** GET /api/v1/access -> {enabled:boolean,setup_required:boolean,org_id:UUID|null}; POST /access/setup {login_name,display_name,password} -> Session并Cookie（受控本地初始化）；POST /access/register {email,password,display_name?} -> 普通用户Session；既有POST /session登录。GET /users -> {items:User[]}; POST /users {login_name,display_name,password,role:'administrator'|'user'} -> User；PATCH /users/{member_id} {expected_version:string,display_name?:string,role?:...,enabled?:boolean,password?:string} -> User。User={id,login_name,display_name,role,enabled,lock_version:string,created_at}。用户设置支持幂等键。helper app.accounts.policy.is_administrator(c,p) -> bool及require_administrator(c,p)。users仅管理员。
- [x] RED测试初始化单次、未知账号、创建／改名／角色／密码、末位管理员保护、禁用即时失效及普通用户配置拒绝。
- [x] 实现迁移、契约、服务／HTTP；不执行项目库变更、不改.env（由主执行者统一备份和安装）。
- [x] GREEN专项与普通后端相关测试，记录证据。

## Task 2：个人数据安全
**Files:** topics/service.py／generation.py／scoring.py、security/authorization.py／read_authorizer.py及相关tests。
**Interfaces:** Task1 helper；原topics／sparks默认永远本人，管理员新增GET /users/{member_id}/space?business_code=... -> {member:User, sparks:SparkView[], topics:TopicView[]}，只读无执行；由个人安全任务实现该接口及契约。管理员可只读topic详情但所有写、评分、导出仍要求created_by本人。原公共知识与榜单读取不变。
- [x] RED两普通成员与一管理员，列表计数、详情／写入／任务／文件越权、管理员只读与撤权边界。
- [x] 最小归属过滤与派生来源闭包；个人文件／任务不能因组织级读取Grant泄漏，其他公共对象保持。
- [x] GREEN真实隔离PG及普通后端测试，更新接口依赖说明。

## Task 3：页面与Demo
**Files:** frontend/src/modules/accounts/*、App／Navigation／api，doc/prototypes/index.html及生成物、frontend/tests/user-accounts.test.tsx。
**Interfaces:** 使用Task1／2响应，复用ApiClient.login/logout/get/json及身份边界。
- [x] RED邮箱注册／登录／退出、普通用户控制台隐藏及直达阻断、管理员用户CRUD、只读用户空间与跨用户缓存清理。
- [x] 实现登录壳、用户入口、用户管理与用户空间抽屉；个人页面仍原布局，公共列表不复制；Demo同步。
- [x] GREEN前端全套、check／build／demo:check／api:check。

## Task 4：本地安装与整体验收
- [x] 本地数据库备份，隔离还原升级与受限角色测试，必要新表精确最小权限，项目升级后核对历史指纹；只改本地.env开关。
- [x] 本地重启；验证指定管理员登录及注册入口，隔离真实账户测试不污染业务数据；实屏验证并记录。
- [x] 独立审阅、修复阻塞项，回填AGENTS／权限与模块技术文档／本计划。管理员按指定邮箱及初始密码登录；普通用户可自助注册。

最终验收见verification.md：本地0036及指定管理员初始化完成，269前端、531普通后端和相关真实PG通过；保留完整PG首轮结果与4项定向复验边界。无Git提交、推送或服务器部署。
