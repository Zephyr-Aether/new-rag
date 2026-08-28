# 故障排查

> 支持/运维视角。定位顺序：**先看首页待办与 `/health/*`，再看 Run 详情错误横幅，最后查审计与 Trace**。所有业务错误都返回统一错误码 `code`，可直接搜。

## 1. 服务健康

| 症状 | 检查 | 处理 |
|---|---|---|
| 首页无法打开 | `curl /health/ready` | 数据库不可达：`pg_isready`；迁移失败看容器日志（启动自动 `alembic upgrade head`） |
| 队列水位异常高 | `/health/ha` + 管理员区 → 队列 | 多实例消费是否正常；`DEAD_LETTER` 是否有积压 |
| 401/403 飘红 | 见「认证与权限」 |

## 2. 认证与权限

| 错误码 | 含义 | 处理 |
|---|---|---|
| `AUTH_INVALID_TOKEN` | token 缺失/过期/伪造 | 重新登录；检查 `APP_AUTH_JWT_SECRET` 是否在多实例不一致 |
| `AUTH_INVALID_CREDENTIALS` | 用户不存在或密码错 | 记住密码走 sha256 传输；管理员可重置密码（首登强制改密） |
| `AUTH_DISABLED` | 用户被禁用 | 管理员在用户管理恢复 |
| 无码 403 | RBAC 默认拒绝 | 检查该用户的 ALLOW 策略；DENY 优先可能覆盖 ALLOW |

常见误区：`auth_require_jwt=false`（非 prod 默认）时无 token 会**回落 seed 管理员**，生产必须 `APP_ENVIRONMENT=prod` 强制 JWT。

## 3. 运行（Run）状态与失败

状态机：`PENDING / RUNNING / PAUSED / COMPLETED / FAILED / CANCELLED / TIMEOUT / UNKNOWN`。

- **看 Run 详情**：顶部横幅给出 `code` 与 message；步骤时间线红色=失败步骤；设有错误原因与一步「重放调试 / 对比原 run」。
- 常见失败：
  - **超时**：`TIMEOUT` / 单步 `AGENT_TIMEOUT`——预算 `APP_BUDGET_MAX_*` 或模型延迟。先调 `APP_BUDGET_MAX_RUNTIME_S` / `APP_BUDGET_MAX_STEP_S`。
  - **模型错误**：429 限流 / 熔断——看「监控 → 模型健康」；`APP_LLM_RATE_LIMIT`、`APP_LLM_BREAKER_THRESHOLD`。
  - **工具失败**：步骤里工具标 ❌；检查工具白名单/沙箱输出上限 `SANDBOX_MAX_OUTPUT_BYTES`（默认 100k 字符截断）。
  - **预算/终止**：`budget:*` 相关——看提示的预算项，或拆分任务。
- Run 很慢→成本高：`/runs/{id}/cost` 看 LLM 调用明细（P/H/T/R 分项与延迟）；调度决策页可对比模型选择。

## 4. 队列 / 事件

- 管理员区 → 队列：`RUNNING`/`PENDING` 水位、`DEAD_LETTER` 死信。死信可重放（`/queue/jobs?state=DEAD_LETTER`）。
- 多实例时队列认领依赖 DB 租约 + Redis；若死信骤增，先看是否有标准券/数据库锁问题。
- 事件 Outbox（`/events`）：幂等键（`dedupe_key`）冲突不会重复投递。

## 5. 发布与回归

| 错误码 | 含义 | 处理 |
|---|---|---|
| `RELEASE_REGRESSION_FAILED` | 基准集回归通过率回退 | 看 Regression 报告逐条定位；修复后重发；确属误判可「发布引导」勾选强制发布跳过门禁（**有风险，需管理员确认**） |
| `AGENT_VERSION_NOT_FOUND` | 版本不存在 | 重新选择 DRAFT 版本 |
| 契约检查失败 | 发布被契约阻断（fail），或需人工签核（warn） | 检查结果页逐项 reason |

- 灰度（Canary）指标恶化会在「发布决策」直接给「建议回滚」，提供「停用灰度 / 回滚」一键。

## 6. 沙箱与安全告警

- 自定义工具被拒：`forbidden` 调用——检查 `must_not_call` 评测或沙箱封禁（`os.system` 等）。
- SSRF 拦截：`http.get` 目标被判定内网——只允许公网白名单。
- 输出超限：工具结果被截断（`SANDBOX_MAX_OUTPUT_BYTES` / `MCP_MAX_OUTPUT_CHARS`）。

## 7. 日志 / Trace / 脱敏

- 正常运行写结构化日志；Trace payload 按采样率落库（`APP_TRACE_PAYLOAD_RATE`，默认 0.1）。**查不到 payload 属采样，不是丢了**。
- Run 详情「Trace Payload 采样（脱敏）」可加载：确认脱敏后只在必要时导出。
- 审计日志 / CSV 导出「管理员区 → 审计」用于合规追溯；数据清除走「数据生命周期」。

## 8. 数据/恢复事故

- 误删/数据损坏：`scripts/backup.py restore <备份>`（恢复前先再备份一遍当前库）。
- 多实例 key 不一致：所有实例用同一 `APP_AUTH_JWT_SECRET` / `APP_SECRET_ENCRYPTION_KEY`。

## 9. 标准定位流程（贴给支持同学）

1. `curl /health/ready`、`/health/ha`——确认服务与队列。
2. 打开对应 Run 详情，记错误码。
3. 按上表找对应小节；解决后 **Replay** 验证。
4. 仍不行：查审计 + Trace payload，带上错误码与步骤导出给开发。