# 集成指南

> 给集成工程师的"能接哪些系统、怎么接"手册。所有 HTTP 能力都围绕一份 REST API 展开（服务启动后可打开 `/docs` 看 OpenAPI）。

## 1. REST API 与认证

- Base URL：`https://<你的域名>`（开发 `localhost:8000`）。
- 认证：**Bearer JWT**。`POST /auth/token` 拿 token：
  - 请求体 `{tenant_id, user_id, password}`，其中 `password` 为**客户端先做 SHA-256(十六进制)** 再传输的值（非明文）。
  - 登录成功返回 `access_token`（默认 3600s 过期）。
- 之后所有业务请求带 `Authorization: Bearer <token>`。
- **错误模型**：非 2xx 返回 `{"code": "CODED_ERROR", "message": "人类可读", "detail": {...}}`，code 稳定用于程序判断。

```bash
PWD_SHA=$(python3 -c 'import hashlib;print(hashlib.sha256(b"你的密码").hexdigest())')
TOKEN=$(curl -s -X POST $B/auth/token -H 'Content-Type: application/json' \
  -d "{\"tenant_id\":\"tenant-default\",\"user_id\":\"user-default\",\"password\":\"$PWD_SHA\"}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s $B/agents/runs -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"input":"12 + 30"}'
```

### 幂等重试

所有 `POST/PUT/PATCH` 可携带 **`Idempotency-Key`** 头：同 key 重放会在 24h 内去重，响应带 `Idempotent-Replayed` 头。**自动化/重试请求务必带**，避免"网络重试导致重复执行"。

## 2. OpenAPI

服务启动后 `/docs`（Swagger UI）、`/openapi.json`。推荐直接据此对接；以下为高频路径一览：

| 域 | 路径 |
|---|---|
| 认证/用户/租户 | `/auth/token`、`/auth/me`、`/users`、`/tenants` |
| Agent 运行 | `/agents/runs`（列表/创建/详情/成本/暂停恢复取消）、`/agents/runs/stream`（SSE 流式） |
| 会话对话 | `/agents/sessions`、`.../messages`、重命名/删除 |
| 知识 | `/knowledge/bases`、`/knowledge/documents`（上传/入库/删除）、`/knowledge/search`、分片上传 API |
| 记忆/图谱 | `/memory`、`/graph` |
| 工具 | `/tools`（注册/执行/风险级）、`/mcp`、`/custom-tools` |
| 评测/发布 | `/evaluation`、`/agents/{id}/versions`（契约/回归/安全评测/发布/灰度/回滚/停用） |
| 治理 | `/approval`、`/audit`(+`/export`)、`/policy`、`/roles`、`/config`、`/flags` |
| 成本/模型 | `/cost/usage`、`/model/config` |
| 数据 | `/data/tenant/{tid}/purge`、`/data/sweep` |
| 健康/元信息 | `/health/live`、`/health/ready`、`/health/ha`、`/meta` |

## 3. 审批 Webhook（出站事件）

配置 `APPROVAL_NOTIFY_CHANNELS=webhook` + `APPROVAL_WEBHOOK_URL` 后，有审批请求时平台**POST JSON** 到你的端点：

```
POST <your_webhook>
Headers:
  Content-Type: application/json
  X-Agent-Timestamp: <unix_ts>
  X-Agent-Signature: sha256=<hmac_sha256(secret, f"{timestamp}.{body}")>
Body: {"approval_id": "...", "tenant_id": "...", "tool_ref": "...", "message": "审批请求：<tool_ref>（approval_id=...）"}
```

- **验签**：用 `APPROVAL_WEBHOOK_SECRET` 按上式复算比对，避免伪造（防篡改/重放）。
- 事件通道还有 `log` / `email`（SMTP 配置驱动）。

## 4. MCP（外接工具服务器）

- 平台可作为 MCP **client**：配置 `APP_MCP_SERVERS='{"server_name": "base_url"}'`，把外部 MCP server 的工具注册进 Agent 工具集。
- 安全：每 server 可配工具白名单 `APP_MCP_TOOL_ALLOWLIST`；输出大小上限 `APP_MCP_MAX_OUTPUT_CHARS`。
- 本地联调参考：`scripts/fake_mcp_server.py`（`tools/list` + `tools/call`）。
- 开发版只送子进程沙箱；生产可开 Docker/gVisor 运行自定义工具（见部署手册）。

## 5. 自定义工具

- 通过 `/custom-tools` 注册，运行在沙箱内：
  - 默认子进程 + rlimit（开发）；
  - 生产 `APP_SANDBOX_DOCKER=true` → Docker `--network none`；gVisor `APP_SANDBOX_DOCKER_RUNTIME=runsc`。
- 沙箱封禁危险操作：`os.system/subprocess/os.spawn*/os.open` 族；不泄漏宿主 env；出站端口受控。
- **SSRF 防护**：`http.get` 单次解析并固定已验证 IP，防内网扫描/TOCTOU。

## 6. 身份源（SSO）

- 内置 JWT(HS256) 身份；**OIDC/JWKS** 可选接入外部 id_token（`APP_OIDC_ENABLED=true` + `APP_OIDC_JWKS_URL/ISSUER/AUDIENCE`），并支持 claim / 邮箱域名 → 租户映射。
- ⚠️ **SAML（Okta/Azure AD 的 SAML 协议）尚未实现**——OIDC 钩子已有，SAML 属路线图，采购评估时以交付清单为准。

## 7. 常见系统连接器 · 现状与路线图

一句话：**今天能"接系统"的是通用通道（REST / 流式 / Webhook / MCP / OIDC），不是预置 SaaS 机器人**。按你的接入优先级评估：

| 想接的系统 | 现状 | 落地方式 |
|---|---|---|
| 任意系统（拉数据） | ✅ 已就绪 | REST API / `/agents/runs/stream` SSE |
| 审批通知进 IM（Slack/Teams/企微） | ✅ 已就绪 | 审批 Webhook（HMAC）+ 对方 webhook |
| 外部 MCP 工具服务器 | ✅ 已就绪 | MCP client（白名单） |
| 现有目录/文档源当知识库 | ✅ 已就绪 | `/knowledge/documents` 入库 API（脚本批量灌） |
| OIDC 身份源 | ✅ 已就绪 | OIDC/JWKS |
| Slack / Teams 双向机器人（用户在 IM 里发起对话） | 🚧 路线图 | 需要入站 Webhook/事件订阅 + 会话桥，按需排期 |
| SAML（Okta/Azure AD） | 🚧 路线图 | 协议接入，大项 |
| 常见知识源连接器（Confluence/SharePoint/Notion 等） | 🚧 路线图 | 每个连接器 = 分发任务 + 凭证 + 增量同步，按套餐排期 |

> 采购承诺请以「7 现状」列为准；🚧 列为路线图而非现成能力。

## 8. 对接清单

1. 确认版本与 `APP_ENVIRONMENT=prod`（强制认证）。
2. 用最小权限建集成账号（不要通配），见[管理员手册](admin-guide.md)§2。
3. 所有写请求带 `Idempotency-Key`。
4. 先用 `/health/ready` + `/meta` 连通性自检，再跑 `/agents/runs`。
5. 敏感调度/告警接审批 Webhook 的验签。