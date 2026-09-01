# 对外产品化计划（Productization Plan）

> 目标：把当前「功能完备的后端 + 管理后台可用的演示平台」推进为可对外交付的产品。
> 本文档是差距分析与分阶段路线，落地按 Phase 顺序执行；每一阶段有明确验收标准。

> 面向客户/交付的文档入口：`docs/customer/`（快速开始 / 部署 / 管理员 / 集成 / 故障排查 / 安全），套餐边界见 `docs/commercial/pricing.md`。
> 更细的执行拆解请看 `productization-roadmap.md`；当前功能优化清单请看 `feature-optimization-plan.md`。

## 执行进度

- [x] **Phase 0 · 安全门禁**（2026-08-23 完成）
- [x] **Phase 1 · 认证与用户管理**（2026-08-23 完成）
  - [x] 用户管理 API（CRUD / 密码 / 禁用）+ 前端用户页
  - [x] 认证收紧：未知/禁用用户拒签、`must_change_password` 首登强制改密
  - [x] 租户管理 API（onboarding / 初始管理员 / 默认策略）+ 前端
  - [x] 密钥持久化（SecretManager → Fernet 加密落库，重启不丢）+ 前端
- [ ] **Phase 2 · 运行时真实化**（进行中）
  - [x] PostgreSQL + pgvector 全链路验证（app 以 PG 启动/登录/种子数据）
  - [x] alembic 迁移链修复（补齐 `users.password_hash`、`policies.user_id/role_id` 等模型漂移）
  - [x] Redis 接入验证（限流/锁/取消，redis URL 启动无错）
  - [x] docker-compose 增加 app 服务 + 多阶段 Dockerfile + prod 安全门禁配置
  - [x] 真实 LLM 链：dev 已在用真实模型（qwen），openai provider + 密钥注入可用
  - [ ] HTTPS/TLS 反代（部署层，留给实际部署）
- [ ] **Phase 3 · 安全加固**（进行中）
  - [x] 攻击面审计（子代理）：沙箱逃逸、SSRF TOCTOU、认证回落、env 泄漏、上传 IDOR
  - [x] 沙箱加固：封禁 `os.spawn*/os.system/subprocess/os.open`、不再泄漏宿主 env
  - [x] SSRF TOCTOU：http.get 单次解析 + 固定已验证 IP（http.client，SNI 用原域名）
  - [x] 上传会话跨租户 IDOR：`upload_sessions.tenant_id` + 租户过滤（含迁移 0010）
  - [x] 租户配额核实：并发 run / LLM 租户限流 / 工具限流 tenant:user:tool / 预算均已存在
  - [ ] 沙箱完整容器化（gVisor/Docker 隔离）——部署层大改，暂留
- [ ] **Phase 4 · 前端体验**（进行中）
  - [x] Route-level 分包：主 bundle 2.8MB → 594KB（gzip 199KB），重依赖（CodeMirror/Graph）按需加载
  - [x] index.html 启动 splash：React 挂载前展示品牌占位，缓解刷新空白/闪乱
  - [x] 骨架屏：`TableSkeleton`（微光动画）替换表格加载态（Policies/Users/Approvals/Queue/Events）
  - [x] 403 页：`PermissionDenied` 组件，权限不足的页面显示专属无权限态
  - [x] HTTPS 反代：Caddy 服务（docker-compose）+ Caddyfile（域名自动 Let's Encrypt）
  - [x] 沙箱容器化：`sandbox_docker` 可配 Docker `--network none` 执行（dev 默认子进程回退）

Phase 0-4 全部核心项已完成；剩余为部署/打磨（真实域名 TLS、骨架屏铺到全部页、沙箱 gVisor）。

## 对话产品化（2026-08-24 增补）

- [x] 会话持久化 + 列表/加载/重命名/删除（`messages` 表 + `sessions.title`，迁移 0011）
- [x] Markdown 渲染（react-markdown + GFM）、工具调用折叠、停止生成、重新生成
- [x] 快捷指令、导出对话
- [x] Token 级流式：openai provider `stream:true`，答案逐 token 推送（`token` SSE 事件）
- [x] 文件上传直接入库 + 对话引用（📎 上传即入库，agent 可检索回答）
- [x] 检索来源（provenance）：`tool_result` 带命中文档 id，对话显示「引用来源」可跳转知识库

