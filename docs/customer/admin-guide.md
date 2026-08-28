# 管理员手册

面向平台管理员（具备治理权限的角色，拥有「管理员区」可见性）。

## 1. 租户与用户

- **租户 onboarding**：由管理员走用户管理页（或 `POST /tenants`）创建租户并指定初始管理员。租户之间数据隔离（各 API 都按 `tenant_id` 作用域）。
- **用户管理**：创建 / 启用禁用 / 重置密码（管理员设的密码首登强制改密 `/auth/password`）。
- **权限模型不是"三档角色"，而是 RBAC**：见下节。默认 seed 管理员拥有完整权限集合。

## 2. 角色与权限（RBAC，默认拒绝）

- 策略四要素：**主体**（用户级 / 角色级 / 租户级）× **action × resource × 效果（ALLOW/DENY）**。
- **默认拒绝**：无任何匹配即拒绝；**DENY 优先**：命中 DENY 立即拒绝。
- 动作令牌示例：`run:create`、`tool:execute`、`kb:ingest`、`policy:manage`、`config:write`、`queue:ops`、`data:purge`、`release:publish`、`eval:write`。
- 资源级策略（`resource != "*"`）用于细粒度授权，不会进入页面级 action 判定（页面按 action 显隐）。
- 管理入口：「管理员区 → 权限策略」（策略增删）+「角色」（角色即一组策略的命名集合，`/roles`）。

> 实践：新增普通用户请**不要直接给通配**。按"能用到什么"给最小动作集：例如创作者给 `run:create`、`kb:ingest`、`knowledge:search`、`eval:write`；运维给 `queue:ops`、`cost:reconcile`；架构/安控给 `release:publish`、`policy:manage`、`config:write`、`data:purge`。

## 3. 工具与审批

- 工具注册按风险分级；需要审批的工具执行前进入审批流（`/approval`）。
- **审批通知**：可选 `log` / `email` / `webhook` 通道（`APPROVAL_NOTIFY_CHANNELS`）。webhook 出站带 HMAC 签名，见[集成指南](integration-guide.md#审批-webhook)。
- 审批动作：`GET /approval`、`/approval/{id}`、`approve`、`reject`。

## 4. 审计

- 关键操作写入审计日志，可查询；**一键导出 CSV**：`GET /audit/export`（管理员区 → 审计）。
- 幂等：所有 `POST/PUT/PATCH` 携带 `Idempotency-Key` 会被去重（24h TTL，响应带 `Idempotent-Replayed` 头），适合自动化重试。

## 5. 配额、预算与成本

| 维度 | 默认值 | 配置项 |
|---|---|---|
| 租户并发 Run | 20 | `APP_TENANT_MAX_CONCURRENT_RUNS` |
| LLM 限流 | 100/60s | `APP_LLM_RATE_LIMIT` / `APP_LLM_RATE_LIMIT_WINDOW_S` |
| 单 run 步数 | 30 | `APP_BUDGET_MAX_STEPS` |
| 单 run tokens | 200k | `APP_BUDGET_MAX_TOKENS` |
| 单 run 成本 | $10 | `APP_BUDGET_MAX_COST` |
| 单 run 工具调用 | 50 | `APP_BUDGET_MAX_TOOL_CALLS` |
| 单 run 时长 | 600s | `APP_BUDGET_MAX_RUNTIME_S` |
| 上传上限 | 50MB | `APP_MAX_UPLOAD_BYTES` |

- 成本聚合：`/cost/usage?days=` 按租户×日聚合（runs/tokens/cost）；单价 `/cost/overview`、趋势 `/cost/growth`。
- 配置中心：「管理员区 → 配置中心」可运行时改配置/Flags；密钥管理在这里单项加密保存第三方凭据。

## 6. 数据生命周期与合规

- 管理员区 → 数据生命周期：租户数据清除（`POST /data/tenant/{tid}/purge`）、全局清扫 `POST /data/sweep`。
- 数据清除会级联清理 Run/步骤/审计/评测等关联数据，操作前确认。
- 审计保留期与存储上限是**套餐维度**（见 [`docs/commercial/pricing.md`](../commercial/pricing.md)），生产按套餐配置落地。

## 7. 评测与发布治理

- 评测样例管理：「知识 → 评测」（BADCASES 坏案例 / GOLDEN 黄金集 / ADVERSARIAL 对抗集 / REGRESSION 回归集），支持种子配置批量导入（按 query+kind upsert）。
- 发布：「发布」页面走 版本 → 契约检查 → 基准回归 → Canary 灰度 → 全量，逐步有线上一键回滚 / 停用。**回归回退会阻断发布**（`RELEASE_REGRESSION_FAILED`），需要管理员确认后或修复后放行。

## 8. 日常运维核对

1. 健康：`/health/ha` 看实例与队列水位；首页「待办」看死信/失败 Run/待审批。
2. 队列：管理员区 → 队列，`DEAD_LETTER` 可查看并重放；事件 Outbox 同理。
3. 模型健康：管理员区/监控 → 模型健康监控限流 429 与熔断（`APP_LLM_BREAKER_THRESHOLD`）。
4. 备份与恢复：见[部署手册](deployment.md)第 3/4 节，按时做并异地留存。