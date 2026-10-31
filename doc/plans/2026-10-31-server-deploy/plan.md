# Git同步与服务器部署计划

用户明确授权：一次Git提交同步GitHub；服务器部署无登录密码；Git不携带业务数据，服务器同时复制当前本地榜单／知识库等已有数据。评论批量任务保持暂停，不因部署自动恢复。

- [ ] 本地：代码／模板／文档提交，排除.env、数据库、原文、导出、运行目录及本轮数据验收截图；真实密钥内容扫描，测试／构建／契约／Demo核验，main单次提交并核对GitHub SHA。
- [ ] 应用：显式PASSWORDLESS_ACCESS，精确允许真实HTTPS origin，共享原工作区、保留CSRF／内部权限；默认关闭，本地规则保持。前端Vite BASE_URL支持/vkb/与根路径，API/cookie反代前缀一致。
- [ ] 服务器：Ubuntu24.04已有多应用，使用/opt/video-knowledge-base独立目录与cip-vkb系统用户；独立数据库和Redis实例、API仅loopback18090。现有IP HTTPS站点仅追加/vkb/入口，保留原站点所有路径。
- [ ] 数据：本地PostgreSQL一致性导出（不含角色凭据）、私有files快照，分别SSH传输，服务启用前核验版本、核心表计数与文件SHA；不搬独立浏览器Cookie／Profile或运行日志。保存原本地数据，不删除或改写远端其他库。
- [ ] 发布：API／worker／Beat独立systemd服务、暂停来源与模型批次状态保留；真实外部HTTPS空会话访问、业务读取、文件与匿名共享模式核验；报告网址、SHA、迁移数量及浏览器采集会话待配限制。

服务器连接密码仅从本地.env读取，应用运行.env排除DEPLOY_*；数据库／Redis使用独立随机服务凭据，运行角色受限；Nginx保留真实Host并覆盖转发scheme，Uvicorn只信任loopback代理。现有IP证书与续期机制复用，不覆盖其他站点或开放其他数据库端口。恢复与回滚保留快照、release目录及配置备份。