## 企业级补强（2026-08-25 增补）

- [x] **HA 多实例队列**：`JobStore.claim_queued` 跨实例认领（DB 租约互斥），本地堆空时轮询共享库——多实例可并行消费
- [x] **API 级幂等**：`Idempotency-Key` 中间件，同 key 重放去重（24h TTL，`Idempotent-Replayed` 头）
- [x] **备份/恢复**：`scripts/backup.py`（SQLite 拷贝 + WAL checkpoint / PG pg_dump）
- [x] **审计导出**：`GET /audit/export` CSV
- [x] **用量/计费**：`GET /cost/usage` 按租户×日聚合（runs/tokens/cost）
- [ ] **SSO（SAML/Okta/Azure AD）**：OIDC 钩子已有，SAML 协议接入未做（大项，待排期）
- [ ] **SLA/容量规划**：自动扩缩未做（部署层）

---

## 1. 现状评估

### 1.1 已具备（功能面）

| 域 | 内容 | 关键文件 |
|---|---|---|
| 认证 | JWT(HS256)+ pbkdf2 密码 + `UserRow`，`/auth/token` 登录、`/auth/me` 取权限 | [auth_api.py](app/gateway/auth_api.py)、[auth.py](app/gateway/auth.py)、[passwords.py](app/gateway/passwords.py) |
| 授权 | RBAC(租户/角色/用户级策略)、default-deny、DENY 优先 | [policy.py](app/security/policy.py)、[roles_api.py](app/security/roles_api.py) |
| 治理 | 审批(§19)、队列(§9/§11/§55)、事件 Outbox(§28.2)、审计、发布/灰度/回滚 | [approval/](app/approval)、[queue/](app/queue)、[events/](app/events)、[release/](app/release) |
| 能力 | 知识库/记忆/图谱/评测、MCP、自定义沙箱工具、模型网关(路由/降级/熔断/限流/成本) | [knowledge/](app/knowledge)、[memory/](app/memory)、[graph/](app/graph)、[tool/](app/tool)、[agent/model/](app/agent/model) |
| 质量 | 280 个测试、统一错误码、审计、敏感信息脱敏、SSRF 防护、CI | [tests/](tests/)、[errors.py](app/common/errors.py)、[audit.py](app/security/audit.py) |
| 前端 | 20+ 页面覆盖全部功能，权限策略/审批详情/工具风险级/队列采样等已对齐后端 | [frontend/src/pages/](frontend/src/pages/) |

### 1.2 仍是「开发态 / 演示态」（阻碍对外）

| 现状 | 位置 |
|---|---|
| `auth_require_jwt=False` 时，无 token 请求直接回落 seed 管理员 | [deps.py:66-71](app/gateway/deps.py#L66-L71) |
| 默认 `APP_LLM_PROVIDER=mock`、本地 Postgres（compose pgvector:5433）、seed 身份 | [.env.example](.env.example) |
| 只有 seed 的 `user-default`，**没有用户管理入口**（无法建用户/设密/禁用） | [auth_api.py](app/gateway/auth_api.py) |
| 租户 id 是任意字符串，无 onboarding/邀请/隔离校验 | 各 API 的 `tenant_id` 字段 |
| `auth_jwt_secret` 默认 `dev-secret-change-me`，启动不校验 | [settings.py:37](app/settings.py#L37) |
| SecretManager 是**进程内内存 dict**，重启即丢、明文驻留内存 | [secrets.py:19-36](app/security/secrets.py#L19-L36) |
| 自定义工具沙箱声明「非真正容器隔离」(subprocess + rlimit) | [custom.py:1-8](app/tool/custom.py#L1-L8) |
| 队列是「MVP 进程内实现」（内存堆 + SQLite 租约），多实例不可用 | [queue.py:6](app/queue/queue.py#L6) |
| SPA fallback 把未匹配的 GET 路径返回 `index.html` + 200，吞掉 API 错误 | [main.py:467](app/main.py#L467) |
| 前端 2.8MB 单 bundle、刷新闪动未定位 | [frontend/](frontend/) |

---

## 2. 差距清单

| # | 差距 | 影响 | 优先级 |
|---|---|---|---|
| G1 | 无 token 回落 seed 管理员（后台裸奔） | 未认证即管理员，数据/操作全开放 | **P0** |
| G2 | 无用户管理（建/改/禁用/密码） | 无法支撑多用户对外使用 | **P0** |
| G3 | 无租户 onboarding 与隔离校验 | 多租户无管控，越权面 | **P0** |
| G4 | `auth_jwt_secret` 默认值可上线 | 签名密钥泄露即伪造任意用户 | **P0** |
| G5 | SecretManager 内存态、明文 | 真实 LLM/凭据无法安全落地，重启丢失 | **P0/P1** |
| G6 | SPA fallback 吞 API 错误 | 联调/前端错误被掩盖（已导致白屏一次） | P1 |
| G7 | 沙箱非容器隔离 | 恶意代码可破坏宿主 | P1 |
| G8 | 队列进程内 MVP | 多实例/高可用不可用 | P1 |
| G9 | 默认 SQLite、无 Redis | 生产不可扩展、无分布式能力 | P1 |
| G10 | 前端单 bundle/闪动/缺骨架 | 体验与性能 | P2 |

---

## 3. 分阶段路线

### Phase 0 · 安全门禁（第 1 优先；改动小、收益大，约 1-2 天）

**目标**：堵住「未认证即管理员」与「默认密钥可上线」两个致命口子；修掉 SPA fallback 隐患。

| 改动项 | 位置 | 说明 |
|---|---|---|
| 认证强制 | [deps.py](app/gateway/deps.py) | `auth_require_jwt=True` 时 `get_subject` 拒绝无 token；生产环境强制开启 |
| 启动自检 | [settings.py](app/settings.py)、[main.py](app/main.py) | `auth_jwt_secret` 仍是默认值时启动直接失败；`APP_ENVIRONMENT=prod` 必须 `auth_require_jwt=True` |
| SPA fallback 收敛 | [main.py:467](app/main.py#L467) | API 路径(以 `/api` 或已知路由前缀开头)不命中时返回 JSON 404，不再吐 index.html |
| 首登引导 | [auth_api.py](app/gateway/auth_api.py) | seed 用户第一次登录强制改密（后移至 Phase 1 完整化） |

**验收**：`auth_require_jwt=True` 下无 token 请求一律 401；`auth_jwt_secret` 用默认值启动失败；`/policies/meta` 等未知路径返回 JSON 404。

**涉及测试**：`tests/test_auth.py`、`tests/test_api.py`（当前有依赖无 token 回落逻辑的用例，需同步调整）。

---

### Phase 1 · 认证与用户管理（核心硬门禁；约 3-5 天）

**目标**：让「建租户 → 建用户 → 登录 → 授权 → 审计」成为闭环，并让密钥安全持久化。

| 改动项 | 说明 |
|---|---|
| 用户管理 API | 新建 `users_api.py`：创建/更新/设密/重置/禁用用户；`/auth/me` 扩展 |
| 租户管理 API | 新建 `tenants_api.py`：租户创建、状态、默认策略；isolated 校验（resource 作用域） |
| 首次登录改密 | seed/初始密码标记 `must_change`，登录后强制改 |
| 密钥持久化 | SecretManager 从内存 dict → **应用层加密落库**（主密钥来自环境变量/KMS），或接外部 Secret Manager |
| 前端 | 用户管理页、登录页完善、改密引导 |

**验收**：能建租户/建用户/登录/改密/禁用；无 token 无法访问任何业务接口；密钥重启不丢、不落日志。

---

### Phase 2 · 运行时真实化（上线必需；约 3-5 天）

**目标**：从「SQLite + mock」切到「PostgreSQL + Redis + 真实 LLM」可部署形态。

| 改动项 | 说明 |
|---|---|
| 生产 DB | PostgreSQL(asyncpg) + pgvector(知识库)；开发已统一连 Postgres，`dev.db` 已弃用 |
| Redis | 限流 / 队列租约 / 分布式锁（现有空实现占位接上） |
| 真实 LLM 链 | openai provider 全链路验证 + 密钥安全注入（依赖 Phase 1 的密钥持久化） |
| docker-compose 生产化 | [docker-compose.yml](docker-compose.yml) 增加 app 服务、HTTPS(TLS)、healthcheck、日志卷 |

**验收**：`docker compose up` 一套起；真实模型可用；SQLite→PG 数据迁移成功；多实例队列不冲突。

---

### Phase 3 · 安全加固（风险收敛；可与 Phase 2 并行）

| 改动项 | 说明 |
|---|---|
| 沙箱容器化 | 用 Docker/gVisor 隔离替代 subprocess+rlimit（[custom.py](app/tool/custom.py)） |
| 攻击面审计 | SSRF、输出安全、注入、路径穿越全量过一遍 |
| 租户配额 | 限流 / 成本上限 / 运行配额 → 租户级 |

**验收**：红队清单过一遍；沙箱逃逸尝试全被拦截；租户配额生效。

---

### Phase 4 · 前端体验（体验上线）

| 改动项 | 说明 |
|---|---|
| 分包 | Route-level `React.lazy` 拆 2.8MB bundle，首屏优化 |
| 闪动修复 | 刷新白屏/样式闪动定位并修复；骨架屏、统一空态/错误态 |
| 流程打磨 | 登录/注册/引导/403 页 |

**验收**：首屏 <1s（gzip 下）；刷新无闪动。

---

## 4. 风险与依赖

| 项 | 说明 |
|---|---|
| **依赖顺序** | Phase 0/1 串行前置；Phase 2 依赖 Phase 1（密钥/DB 是真实 LLM 的前提）；Phase 3/4 可与 2 并行 |
| **测试回归** | 强制认证会改动 `get_subject` 语义，280 个测试中依赖「无 token 回落」的用例需同步改造（G1 落地时） |
| **数据迁移** | 开发已直接用 Postgres，无 `dev.db` → PG 迁移负担；向量表依赖 pgvector |
| **行为差异** | mock → 真实 LLM 由确定性变非确定性，评测/回归用例需重标定 |
| **密钥迁移** | 现有内存 SecretManager 无持久化数据可迁移，直接换实现即可，无历史包袱 |

---

## 5. 建议执行顺序

1. **Phase 0**（1-2 天）：先堵 G1/G4/G6 三个洞 —— 纯改动、立即见效，且是后面所有工作的安全前提。
2. **Phase 1**（3-5 天）：认证与用户管理闭环 —— 对外产品的硬门禁，完成后平台才具备「多用户可安全使用」的基础。
3. **Phase 2**（3-5 天）：真实化部署。
4. **Phase 3 / Phase 4**（并行）：安全加固 + 前端体验。

> 工作量估算基于现有代码结构，实际按迭代调整。每个 Phase 的验收标准即为该阶段的 Definition of Done。

---

## 部署指南

### 域名 TLS（Caddy 自动 Let's Encrypt）

1. 在 DNS 控制台把 `agent.example.com` 的 **A 记录**指向服务器公网 IP,开放 80/443 端口。
2. `.env` 设 `DOMAIN=agent.example.com`(不设则走 `http://localhost` 本地 HTTP)。
3. `docker compose up -d --build` —— Caddy 自动申请/续期证书,`https://agent.example.com` 访问。

### gVisor 沙箱(内核级隔离)

```bash
# 1. 安装 runsc(需 root)
curl -fsSL https://gvisor.dev/archive/releases/latest/go/runsc -o /usr/local/bin/runsc
chmod +x /usr/local/bin/runsc
# 2. 注册为 Docker runtime
cat > /etc/docker/daemon.json <<'EOF'
{ "runtimes": { "runsc": { "path": "/usr/local/bin/runsc" } } }
EOF
systemctl restart docker   # 或 service docker restart
# 3. 应用启用
APP_SANDBOX_DOCKER=true
APP_SANDBOX_DOCKER_RUNTIME=runsc
```

启用后自定义工具以 `docker run --runtime runsc --network none ...` 执行。

### 生产启动清单

- `APP_ENVIRONMENT=prod` + 强随机 `APP_AUTH_JWT_SECRET`(compose 会强制)
- 建议独立 `APP_SECRET_ENCRYPTION_KEY`
- `APP_SANDBOX_DOCKER=true`(有 Docker 时)+ 可选 `APP_SANDBOX_DOCKER_RUNTIME=runsc`(gVisor)
- 真实 LLM:`APP_LLM_PROVIDER=openai` + base_url/api_key(或走配置中心 + 密钥管理)
- `DOMAIN` 绑定域名后由 Caddy 终止 TLS
