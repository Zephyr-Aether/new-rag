# 企业级 Agent 平台技术设计规范

> 面向生产环境的 Agent 平台与 Agent Runtime：Execution · Scheduling · Cancellation · Checkpoint · Timeout · Retry · Circuit Breaker · Queue · RAG · Knowledge Graph · Memory · Security · Multi-Tenant · Observability · Evaluation · Versioning · Rollback · Developer Debugging。
>
> 本文档由两份规范深度合并重构而成，去重后形成单一连贯章节流：涵盖平台级设计（架构/边界/数据模型/API）与 Runtime 工程化设计（状态机/执行引擎/可靠性/知识层/运营治理）的全部要点。
>
> 立场：Engineering First、Security First、Observability First、Failure First、Evaluation Driven。模块化单体起步，不绑定任何 LLM 厂商或 RAG 框架。

- 编写日期：2026-08-20
- 状态：Draft v0.3（深度合并重构版）
- 目标读者：有经验的软件工程师，可据此直接开始编码

---

# 第一部分：总体架构与设计哲学

## 1.1 设计哲学（10 条原则）

| # | 原则 | 含义 | 反例（不合格） |
|---|---|---|---|
| 1 | Engineering First | 每个设计回答"为什么/结构/流程/异常/并发/安全/性能/可观测/测试/坑" | 只有架构图没有决策 |
| 2 | Security First | 默认拒绝、最小权限、UNTRUSTED 数据隔离 | 前端隐藏当隔离 |
| 3 | Observability First | 任何一次 Run 可答"发生了什么、为什么" | 只有日志没有 Trace |
| 4 | Evaluation Driven | 改动用评测集说话，不靠感觉 | 凭感觉换模型 |
| 5 | Failure First | 先设计失败路径：LLM 挂/慢/限流、Tool 挂、Worker 崩、取消竞态、队列堆积 | 只写 happy path |
| 6 | Multi-Tenant Isolation | tenant_id 全模型，服务端强制 | 靠前端过滤 |
| 7 | Cost Aware | 成本可归因、可预算 | "今天花了 $500" |
| 8 | Graceful Degradation | 依赖失败走降级链，不硬编 | 一直 Retry |
| 9 | Recoverability | 崩溃可恢复、任务不悬挂、副作用幂等 | 崩了重跑一遍 |
| 10 | Developer Debuggability | 5 分钟内定位线上问题 | 只能加日志重跑 |

**最终目标**：不是"Agent 能运行"，而是"Agent 可以长期稳定运行，并且开发团队知道它为什么这样运行"。

## 1.2 四层架构

```
                    Agent Application（业务 Agent / Skill / Workflow）
                                  │
                                  ▼
              ┌─────────────────────────────────────────┐
              │   Agent Runtime / Control Plane          │
              │   Execution · State Machine · Scheduler   │
              │   Cancellation · Timeout · Retry ·        │
              │   Checkpoint · Budget · Policy · Isolation│
              └──────┬──────────────┬──────────────┬──────┘
                     ▼              ▼              ▼
                 LLM Layer      Tool Layer     Knowledge Layer
                 Router        Registry       RAG / Graph / Memory
                 Pool          Permission     Search / Citation
                 Fallback      Sandbox        Provenance
                     │              │              │
                     └──────────────┼──────────────┘
                                    ▼
              ┌─────────────────────────────────────────┐
              │   Infrastructure：Queue/Cache/DB/Object  │
              │   Lock/Scheduler/Event Bus              │
              └──────────────────┬──────────────────────┘
                                 ▼
              ┌─────────────────────────────────────────┐
              │  Cross-Cutting：Security·Observability·  │
              │  Evaluation·Cost·Audit·Versioning·Release │
              └─────────────────────────────────────────┘
```

**关键分层决策**：Core Runtime 只负责执行与治理；Capability Layer（RAG/Graph/Memory/Tool/MCP/Skill）可插拔可替换；Infrastructure 用通用中间件；Cross-Cutting 横切且不依赖业务模块。

## 1.3 服务边界与模块边界

| 模块 | 归属 | 职责 | 不做什么 |
|---|---|---|---|
| API Gateway | Edge | 认证/限流/路由/TLS/请求审计入口 | 业务逻辑 |
| Agent Runtime | Data | 状态机/预算/编排/取消/恢复 | 不实现检索、不直连 LLM provider |
| Model Gateway | Data | provider 路由/重试/限流/成本/fallback | 不感知 Agent 语义 |
| Context Engine | Data | 组装/预算/过滤/排序/信任分级 | 不生成内容 |
| Tool Runtime | Data | 工具执行/沙箱/审批闸/幂等/熔断 | 不决定工具语义 |
| Tool Registry | Control | 注册/版本/发现/健康/灰度 | 不执行 |
| Knowledge Platform | 能力层 | 索引/检索（RAG/图）/权限过滤 | 不做授权判定 |
| Memory 服务 | 能力层 | 记忆读写/TTL/隔离 | 不跨用户读写 |
| Evaluation | Control | 评测集/评测运行/指标 | 不影响线上流量 |
| IAM/Policy | 横切 | 授权判定 | — |
| Observability | 横切 | Trace/Metric/Log | — |
| Config/Feature Flag | 横切 | 版本化配置/开关 | — |

**依赖规则**：单向依赖（`Application → Runtime → Capability → Infrastructure`）；Capability 不得反向依赖 Runtime；模块间以版本化契约通信；CI 用 import-linter 强制。

## 1.4 关键架构决策（ADR）

| # | 决策 | 理由 | 何时推翻 |
|---|---|---|---|
| ADR-01 | 模块化单体起步 | 3~5 人团队，拆分收益 < 成本 | 独立扩容需求明确 |
| ADR-02 | Runtime 无状态化，状态外置 PG+Redis | 水平扩展、崩溃恢复的基础 | 无 |
| ADR-03 | RAG/Graph/Memory 是能力层非核心 | 可插拔、不绑架架构 | 无 |
| ADR-04 | 检索通道统一抽象 | Runtime 不感知向量/图/SQL | 检索语义分化到无法统一 |
| ADR-05 | pgvector 起步，不引专用向量库 | 简单优先 | 块 >500 万 / 复杂过滤 |
| ADR-06 | 全模型带 tenant_id，服务端强制 | 隔离是硬合规 | 无 |
| ADR-07 | 模型访问统一走 Model Gateway | 路由/限流/成本集中 | 无 |
| ADR-08 | 一切 artifact 版本化 | 灰度/回滚前提 | 无 |

## 1.5 技术选型

| 域 | 选型 | 何时换 |
|---|---|---|
| Runtime/API | Python + FastAPI | 独立扩缩容需求出现 |
| 关系库 | PostgreSQL | 无 |
| 缓存/锁/队列 | Redis | 吞吐不足换 Kafka/Pulsar |
| 向量 | pgvector 起步 | 块 >500 万 或 复杂过滤 → 专用向量库 |
| 全文 | PG tsvector → OpenSearch | 检索延迟/中文分词 |
| 图 | 后置（Neo4j 或 PG 递归 CTE） | 关系型数据规模大 |
| 对象 | S3 兼容（MinIO） | 无 |
| 追踪 | OpenTelemetry | 无 |

---

# 第二部分：Agent Runtime 核心模型

## 2.1 为什么需要正式数据模型

Run 是**异步、跨进程、可中断、可恢复**的执行单元。没有正式的 Run/Step/Task/ToolCall/LLMRequest/Checkpoint/Event/Trace 结构，就无法做取消传播、断点续跑、审计、重放。

## 2.2 核心数据结构（Pydantic 契约，版本化）

```python
class Run(BaseModel):
    run_id: str
    tenant_id: str
    user_id: str
    agent_id: str
    agent_version: str  # 绑定的版本集（prompt/model/tool/knowledge）
    session_id: str
    state: RunState  # §3 状态机
    budget: ExecutionBudget  # §18：steps/tokens/cost/tool_calls/wall_time
    model_route: ModelRoute  # §8 路由决策（含 reason，落 Trace）
    input: RunInput
    output: RunOutput | None
    error: ErrorInfo | None
    checkpoint: CheckpointRef
    deadline: datetime
    created_at / updated_at / started_at / finished_at


class Step(BaseModel):  # 一次"思考+动作"循环迭代
    step_id: str
    run_id: str
    seq: int
    state: StepState  # PENDING/RUNNING/WAITING_TOOL/OBSERVING/...
    input: StepInput
    llm_call: LLMRecord
    tool_calls: list[ToolCallRecord]
    observations: list[Observation]
    decision: StepDecision  # continue / done / escalate / cancel
    tokens_used: int
    cost: Decimal
    checkpoint_before: bool


class ToolCall(BaseModel):  # 一次工具执行（含幂等键与决策链）
    call_id: str  # = hash(tenant,run,step,tool,args)
    run_id: str
    step_id: str
    tool_ref: str
    args: dict
    permission_decision: PolicyDecision
    risk_decision: RiskDecision
    status: CALL_STATUS  # PENDING/RUNNING/SUCCEEDED/FAILED/UNKNOWN
    result: ToolResult | None
    latency_ms: int
    cost: Decimal


class LLMRequest(BaseModel):  # 一次模型调用（可取消、可重放）
    request_id: str
    run_id: str
    step_id: str
    provider: str
    model: str
    messages: list[Message]
    tools: list[ToolSchema]
    params: LLMParams
    deadline: datetime
    cost_estimate: Decimal


class Checkpoint(BaseModel):  # 可恢复的持久化快照
    checkpoint_id: str
    run_id: str
    run_state: RunState
    completed_steps: int
    current_step: int
    variables: dict
    tool_results: dict[str, ToolResult]  # call_id -> result（幂等续跑）
    trace_id: str
    created_at: datetime


class Event(BaseModel):  # 一切状态/副作用变更的不可变记录
    event_id: str  # 幂等去重
    event_type: str  # RunStarted/StepStarted/ToolCalled/CancelRequested/...
    run_id: str
    step_id: str
    tenant_id: str
    user_id: str
    trace_id: str
    payload: dict
    created_at: datetime


class Span(BaseModel):  # 观测骨架
    span_id: str
    trace_id: str
    parent_span_id: str
    name: str
    start: datetime
    end: datetime
    duration_ms: int
    status: str
    error: ErrorInfo | None
    attributes: dict  # model/tokens/cost/tool_ref/...（脱敏后）
```

## 2.3 生命周期与存储

- Run/Step 状态存 PostgreSQL（`agent_runs` / `agent_steps`，§27）；Checkpoint 存 PG（小）+ S3（大 artifact）；Event 写 `event_ledger`（与状态同事务）；Trace 写 OTel 后端。
- 崩溃恢复：从最后 Checkpoint 重放，工具副作用由幂等键保证**至多一次**（§10）。

## 2.4 关键不变量

1. 状态只经 `StateMachine.transition()` 变更（带守卫 + 乐观锁 CAS），禁止直接改字段。
2. 同一 run 只有一个执行者：Redis 锁 + Lease/Heartbeat（§10/§11 Zombie 检测）。
3. 工具副作用至多一次：幂等键（§6）。
4. 版本集在 Run 创建时冻结，运行中不漂移（§22）。
5. UNTRUSTED 数据永远隔离（§15）：RAG/网页/工具结果/记忆不是指令。

---

---

# 第三部分：Agent State Machine

## 3.1 为什么是正式状态机

Run 不是 "PENDING→RUNNING→SUCCESS/FAILED"。它要处理**取消竞态、暂停/恢复、超时、审批阻塞、崩溃恢复**——没有显式状态机，多 Worker 并发改状态必然错乱。

## 3.2 状态全集

```
PENDING（已入队）→ RUNNING（执行中）
RUNNING → PAUSING（收尾当前步）→ PAUSED（不耗预算）→ RESUMING（装载检查点）→ RUNNING
RUNNING → CANCELLING（传播取消）→ CANCELLED（终态）
RUNNING → TIMEOUT（超预算/超时）→ TERMINATING（清理资源/取消下游）→ FAILED | CANCELLED | UNKNOWN
RUNNING → UNKNOWN（副作用工具超时，结果未知）→ SUCCESS | FAILED（查询第三方后收敛）
RUNNING → SUCCESS（终态）；→ FAILED（不可恢复，终态）
```

## 3.3 合法状态转换与竞态收敛

```
PENDING → RUNNING
RUNNING → CANCELLING | PAUSING | TIMEOUT | FAILED | SUCCESS | UNKNOWN
CANCELLING → CANCELLED | TIMEOUT
PAUSING → PAUSED | CANCELLING
PAUSED → RESUMING | CANCELLING | TIMEOUT
RESUMING → RUNNING | FAILED
TIMEOUT → TERMINATING
TERMINATING → FAILED | CANCELLED | UNKNOWN
UNKNOWN → SUCCESS | FAILED
```

**竞态处理（§"取消与 Step 完成同时发生"）**：状态转换必须**原子 + 乐观锁 CAS**：

```sql
UPDATE agent_runs SET state='CANCELLING', version=version+1
WHERE run_id=$1 AND state='RUNNING' AND version=$2
-- 影响行数=0 => 状态已变，重读决策
```

谁先提交谁生效；后到一方读新状态走补偿（已完成副作用由幂等键保证不重复，§6）。状态机实现要点：唯一 `transition()` 入口、守卫、历史审计、终态无出边。

## 3.4 UNKNOWN 状态（企业级必须支持）

工具"请求已发出但超时"时**不知道第三方是否成功**，不能简单标 FAILED：

```
工具请求发出 → 网络超时 → 状态=UNKNOWN
  → 工具 reconcile(call_id) 查询第三方 → SUCCESS / FAILED
  → 无法查询 → 保留 UNKNOWN + 告警 + 人工介入
```

`ToolDefinition.reconcile` 是**可恢复副作用工具**的必需接口（§6）。

---

# 第四部分：Execution Engine

## 4.1 执行模型

```
User Input → Context Assembly → Policy Check → Planner/LLM（Model Router）
  → Tool Selection → Tool Execution（§6 全管线）→ Observation → State Update
  → 是否继续？ Yes→Planner / No→Final Answer
```

## 4.2 并发模型

- 每个 Run 一个执行器协程；Run 内 Step 串行（语义正确的前提）。
- Step 内 Tool 并行（有界并发，默认 4）；声明依赖的工具串行（§6）。
- Run 间水平并行：Executor 无状态，`acquire_run` Redis 锁保证单执行者。
- 全局有界并发：信号量限制并发 Run，超水位进队列（§11）。

## 4.3 执行循环（伪代码）

```python
async def execute_run(run, deps):
    await acquire_run_lock(run.run_id)  # 单执行者
    sm = StateMachine(run.state)
    ctx = ExecutionContext(run, CancellationToken(), Deadline(run.deadline))
    spent = BudgetSpent()
    while not sm.is_terminal():
        if BudgetGuard(run.budget).check(spent).exceeded:  # §18
            sm.transition(TIMEOUT)
            break
        if ctx.token.cancelled:  # §10
            sm.transition(CANCELLING)
            await propagate_cancel(ctx)
            break
        result = await deps.llm.complete(LLMRequest(...))  # 可取消
        spent.accumulate(result)
        if result.tool_calls:
            for tc in result.tool_calls:
                spent.tool_calls += 1
                obs = await deps.tool_runtime.execute(tc, ctx)  # §6 全管线
                ctx.messages.append_tool_result(obs)
            if loop_detected(ctx):
                sm.transition(FAILED, LOOP_DETECTED)
                break
        else:
            sm.transition(SUCCESS)
            break
        await checkpoint(run, spent)  # §10：每步后打点
    await finalize(run, sm.state, spent)
```

## 4.4 执行预算（防死循环 + 成本闸）

| 维度 | 默认 | 触发 |
|---|---|---|
| max_steps | 30 | TIMEOUT |
| max_tokens | 200k | 停止下一次 LLM |
| max_cost | ¥10 | 停止，可配审批放行 |
| max_tool_calls | 50 | 不再接受新工具 |
| max_wall_time | 600s | 强杀协程 + TERMINATING |
| max_retries | 3 | 超即 FAILED |

**死循环检测**：`(意图摘要, 工具名, 参数指纹)` 连续 N 步相同 → 判定循环 → 中断 + 告警。

## 4.5 失败处理（§9/§26 错误体系）

- 可重试：超时/429/5xx/网络 → 指数退避 + 抖动重试（上限内）。
- 不可重试：参数错误/权限拒绝/业务错误 → FAILED（保留现场）。
- 一律映射统一错误模型：`ErrorCode / ErrorType / Retryable / UserVisible / InternalMessage / Cause / TraceID`。

---

# 第五部分：Context Engine

## 5.1 为什么存在

Context 是"模型看到什么"，同时决定**生成质量**（token 预算）与**安全**（注入防护、数据隔离）。Context Engine 把拼 prompt 抽成有预算、有信任分级、可审计的管线。

## 5.2 Context 类型与信任分级

| 类型 | 来源 | 信任级 | 默认预算占比 |
|---|---|---|---|
| system | 平台/Agent 作者配置 | **TRUSTED** | 低但优先 |
| user | 用户本轮输入 | TRUSTED（本会话） | 中 |
| task | 任务目标/工具清单 | TRUSTED | 中 |
| history | 会话历史 | TRUSTED（会话内） | 中 |
| memory | Memory 召回 | **UNTRUSTED** | 低 |
| knowledge | RAG/Graph 检索 | **UNTRUSTED** | 高 |
| tool | 工具结果 | **UNTRUSTED** | 中 |
| observation | 检测后的观察摘要 | TRUSTED | 低 |

**核心原则：UNTRUSTED 数据永远是数据，绝不与指令混排**（§15 多层防御第一道墙）。

## 5.3 ContextBlock 结构

```python
class ContextBlock(BaseModel):
    block_id: str
    ctx_type: ContextType  # SYSTEM/USER/TASK/HISTORY/MEMORY/KNOWLEDGE/TOOL/OBSERVATION
    trust: TrustLevel  # TRUSTED / UNTRUSTED
    source: str  # 块来源（kb:doc#chunk），引用/审计用
    priority: int  # 预算裁剪保留优先级
    tokens: int
    text: str
    meta: dict  # provenance / 权限 / 时间
```

## 5.4 Builder 管线

```
collect(system/task/history/memory/retrieval/tool/observation)
  → filter_by_policy（组装前！）→ dedupe → rank
  → budget_truncate（整块取舍，绝不半块截断）→ inject_detection（UNTRUSTED 标注）
  → assemble（按 trust 分区 + 引用编号）
```

- **预算**：`max_context_tokens`（默认窗口 60%）；按类型上限；溢出按 priority 整块丢弃；同输入同配置同顺序（可复现）。
- **防污染/防注入/防泄漏/防 lost-in-middle**：指令放首尾、证据按分排序、块数 ≤20、权限过滤在检索层（§16）、UNTRUSTED 块 masking（§15）。

---

---

# 第六部分：Function Calling / Tool Runtime

## 6.1 核心论断

**Function Calling ≠ 直接执行。** LLM 输出的 `tool_calls` 是"意图"，不是"命令"。中间隔着裁决链：

```
LLM → Tool Call → Tool Registry → Policy Engine → Permission
  → Argument Validation → Quota/Rate Limit → Risk/Approval
  → Sandbox/Execution → Result Validation → Observation → LLM
```

## 6.2 Tool 契约

```python
class ToolDefinition(BaseModel):
    ref: str
    name: str
    description: str
    input_schema: dict  # JSON Schema（参数校验 + 暴露给 LLM）
    output_schema: dict | None  # 输出校验
    permission: str  # 权限点，如 "crm:order:read"
    risk_level: READ | WRITE | SIDE_EFFECT | ADMIN
    timeout_s: float
    retry_policy: RetryPolicy
    idempotency_policy: IdempotencyPolicy
    cost: ToolCost
    tenant_scope: bool  # 是否需要主体身份
    kind: FUNCTION | HTTP | MCP | DB | BROWSER | CODE | SHELL | FILE | SEARCH | RAG | GRAPH
    status: DRAFT | ACTIVE | DEPRECATED | DISABLED
    version: str
    reconcile: Callable | None  # UNKNOWN 状态查询第三方（§3.4）
```

**风险分级**：

| 级 | 例子 | 控制 |
|---|---|---|
| READ | 查询订单、检索 | 权限 + 限流 |
| WRITE | 创建订单 | 权限 + 幂等键 |
| SIDE_EFFECT | 支付、发邮件 | 权限 + 审批 + 幂等键 + 可查账 |
| ADMIN | 删数据、改权限、发布 | 权限 + 审批 + 双人复核 |

## 6.3 执行管线（全量）

```
1 resolve（TOOL_NOT_FOUND）→ 2 status（ACTIVE）
→ 3 permission（PolicyEngine default-deny，TOOL_PERMISSION_DENIED）
→ 4 argument validation（JSON Schema + 业务，TOOL_INVALID_ARGUMENT）
→ 5 quota/rate limit（tenant:user:tool，TOOL_RATE_LIMITED）
→ 6 risk gate（SIDE_EFFECT/ADMIN → APPROVAL_REQUIRED）
→ 7 circuit breaker（TOOL_BREAKER_OPEN）
→ 8 idempotency（call_id 命中返回缓存，至多一次）
→ 9 execute（timeout + retry + sandbox + secret 注入）
→ 10 output validation（脱敏 + 注入检测）
→ 11 reconcile 注册（UNKNOWN 支持）→ 12 audit + metrics + trace
```

## 6.4 幂等键与副作用（"Tool 已产生副作用但 Agent 超时"）

```
idempotency_key = hash(tenant_id, run_id, step_id, tool_ref, canonical_args)
```

- 同 key 重复执行返回缓存结果，绝不重复副作用。
- **补偿**：`compensatable=true` 时提供撤销工具（`ticket.reopen` 补偿 `ticket.close`）。
- 超时后：状态 → UNKNOWN，凭 key 调 `reconcile()` 判定真实结果；审计成对（副作用 + 补偿/查询）。

## 6.5 参数错误处理矩阵（编排层核心决策）

| 错误 | 错误码 | 动作 |
|---|---|---|
| 参数缺失/类型/越界 | `TOOL_INVALID_ARGUMENT_*` | **回喂 LLM 修正**（每步上限 2 次） |
| 非法参数 | `TOOL_INVALID_ARGUMENT` | 拒绝 + 审计（可疑注入） |
| 工具不存在 | `TOOL_NOT_FOUND` | 回喂 LLM 换工具 |
| 权限不足 | `TOOL_PERMISSION_DENIED` | **拒绝 + 审计，不回喂**（防试探） |

## 6.6 Tool 治理与生命周期

- 治理：timeout(30s) / retry(仅幂等+瞬时) / circuit breaker(5败/60s) / rate limit / audit 强制。
- 生命周期：`DRAFT → ACTIVE → DEPRECATED → DISABLED`；不直接删工具（Trace/审计可回溯）。
- **统一抽象**：`ToolProvider（resolve/execute/health/reconcile）` 下有 FunctionProvider / HttpProvider / McpProvider；上层 Agent 不感知底层是 MCP 还是 HTTP（§7）。

---

# 第七部分：MCP 与 Skill

## 7.1 MCP ≠ Function Calling

- **Function Calling**：LLM 结构化出参 → 平台校验编排（**编排层**）。
- **MCP**：工具/资源/提示词的**发现与传输协议**（Server 如何暴露、Client 如何发现调用）。

两者正交：MCP 解决"能力如何描述与传输"，Function Calling 解决"意图如何校验与编排"。MCP Server 能力经 `McpProvider` 包装成普通 `ToolDefinition`，成为编排一员。

```
LLM → Agent Runtime → ToolProvider
                        ├─ FunctionProvider（本地函数）
                        ├─ HttpProvider（HTTP，SSRF 防护）
                        └─ McpProvider（MCP Client）→ MCP Server（stdio/SSE/HTTP Streamable）
```

## 7.2 MCP 安全（第三方 Server 默认不可信）

| 防线 | 手段 |
|---|---|
| 白名单 | `tools/list` 全量 → 过滤 → 只注册允许子集 |
| 参数/输出 | 复用平台 JSON Schema + 脱敏 + 注入检测 |
| 网络隔离 | server 网络策略（防 SSRF/内网横向） |
| Secret | 凭据经 SecretManager 注入，不落地 |
| 接入治理 | 高风险 server 需审批；来源/签名/版本留痕 |

- 连接管理：`connect → initialize → tools/list → tools/call → close`；健康探活 + 指数退避重连。
- 能力映射：`tools→ToolDefinition`、`resources→知识读取`、`prompts→Skill/Prompt 模板`。
- 工具名冲突用命名空间前缀：`tool_ref = "mcp:{server}:{tool}"`。

## 7.3 Skill（技能包）

Skill = 行为知识（指令 + 可选工具绑定 + 可选资源 + 元数据），**按需加载不常驻 Context**。

```yaml
name: customer-support-handbook
version: 3
trigger: 用户咨询 售后/退款/物流
instructions: |          # 怎么做：步骤/边界/禁忌
  ...
tools: [platform.search.web, platform.crm.ticket.create]   # 声明所需工具
permission: [action: crm.ticket:create]                    # 自身最小权限
```

- **生命周期**：`DRAFT → REVIEW → ACTIVE → DEPRECATED → DISABLED`；每版不可变（灰度/回滚）。
- **两级加载**：catalog（名称/描述/触发条件，轻量）→ 命中 → 加载全文进 Context；避免全量塞上下文。
- **信任与权限**：平台/租户自建经 REVIEW = 可信；第三方/用户上传必须审查（可能注入）。Skill 声明权限 ≤ 调用者权限否则拒绝；执行内工具仍走 ToolRuntime 全管线（审批/沙箱/审计不豁免）。
- Skill 与 RAG 关系：Skill 是"该怎么做"的知识通道，RAG 是"事实"通道。

---

---

# 第八部分：LLM Provider / Model Router

## 8.1 分层

```
Agent → Model Gateway → Scheduler → Model Pool → Provider
              │                    │
         统一入口             决策写入 Trace（为什么选这个模型）
```

- **LLM Provider Interface**：`complete(LLMRequest) -> LLMResult`，支持 OpenAI/Anthropic/DeepSeek/GLM/Qwen/本地模型，不绑定厂商。
- 统一度量：token（in/out/cached/reasoning）、cost、latency、request_id、错误归一化（`MODEL_TIMEOUT/429/5xx`）。

## 8.2 Model Router

输入：TaskComplexity · ContextSize · ToolCount · RiskLevel · LatencyBudget · CostBudget · TenantTier · ModelHealth · Quota。

```
Capability Filter（匹配任务分级）→ Health Filter（排除 Unavailable）
  → Quota Filter → Cost Filter → Latency Filter → Load Balance
```

**任务分级（Model Tier）**：

| 级 | 任务 | 档位 |
|---|---|---|
| L0 | 规则任务 | 不调 LLM |
| L1/L2 | 分类/简单问答 | Small |
| L3 | 复杂 RAG | Medium |
| L4 | 复杂 Agent Planning | Large |
| L5 | 高风险决策 | Strong + Guardrail + Human Review |

**Dynamic Routing**（不写死"永远用 GPT-X"）：实时看 latency/error/429/quality/quota/provider health 动态调流。

**Model Escalation**（小模型先处理）：`Small → confidence≥θ → 返回；否则 → Medium → Large / 拒答转人工`。Escalation 链写 Trace，成本可归因。

## 8.3 LLM 限流与超时

- 限流：Global/Model/Tenant/User 四层；Token Bucket / Semaphore；不能让请求无限堆进 Worker（§11 背压）。
- 超时：分层 Timeout + Deadline 传播（§9），LLM HTTP 请求支持连接取消（§10，不再耗 token/连接/费用）。

---

# 第九部分：Timeout / Retry / Circuit Breaker / Degradation

## 9.1 分层 Timeout（数字按 SLA 评测定，不照抄）

| 层 | 默认 | 说明 |
|---|---|---|
| API | 30s | 网关层 |
| Agent | 5min | Run 总墙钟 |
| Step | 60s | 单次循环 |
| LLM | 30s | 含连接取消 |
| Tool | 10s | 含沙箱强杀 |
| RAG | 5s | 检索 |
| Queue | — | 任务租约/可见性 |

**Deadline 传播**：子调用 `deadline = min(parent.deadline, now + 本层预算)`，绝不无限等待。

## 9.2 Retry

```
可重试：Timeout / 429 / 临时 5xx / 网络抖动
不可重试：InvalidParameter / PermissionDenied / BusinessError
策略：Exponential Backoff + Jitter，max_attempts=3
```

- **Retry Storm 防护**：全局退避上限 + 请求去重 + 熔断优先于重试。
- 副作用工具**不自动重试**（靠幂等键，§6）。

## 9.3 Circuit Breaker

```
CLOSED → 错误率/慢调用超阈值 → OPEN（快速失败）→ 冷却 → HALF_OPEN（试探）
  → 成功 → CLOSED / 失败 → OPEN
```

按 Provider 与 Tool 分别熔断；熔断事件写 Trace + 审计 + 告警。

## 9.4 Degradation（Fail Gracefully）

```
Large → Medium → Small → Cached Result → Rule Based → Graceful Failure（拒答+可选项）
RAG 挂 → 关键词检索 → 拒答；Graph 挂 → 向量检索；Reranker 挂 → 原始 RRF 顺序
```

**绝不硬编**：检索为空/低分 → 显式拒答或降级。每次降级写 Trace（`degradation` 事件）。

---

# 第十部分：Cancellation / Pause / Resume / Checkpoint

## 10.1 Cancel 是一等能力

用户点 Cancel ≠ 改字段。后台 Worker 可能仍在跑：

```
Cancel API → Task.state=CANCELLING → CancellationToken
  → ExecutionContext → 传播到 LLM/Tool/RAG/Queue → 停止执行
  → Cleanup（取消下游/释放资源/审计）→ CANCELLED
```

```python
class CancellationToken:
    cancelled: asyncio.Event

    def cancel(self):
        self.cancelled.set()

    async def wait(self):
        await self.cancelled.wait()


class ExecutionContext:
    run: Run
    token: CancellationToken
    deadline: datetime
    trace_id: str
```

## 10.2 Cancellation Propagation

- **LLM 取消**：HTTP 请求支持 abort/取消——用户取消后不再耗 token/连接/费用；Request 带 `request_id`。
- **Tool 取消**：可取消工具（Search/RAG/HTTP GET/DB Query/Embedding）→ 信号直传；**不可简单取消工具**（Payment/Order/Email/DB Write）→ 不取消执行，标 UNKNOWN + 幂等键兜底。
- **Queue 取消**：取消标记传播到 Worker（幂等处理，§11）。

## 10.3 Pause / Resume

```
RUNNING →(Pause)→ PAUSING（当前步收尾）→ PAUSED（不耗预算）
PAUSED →(Resume)→ RESUMING（装载检查点）→ RUNNING
```

暂停发生在 **Step 边界**（不在工具执行中途切），保证可恢复语义；暂停/恢复事件化 + 审计。

## 10.4 Checkpoint / Resume

```
Step1 SUCCESS → Step2 SUCCESS → Step3 SUCCESS → Step4 RUNNING → Step5 PENDING
                                        │ Worker 崩溃
                                        ▼
                  重启 → Load Checkpoint → 重放 Step4（工具按幂等键跳过）
```

- **Checkpoint 内容**（不存整个巨大 Context）：`completed_steps / current_step / run_state / variables / tool_results（幂等缓存）/ trace_id`。
- 每步后打点；重放语义：LLM 重做（记录请求），工具按幂等键**至多一次**。
- **Zombie 检测**：Lease(30s) + Heartbeat + Visibility Timeout——锁过期即重入队（§11）。

## 10.5 竞态收敛

状态变更走乐观锁 CAS（§3.3）；取消传播尽力而为——即使取消迟到（Step 已完成），副作用由幂等键保证不重复，Run 终态由 CAS 裁决。

---

---

# 第十一部分：Queue / Scheduler / Backpressure

## 11.1 为什么需要队列

Agent 不能全部同步执行。异步面：Document Ingestion、Embedding、Rerank、Graph Construction、Evaluation、Long Running Agent、Async Tool、Batch。

```
Producer → Message Queue → Scheduler → Worker Pool → Result Store
                    │
           Retry Queue · DLQ · Delay Queue
```

## 11.2 Job State Machine（禁止用 boolean）

```
CREATED → QUEUED → RUNNING → SUCCEEDED
              │        │  ↘ RETRYING → RUNNING
              │        │  ↘ WAITING（依赖/审批）
              │        ▼
              │      FAILED → DEAD_LETTER（重试耗尽）
              ▼
            CANCELLED / EXPIRED
```

## 11.3 队列治理（"队列堆积怎么办"）

- **容量上限 + Admission Control**：`<50% 正常 / 50-70% 告警 / 70-85% 限流 / 85-95% 仅高优 / >95% 拒绝低优`。
- **优先级**：P0 用户实时 > P1 后台任务 > P2 普通 > P3 离线评测/索引。
- **公平性**：Per-Tenant Queue + 配额 + Weighted Scheduling，防一个大租户占满 Worker；**Aging**（等待越久优先级越高）防饿死。
- **Zombie 防护**：Lease + Heartbeat + Visibility Timeout——Worker 崩溃 → 租约过期 → 重入队。
- **DLQ + 告警**：重试耗尽进死信队列，不静默丢失。
- **Backpressure**：生产速度 > 消费速度 → 降生产/加消费者/降优先级/丢弃低价值/暂停非核心。

## 11.4 指标

`queue_depth / consumer_lag / processing_rate / failure_rate / retry_rate / dlq_depth`；P0 饥饿告警。

---

# 第十二部分：Memory

## 12.1 定位

Memory 独立于 RAG：RAG 管外部文档，Memory 管个体经验。

## 12.2 分类与隔离

| 类型 | 作用域 | 生命周期 |
|---|---|---|
| Working | Run | Run 内 |
| Conversation | Session | 会话（近轮原文 + 旧轮摘要） |
| Episodic | User | 短~中 |
| Semantic | User/Agent/Tenant | 长 |
| Preference | User | 长 |

**严格隔离**：tenant + user + session + run；Repository 层强制注入 scope，**先钉死 scope 再做相似度**——User A 不能召回 User B 记忆，即使 embedding 最相似。

## 12.3 写入也要策略（Memory Poisoning 防护）

Memory 写入需过 Policy + 注入检测 + 敏感检测；`source_trust` 分级（用户明确表达=可信，网页自动提炼=不可信）。recall 结果进 Context 的 **UNTRUSTED 分区**（§15）。

---

# 第十三部分：RAG（Knowledge Capability）

## 13.1 定位与管线

RAG 是 Knowledge Layer 的一种检索能力（非系统核心，ADR-03）。可插拔、可替换。

```
索引期：Document → Parse → Clean → Structure → Chunk → Embedding → Index（向量+倒排）
查询期：Query → Query Rewrite → Permission Filter → Hybrid Retrieval
     → RRF → Rerank → Context Assembly → LLM
```

## 13.2 Chunk 元数据（不是附属信息）

```
chunk_id / document_id / version / tenant_id / workspace_id / source
title / section / page / language / created_at / updated_at
permission / access_level / parent_id / position / hash
```

元数据是检索/权限/审计/增量更新/引用/排障的基础。

## 13.3 分块

- 结构感知（Heading/Paragraph/Table/Code/List）+ 递归/语义/父子分块。
- 推荐：**Small Child 检索（256-512 token）+ Parent 上下文（1000-2000 token）**。
- 块大小/overlap 必须通过评测集确定（§21）。

## 13.4 混合检索与 Rerank

```
Vector top-50 + BM25 top-50
  → RRF 融合：score(d)=Σ 1/(k+rank(d))，k=60
  → Top 20 → Cross-Encoder Rerank → Top 5~10 → Context
```

- **Rerank 漏斗**：绝不 `百万 → 全量 rerank`。
- **权限前置**：检索**前**按权限过滤，绝不让越权内容进入上下文再靠 LLM 判断。

## 13.5 增量更新与版本

```
Document Hash → Diff → 变更 Section/Chunk → 只 Embed 变更块 → 按来源整体替换
```

- Embedding 幂等（text_hash 缓存）；删除按来源 id。
- **Knowledge Version**：Run 绑定 knowledge_version，保证"同一问题今天/昨天结果为何不同"可解释。

## 13.6 关键坑

- 分块质量决定上限（结构感知 + 父子分块首选，参数过评测集）。
- 纯向量对代码符号/专有名词/条款号弱 → 必须混合检索。
- RAG 文档是 **UNTRUSTED 数据**：进 Context 单独分区，绝不拼进 system prompt。
- 百万级性能单独成章（§24）。

---

# 第十四部分：Knowledge Graph

## 14.1 定位

Graph 不是 RAG 子模块，是独立 Knowledge Capability。但**不要盲目建图**：只有"跨实体全局性问题"（组织关系、上下游、多跳）才值得；普通 FAQ 用 RAG。

```
Docs → Entity Extraction → Normalization → Resolution → Relation Extraction
  → Linking → Graph Validation → Storage → Retrieval（子图/多跳/社区）
```

## 14.2 Provenance 是硬要求

每条事实必须可审计：

```
Relation: Company —CEO→ Person
  source_document: doc-123; source_chunk: chunk-456; document_version: 7
  confidence: 0.92; extracted_by: model-x; created_at: 2026-08-20
```

回答不了"谁说的/哪个版本/多大把握/何时有效"的图，不能上生产。

## 14.3 时间有效性 + 冲突（"Graph 出现错误关系"）

- 时间敏感事实用 `valid_from / valid_to`（CEO 会换届），**不直接覆盖**。
- 冲突仲裁：`confidence × source_trust × recency`，胜出 ACTIVE，其余 SUPERSEDED（保留供审计/回滚）；无法自动判定 → 人工仲裁队列。
- 错误关系修正 = 按来源版本标记 SUPERSEDED（回滚复用同一机制）。

## 14.4 增量与删除

- 增量：按来源文档版本重抽取受影响子图。
- 删除：按来源整体标记失效；用户删除数据后 Vector/Graph/Cache/Memory/索引必须最终删除（§26）。

---

---

# 第十五部分：Security / Prompt Injection / Data Security

## 15.1 核心思想

**所有外部内容 = UNTRUSTED DATA**：用户输入、RAG 文档、网页、Graph、Tool Result、第三方 API、Memory、文件。

**绝对不能把外部内容拼进 System Prompt。** 必须：

```
System Instructions（TRUSTED）

<context>（UNTRUSTED DATA，模型只当数据，不当指令）
  [1] (source) chunk 文本
  [2] (source) 工具返回
</context>
```

## 15.2 多层防御（不靠单个 Prompt）

| 层 | 防御 | 落地 |
|---|---|---|
| L1 | 输入检测（注入特征） | Gateway / Ingest / Context |
| L2 | Trust Boundary（信任分级） | Context Engine |
| L3 | Instruction/Data 分离 | Context 分区 |
| L4 | Tool Permission（default-deny） | Policy Engine |
| L5 | 参数校验 + 输出校验 | Tool Runtime |
| L6 | 敏感数据 Filter/Mask | 敏感数据层 |
| L7 | Audit + 告警 | Audit |

**关键认知**：Prompt Injection 的最终风险不是"模型说奇怪的话"，而是**模型被诱导调用危险 Tool**。所以 **Tool Permission > Prompt**。

## 15.3 敏感数据

- **分类**：PUBLIC / INTERNAL / CONFIDENTIAL / SECRET；敏感数据**默认不进**普通日志/Trace/Prompt/Cache/训练集。
- **Mask/Redact**：Recorder 层统一脱敏（`sk-****`、`138****1234`），避免"日志脱敏了 Trace 没脱"的缝隙。
- **Secret Reference**：LLM 只见 `credential_ref`，真实凭据由 Tool Runtime 执行时注入（§6.3），绝不落地。

## 15.4 SSRF / 命令注入 / 沙箱

- HTTP 工具做 SSRF 防护（解析 DNS → 拦截内网/回环/保留地址）。
- Shell/Code/文件工具必须沙箱：进程/容器隔离、CPU/内存限制、网络策略、seccomp、超时强杀、Secret 隔离（§23.4）。

---

# 第十六部分：Multi-Tenant / User Isolation

## 16.1 原则

- **所有核心表带 tenant_id**；必要时 user_id / workspace_id / session_id / run_id。
- **服务端强制**：Repository/ORM 层自动注入 tenant scope，禁止"业务代码忘记 WHERE tenant_id"。
- 禁止只靠 `conversation_id` 查询——必须验证会话属于该用户该租户（防串会话，§"User A 访问 User B 记忆"）。

## 16.2 各层隔离

| 层 | 隔离手段 |
|---|---|
| DB 查询 | Repository 统一注入 `WHERE tenant_id=...` |
| RAG | tenant filter + 块 permission（检索前过滤） |
| Memory | tenant + user + scope 钉死再相似度 |
| Graph | facts 带 tenant，来源块权限沿 provenance 传导 |
| Cache | key 含 tenant + user/permission scope（§17.2） |
| Queue | 消息携带完整身份，Worker 重验权限（不信任 payload） |
| Object Storage | tenant prefix |
| Logs/Trace | tenant_id + user_id 全量属性 |

## 16.3 租户配额（"一个租户打爆系统"）

Tenant Quota：并发 Run、Token、Queue、Storage、Tool Calls、Rate。超配额 → 限流/降级/拒绝。每租户队列 + 权重调度防饿死（§11）。

---

# 第十七部分：Cache

## 17.1 分级（"缓存越权"）

| 类别 | 处理 |
|---|---|
| 可缓存 | Embedding（text_hash→vector，幂等）、检索结果（短 TTL + kb_version）、静态配置、模型元数据、公开知识 |
| 谨慎 | LLM Response / RAG Answer / 用户 Query（仅会话内，脱敏） |
| 禁止 | 用户私密数据、敏感信息、权限相关结果、未隔离的 Tool Result、短期授权 |

## 17.2 Cache Key 必须含隔离维度

```
❌ cache[query]
✅ cache[f"{type}:{tenant_id}:{scope}:{version_set}:{content_hash}"]
   scope = user/session/agent；version_set = kb_version+embed_version+prompt_version+model_version
```

依赖权限的内容，**permission scope 必须入 key**，否则权限窄化后命中即越权。

## 17.3 失效与 Stampede

- **Versioned Cache**：版本号翻新 key 代替全局删除（kb 升级自动产生新 key）。
- **Singleflight**：同 key 并发 Miss 只加载一次；TTL Jitter 防同时过期；热点预热。
- 命中任何缓存**先过权限校验**（缓存内容 + 已过期权限 = 越权）。

---

# 第十八部分：Cost Governance

## 18.1 成本可归因（"这个 Agent 为什么贵"）

```
Tenant → User → Agent → Run → Step → LLM Call
每层可见：input/output/cached/reasoning tokens、model、price、estimated_cost、actual_cost
```

- **estimated_cost**（下单前估算，预算预检）与 **actual_cost**（账单口径）分开字段。
- Run 绑定 `money/token/step/tool/time` 预算；超限 → Stop / Downgrade。

## 18.2 Token 持续上涨治理

监控 `Context/History/Tool Result/RAG/Output token、Steps、LLM Calls、Retry` 均值；`Token/Run` 环比上涨自动告警。

优化优先级：1 Context 压缩 → 2 History 摘要 → 3 Tool Result 压缩 → 4 RAG Top-K → 5 Prompt 压缩 → 6 去重 → 7 输出 schema → 8 Max Output → 9 Step Limit → 10 Model Routing。

**禁止把完整历史每次全量发给 LLM**（成本黑洞 + lost-in-middle）。

## 18.3 三维约束

任何优化必须回答 **Quality / Latency / Cost** 各变化多少；不做只看延迟不看成本的优化。

---

---

# 第十九部分：Observability / Trace / Logs / Metrics

## 19.1 三支柱

Logs + Metrics + Traces + Events 从第一天设计。

## 19.2 Trace 结构

```
Run
 ├── Planning → LLM
 ├── Tool Call → RAG → Query Rewrite → Vector Search → BM25 → RRF → Rerank
 ├── Tool Call → API
 └── Final LLM
```

每个 Span：`start/end/duration/status/error/input(脱敏)/output(脱敏)/model/tokens/cost`。必带属性：`trace_id/span_id/parent_span_id/tenant_id/user_id/session_id/agent_id/agent_version/run_id/step_id/model/prompt_version/tool_ref/call_id/knowledge_version`。

## 19.3 采样与指标

- **元数据全量**（ID/耗时/状态/属性），**payload 采样**（prompt/输出默认 10%，可配 100%）；敏感字段 Recorder 层统一脱敏。
- 线上指标：Success/Error/Fallback/Timeout/Cancellation/Tool Failure 率、RAG Empty/Low Score 率、引用准确率、Like/Dislike、Token/Cost、P95/P99。

---

# 第二十部分：Developer Debugging System

## 20.1 目标（"线上一次诡异错误，5 分钟复盘"）

5 分钟内定位：问题在哪、为什么、哪个 Step/Tool/Model/Version/User/Tenant/Knowledge/Prompt。用户投诉"说错了" → 判别是 **Retrieval / Tool / Model / Prompt / Memory / Knowledge / Permission** 七类。

## 20.2 Run Timeline

```
10:01:01 Run Started → 10:01:02 Planner Started → 10:01:03 LLM Request
10:01:08 LLM Response → 10:01:09 Tool Call → 10:01:10 RAG → Rerank
10:01:13 Tool Response → 10:01:14 LLM Started → 10:01:30 Timeout
```

直接看到：哪里慢、哪里失败、哪里重试、哪里取消、哪里降级、哪里产生大量 token。

## 20.3 定位方法

1. `trace_id` → Trace 瀑布 → 最慢/失败 span → payload。
2. 审计交叉验证（权限拒绝/审批/越权）。
3. **Replay**：原样/换参/分步重放 + Diff（换 prompt/model/检索/tool 找变量）。
4. 成本下钻：Tenant→Agent→Run→LLM Call（§18）。

## 20.4 每 Run 必答清单（20 问）

从 run_id 必须能答：哪个 Agent/Prompt/Model 版本、为什么选这个模型、检索到什么、用了哪些 Context、调了哪些 Tool、返回什么、多少 token/钱、哪步最慢/失败、是否重试/降级/熔断/缓存命中、用户权限、是否串会话、能否 Replay。

---

# 第二十一部分：Evaluation Platform

## 21.1 评测维度

- **Retrieval**：Recall@K / Precision@K / MRR / NDCG。
- **Generation**：Faithfulness / Answer Relevance / Answer Correctness。
- **Citation**：Citation Accuracy / Completeness。
- **Agent**：Task Success / Tool Selection & Argument Accuracy / Planning / Step Count / Loop Rate / Failure Recovery / Cost / Latency。
- **Security**：Prompt Injection 成功率、权限绕过、越权、跨租户、敏感泄露（Adversarial Dataset）。

## 21.2 评测集类型

| 集 | 来源 | 用途 |
|---|---|---|
| Golden | 人工标注 | 主指标 |
| Adversarial | 专门攻击 | 安全/健壮性 |
| Regression | 生产 bad-case + 修正 | 防止改代码回退 |
| Production | 真实问题脱敏采样 | 线上质量 |

评测框架：检索用规则（gold chunk 命中），生成用 LLM-as-judge + 人工抽样锚定；评测集 100 条起步。

## 21.3 离线 / 在线飞轮

```
离线：Golden/Regression 集 → 基线 → 改动 → 重跑 → 对比（只保留评测提升的改动）
在线：生产指标 → Bad Case → 人工标注 → 评测集 → 回归 → 改进 → 灰度 → 上线 → 监控
```

用户 Like/Dislike 进反馈系统；bad-case 自动进标注队列。

---

# 第二十二部分：Versioning / Gray Release / Rollback

## 22.1 一切可版本化（"新 Prompt/新模型质量下降"）

Agent / Prompt / Model / Skill / Tool / RAG 配置 / Chunking / Embedding / Reranker / Policy / Knowledge 全部版本化。**Run 创建时冻结版本集**：`agent + prompt + model + tool + knowledge` 版本，运行中绝不漂移。

## 22.2 灰度

```
Agent v1 → 5% → 20% → 50% → 100%
观察：Quality / Latency / Cost / Error / 用户反馈；任一恶化 → 自动停止灰度并回滚
```

## 22.3 Rollback

Rollback 不是只回代码：`Code + Prompt + Model + Tool + Agent Config + Knowledge + Schema Version（一致版本集）`。配置只增不改（新版本 = 新行），回滚 = 切换版本指针；知识版本建议用 versioned cache 切换检索版本（§17.3）。

**Release Contract**：发布前 10 项兼容性检查（API/Queue/DB/Prompt/Tool/Model/Config/Memory/Trace/Rollback）。

---

---

# 第二十三部分：Deployment / Startup / Shutdown / Drain

## 23.1 生命周期操作

`Start / Stop / Restart / Drain / Pause / Resume`。

## 23.2 Graceful Shutdown

```
Stop Accepting New Tasks → Stop Scheduling → Drain
  → Checkpoint Running Tasks → Cancel/Pause → Release Resources → Shutdown
```

- **Grace Period**（30s/60s/120s）限时；超时任务交给 Queue/Recovery，**绝不 kill 丢数据**。
- **Liveness ≠ Readiness**：LLM 挂 → Readiness 置否（摘流量），不杀进程（防 K8s 无限重启）。

## 23.3 发布不丢体验

- **Stateless Runtime**：会话/运行状态放 DB/Redis，不放进程内存。
- **Connection Draining**：旧实例停接新请求，继续处理已有 HTTP/SSE/WS/进行中 Run。
- **Message Schema 向后兼容**；**Schema Migration** 用 Expand → Migrate → Contract。
- **Feature Flag** 放量高风险功能（tenant → agent → user → percentage）。
- **Canary 自动停 + 快速 Rollback**（§22.3）。

## 23.4 Sandbox

Shell/Code/Browser/File 必须沙箱：进程/容器隔离、CPU/内存限制、网络策略、文件权限、超时强杀、seccomp、Secret 隔离。禁止 Agent 直接访问生产环境。

---

# 第二十四部分：百万级知识库性能优化

## 24.1 检索漏斗（"百万级检索变慢"）

```
百万块 → Tenant/Partition/Metadata Filter（先过滤后召回）
  → ANN（HNSW/IVF）Top-100 → RRF 融合 50 → Rerank 20~50 → Top 5~10 → Context
```

**绝不** `1,000,000 vectors 全扫描` 或 `全量 → Rerank`。

## 24.2 Partition / 分层索引

```
Tenant → Knowledge Base → Domain/Region Partition → Vector Index
查询：先确定"去哪搜"，再"搜什么"。
```

## 24.3 HNSW / IVF 用 Benchmark 定参

| 索引 | 参数 | 调优 |
|---|---|---|
| HNSW | M / efConstruction / efSearch | 数据量/Recall/QPS/延迟/内存基准 |
| IVF | nlist / nprobe | 同上 |

## 24.4 缓存分层与 Sharding

- 缓存：Query Cache（含 kb_version + permission scope + embed_version）、Retrieval Cache、Embedding Cache（text_hash）、热点预热；冷热数据分离。
- Sharding：按 `tenant_hash / kb / domain` 分片；Cross-Shard 检索 = Parallel Search → Top-K Merge → RRF → Rerank。

---

# 第二十五部分：高并发与容量治理

## 25.1 容量规划

| 规模 | 关键约束 | 变化 |
|---|---|---|
| 100 QPS | 单机 + 进程内队列 | — |
| 1K QPS | 多实例 + Redis 限流/锁 | 拆队列 |
| 10K QPS | 分区 + 连接池 + 缓存分层 | 可能拆服务 |
| 100K QPS | 专用向量库 + 消息系统 + HA | 必须拆 |

## 25.2 资源隔离与 Backpressure

- **Tenant Quota**：并发 / Token / Queue / Storage / Tool Calls / Rate。
- **Backpressure**：LLM/RAG/Embedding/Reranker/Graph 全支持；下游慢 → 上游限产。
- 队列水位限流（§11.3）、限流分层（全局/租户/用户/模型，§8.3）。

## 25.3 防无限循环

`max_steps / max_tool_calls / max_retries / max_wall_time` + 重复 Tool Call/Query/Reasoning 指纹检测（§4.4）。

---

# 第二十六部分：数据一致性与生命周期

## 26.1 一致性等级

| 数据 | 一致性 | 手段 |
|---|---|---|
| Run/Step 状态 | 强一致（CAS + 事务） | PostgreSQL + 乐观锁 |
| 工具副作用 | 至多一次 | 幂等键 + 缓存结果 |
| 缓存 | 最终一致 | TTL + Versioned Cache + Pub/Sub 失效 |
| 知识索引 | 最终一致 | 增量 Upsert，版本切换 |
| 事件 | 至少一次 + 幂等去重 | event_id |

## 26.2 数据生命周期（"用户删除数据后"）

`Create → Update → Delete → Archive → Retention`：软删 + TTL，删除前归档 S3；**用户删除数据 → Vector/Graph/Cache/Memory/对象存储/搜索索引必须最终删除**（级联清理任务）。

保留策略：审计 180d、Trace 元数据 90d、payload 快照 30d、评测集长期。

## 26.3 事务边界

- 状态转换 + 事件写入**同一事务**（先写事件再提交状态，§28 幂等）。
- 工具执行结果 + 审计尽量同事务；跨存储（PG + S3 + Redis）用 Outbox/事件驱动（先写意图后补偿）。

---

---

# 第二十七部分：数据模型与数据库设计

## 27.1 存储职责（不重复存储）

| 数据 | 载体 |
|---|---|
| 身份/Agent/版本/Session/Run/Step/工具/文档/图事实/评测/审批/审计/配置 | PostgreSQL |
| 向量 | pgvector（规模大换专用库） |
| 缓存/锁/限流/Stream | Redis |
| 全文检索 | PG tsvector → OpenSearch |
| 文档原件/快照/artifact | S3 |
| Trace/Metric | OTel 后端 |
| 密钥 | KMS / Secret Manager |

## 27.2 核心实体

Tenant / User / Workspace / Agent / AgentVersion / Session / Run / Step / Tool / ToolVersion / ToolCall / LLMRequest / Message / Memory / KnowledgeBase / Document / DocumentVersion / Chunk / Entity / Relation / Checkpoint / Job / QueueTask / Artifact / Trace / EvaluationCase / EvaluationRun / CostRecord / AuditLog / Configuration / FeatureFlag。

共性：`tenant_id` 全表、`id` UUID PK、`created_at/updated_at/deleted_at` 软删、`version` 乐观锁、唯一约束带 `tenant_id` 前缀、状态用状态机非 boolean。

## 27.3 核心表 DDL（PostgreSQL，MVP 子集）

```sql
CREATE TABLE agent_runs (
  run_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  agent_id UUID NOT NULL, agent_version INT NOT NULL, session_id UUID NOT NULL,
  state TEXT NOT NULL, budget_json JSONB NOT NULL, cost NUMERIC(12,4) NOT NULL DEFAULT 0,
  tokens_in INT NOT NULL DEFAULT 0, tokens_out INT NOT NULL DEFAULT 0,
  model_config JSONB, input_json JSONB NOT NULL, output_json JSONB,
  error_json JSONB, checkpoint_id TEXT, lock_expires_at timestamptz,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, updated_at timestamptz
);
CREATE INDEX idx_runs_tenant_state ON agent_runs (tenant_id, state, started_at);
CREATE INDEX idx_runs_session ON agent_runs (session_id, started_at);

CREATE TABLE agent_steps (
  id BIGSERIAL PRIMARY KEY, run_id UUID NOT NULL REFERENCES agent_runs(run_id),
  seq INT NOT NULL, state TEXT NOT NULL, llm_json JSONB, tool_calls_json JSONB,
  observations_json JSONB, decision TEXT, tokens_used INT, cost NUMERIC(12,4),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (run_id, seq)
);

CREATE TABLE tool_calls (
  call_id TEXT PRIMARY KEY, run_id UUID NOT NULL, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  tool_ref TEXT NOT NULL, args_json JSONB, result_json JSONB, status TEXT NOT NULL,
  risk_level TEXT, approval_id UUID, error_code TEXT, latency_ms INT, cost NUMERIC(12,4),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz
);
CREATE INDEX idx_tool_calls_run ON tool_calls (run_id, created_at);

CREATE TABLE chunks (
  chunk_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, document_id UUID NOT NULL,
  version INT NOT NULL, seq INT NOT NULL, section TEXT, source TEXT, position INT,
  text TEXT NOT NULL, token_count INT NOT NULL, permission TEXT,
  vector vector(1024), meta_json JSONB, hash TEXT,
  UNIQUE (tenant_id, document_id, version, seq), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_text_gin ON chunks USING GIN (to_tsvector('simple', text));

CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY, tenant_id UUID NOT NULL, trace_id TEXT, actor_id UUID,
  action TEXT NOT NULL, resource TEXT, resource_id TEXT, outcome TEXT NOT NULL,
  detail_json JSONB, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_time ON audit_logs (tenant_id, created_at DESC);

CREATE TABLE policies (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, name TEXT, effect TEXT CHECK (effect IN ('ALLOW','DENY')),
  action TEXT NOT NULL, resource TEXT, condition_json JSONB, enabled BOOLEAN DEFAULT TRUE,
  version INT DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz
);
CREATE INDEX idx_policies_action ON policies (tenant_id, action);
```

---

# 第二十八部分：API 与 Event Design

## 28.1 REST API

```
POST /agents                     创建 Agent
POST /agents/{id}/runs           发起 Run
GET  /runs/{id}                  查询 Run + Steps
POST /runs/{id}/cancel|pause|resume|retry
GET  /runs/{id}/trace|events
POST /tools                      注册工具
POST /knowledge/documents        导入文档
DELETE /knowledge/documents/{id}
POST /knowledge/search           混合检索
POST /evaluations                触发评测
```

统一：Authentication（网关 OIDC/JWT + mTLS）、Authorization（PolicyEngine）、Idempotency、Rate Limit、Error Code、Trace ID 透传。

## 28.2 事件模型（幂等 / 可追踪 / 可重放）

`AgentRunCreated/Started · StepStarted · LLMRequested/Completed · ToolCalled/Completed · RetrievalStarted/Completed · CheckpointCreated · CancelRequested/Propagated · RunCancelled/Paused/Resumed/Completed/Failed`

- 事件 = `event_id`（幂等去重）+ `run_id/step_id/trace_id` + payload + 时间。
- 事件写 `event_ledger`（与状态同事务，§26.3），供审计/重放/订阅（Webhook/Stream）。

---

# 第二十九部分：错误体系

统一错误模型：`ErrorCode / ErrorType / Retryable / UserVisible / InternalMessage / Cause / TraceID`。

| 错误 | 语义 | Retryable | HTTP |
|---|---|---|---|
| AGENT_TIMEOUT / AGENT_CANCELLED | 超时/取消 | 否 | 429/200 |
| MODEL_TIMEOUT / MODEL_RATE_LIMIT | LLM 超时/限流 | 是 | 504/429 |
| TOOL_NOT_FOUND | 工具不存在 | 否 | 404 |
| TOOL_PERMISSION_DENIED | 权限拒绝 | 否 | 403 |
| TOOL_INVALID_ARGUMENT | 参数非法 | 否 | 400 |
| TOOL_TIMEOUT / TOOL_EXECUTION_FAILED | 工具失败 | 是/否 | 504/500 |
| TOOL_RATE_LIMITED | 限流 | 否 | 429 |
| APPROVAL_REQUIRED | 需审批 | 否 | 402 |
| RAG_EMPTY / RAG_LOW_CONFIDENCE | 检索空/低分 | 否 | 200(降级) |
| POLICY_DENIED / TENANT_ACCESS_DENIED | 策略/越权 | 否 | 403 |
| BUDGET_EXCEEDED | 超预算 | 否 | 429 |
| AGENT_LOOP_DETECTED | 死循环 | 否 | 500 |
| UNKNOWN | 副作用结果未知 | 否 | 200(可查询) |

每个错误必须可观测（Trace + Audit），可 Replay。

---

# 第三十部分：测试与 Chaos Engineering

## 30.1 测试金字塔

Unit（状态机/预算/契约）→ Integration（Runtime 全流程 + DB）→ E2E（API）→ Load（QPS/延迟）→ Chaos → Security（注入/越权样本）。

重点场景：LLM Timeout/429、Tool Timeout、Worker Crash、DB Failure、Queue Backlog、Cancel Race、Duplicate Tool Call、Cross-Tenant、Prompt Injection、Cache Leakage、Deployment、Rollback。

## 30.2 Chaos Engineering

主动注入：LLM 慢/失败/限流、Vector DB 慢、Graph DB 慢、Redis 故障、Queue 堆积、Worker Crash、网络抖动、第三方 API 失败。

观察系统是否：降级 / 恢复 / 回滚 / 清理资源 / 保持数据一致性。每轮 Chaos 出具报告，作为发布门禁。

---

---

# 第三十一部分：项目目录与代码架构

```
agent-platform/
├── api/                    # REST 路由（agents/runs/tools/knowledge/evaluations）
├── runtime/
│   ├── execution/          # 执行引擎（§4）：循环、预算、死循环检测
│   ├── scheduler/          # 调度（§11）：优先级、公平、背压
│   ├── state/              # 状态机（§3）：转换表 + CAS
│   ├── cancellation/       # 取消/暂停/恢复（§10）
│   ├── checkpoint/         # 检查点/恢复（§10）
│   ├── retry/              # 重试策略（§9）
│   ├── timeout/            # 分层超时 + Deadline（§9）
│   └── budget/             # 执行预算（§18）
├── llm/                    # provider/ / router/ / limiter/ / circuit_breaker/ / cost/
├── tools/                  # registry/ / policy/ / executor/ / sandbox/ / validation/
├── knowledge/              # rag/ / graph/ / memory/ / permission/
├── queue/                  # scheduler/ / worker/ / retry/ / dlq/
├── security/               # auth/ / authorization/ / injection/ / pii/ / audit/
├── observability/          # tracing/ / metrics/ / logging/ / events/
├── evaluation/             # dataset/ / runner/ / judge/ / regression/
├── storage/                # DB/Redis/S3 访问 + 隔离注入
└── config/                 # 版本化配置 + Feature Flag
```

遵循 **Modular Monolith First**：模块边界严格（单向依赖 + import-linter），出现性能瓶颈/团队边界/资源隔离/部署需求再拆服务。

---

# 第三十二部分：MVP → Production → Enterprise 演进路线

| Phase | 范围 | 交付物 |
|---|---|---|
| Phase 1 单体 Runtime | LLM + Function Calling + Tool + State Machine + RAG + Trace + Evaluation | 可跑通对话+工具+检索+评测 |
| Phase 2 生产治理 | Tenant + Permission + Timeout + Retry + Circuit Breaker + Cancellation + Checkpoint + Cost | 可上线内部试用 |
| Phase 3 高并发 | Queue + Scheduler + Rate Limit + Backpressure + Model Router + Cache | 可支撑外部流量 |
| Phase 4 Knowledge Platform | RAG + Graph + Memory + Hybrid Retrieval | 知识能力完整 |
| Phase 5 企业治理 | Evaluation Platform + Security + Audit + Gray + Rollback + HA/多区域 | 生产级 |

**排期建议（3~5 人团队）**：
- **P0（生产必须有，~8 周）**：Runtime 状态机/预算/取消、Tool 全管线（权限/幂等/审计）、PolicyEngine 默认拒绝、Trace、崩溃恢复、评测雏形（Recall@k）。
- **P1（强烈建议，~4 周）**：队列 + 调度 + 限流 + 熔断降级 + 模型路由 + 检查点续跑 + 敏感数据脱敏。
- **P2（规模化后）**：Graph、百万级分片、灰度/AB、在线评测飞轮、Sandbox/审批流、混沌工程。
- **P3（未来）**：多区域 HA、专用向量库/图库、MCP 生态网关、Agent 市场。

> 先把 **Runtime 内核**打磨到"能安全、可观测、可恢复地运行"，再谈外部能力。不要第一天上 Kafka/K8s/Milvus/Neo4j/几十个微服务。

---

# 附录 A：核心"如果……怎么办"问答

| # | 场景 | 答案（章节） |
|---|---|---|
| 1 | LLM 挂了 | 熔断（§9.3）+ 降级链（§9.4）；Liveness≠Readiness 摘流量不杀进程（§23.2） |
| 2 | LLM 很慢 | 分层超时 + Deadline（§9.1）；Model Router 切同档更快模型（§8.2） |
| 3 | LLM 被限流 | 退避重试（§9.2）+ 换 provider（§8.3）；429 熔断统计 |
| 4 | Tool 挂了 | 熔断 + 超时 + 审计（§6.5）；降级换工具/拒答（§9.4） |
| 5 | Tool 已产生副作用但超时 | 幂等键（§6.4）+ UNKNOWN（§3.4）+ reconcile 查询；补偿可撤销 |
| 6 | 执行一半用户取消 | CancellationToken 传播（§10）；LLM abort 不再耗 token/连接 |
| 7 | Cancel 与 Step 完成同时发生 | 乐观锁 CAS 收敛（§3.3/§10.5）；副作用靠幂等键不重复 |
| 8 | Worker 崩溃 | Checkpoint + 重启装载 + 幂等重放（§10.4）；Zombie 靠 Lease 重入队（§11.3） |
| 9 | 服务正在发布 | Stateless + Drain + Connection Draining + Schema 兼容 + Canary（§23.3） |
| 10 | 队列堆积 | 水位限流 + 背压 + 降优先级 + DLQ（§11.3） |
| 11 | 一个租户打爆系统 | Tenant Quota + 每租户队列 + 权重调度（§16.3/§25.2） |
| 12 | User A 命中 User B 缓存 | Cache Key 含隔离维度（§17.2）+ 命中先过权限校验 |
| 13 | RAG 文档含注入 | UNTRUSTED 分区（§15.1）+ 多层防御（§15.2）+ 工具权限兜底 |
| 14 | Graph 错误关系 | Provenance + 冲突仲裁 + SUPERSEDED 回滚（§14.2/§14.3） |
| 15 | 知识库更新 | Hash Diff 增量 + 按来源替换 + Knowledge Version（§13.5/§26.3） |
| 16 | 百万级检索变慢 | 过滤前置 + Partition + ANN + Rerank 漏斗 + 缓存（§24） |
| 17 | Token 成本上涨 | 归因 + 告警 + 10 项优化 + 禁止全量历史（§18.2） |
| 18 | 模型价格变化 | estimated vs actual 分离 + 路由成本过滤（§18.1/§8.2） |
| 19/20 | 新 Prompt/新模型质量下降 | 版本化 + 灰度观察 + 自动停 + 回滚（§22） |
| 21 | 发布出错 | Canary 自动停 + Release Contract 检查（§22.3） |
| 22 | 快速 Rollback | 一致版本集回滚（§22.3） |
| 23 | 诡异错误复盘 | Trace 20 问（§20.4）+ Timeline + 审计 + Replay（§20.3） |
| 24 | "说错了"归因 | 判 Retrieval/Tool/Model/Prompt/Memory/Knowledge/Permission 七类（§20.1） |
| 25 | 运行半年可维护 | 模块边界 + 契约版本化 + 评测回归 + 可观测完整 + 可回滚（§1.3/§21/§26.2） |

---

# 附录 B：已实现代码说明（Phase 0–3）

本仓库 `app/` 已落地规范核心（Python/FastAPI/SQLite 起步，PG/Redis 可切）：

| 规范章节 | 已实现 | 位置 |
|---|---|---|
| §3 状态机 | AgentState 12 态 + 守卫 + 历史审计 | `app/agent/runtime/state.py` |
| §4 执行引擎 | 循环 + 预算 + 死循环指纹 + 模型退避重试 | `app/agent/runtime/runtime.py` |
| §4.4 预算 | ExecutionBudget | `app/agent/runtime/budget.py` |
| §10 取消 | 协作式取消（CancelService）+ 进程内/Redis 锁 | `app/agent/runtime/cancel.py`, `app/storage/lock.py` |
| §10.4 恢复 | 锁过期僵尸 Run 回收（RECOVERY_ABANDONED） | `app/agent/runtime/recovery.py` |
| §6 工具全管线 | ToolRegistry + JSON Schema 校验 + 幂等 + SSRF 防护 | `app/tool/registry.py` |
| §6.3 管线编排 | ToolRuntime：权限→限流→风险闸→幂等→执行→审计 | `app/tool/runtime.py` |
| §16 Policy | PolicyEngine 默认拒绝 + DENY 优先 + policies 表 | `app/security/policy.py` |
| §15.2 审计 | AuditService + audit_logs 全量落库 | `app/security/audit.py` |
| §6.3 限流 | 滑动窗口 RateLimiter（进程内/Redis） | `app/tool/limiter.py` |
| §13 RAG | 结构感知分块 + HashEmbedding + 向量/BM25 + RRF + provenance | `app/knowledge/` |
| §13.4 混合检索 | kb.search 工具（租户只信 subject） | `app/knowledge/retrieval.py` |
| §21 评测 | Recall@k/MRR/Faithfulness 脚本 + 样例 KB | `scripts/eval.py` |
| API | `/agents/runs` `/tools` `/knowledge/*` + 健康检查 | `app/agent/api/`, `app/tool/api.py`, `app/knowledge/api.py` |
| 演示 | 端到端演示（工具 + RAG + Trace + 审计） | `scripts/demo.py` |

验证：`make install && make test`（58 passed）→ `make smoke` / `make demo` / `make eval`。真实 LLM 只需 `.env` 设 `APP_LLM_PROVIDER=openai` + base_url/key。

---

> 本文档为深度合并重构版《企业级 Agent 平台技术设计规范》v0.3。覆盖平台级（架构/边界/数据模型/API）与 Runtime 工程化（状态机/执行引擎/可靠性/知识层/运营治理）全部要点；附录 C–K 保留重构中被压缩的细节（完整 DDL / 时序图 / 隔离细则 / 发布细则 / 缓存治理 / 成本调度 / 测试矩阵 / Replay / MVP 计划）。

---

# 附录 C：完整数据模型与 DDL（核心表全集）

> 通用约定：每表含 `id`（UUID PK）、`tenant_id`（NOT NULL）、`created_at/updated_at`（带 `ON UPDATE`）、`deleted_at`（软删）、`version`（乐观锁）；唯一约束一律 `(tenant_id, ...)` 前缀。

## C.1 Identity

```sql
CREATE TABLE tenants (
  id UUID PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE users (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL, display_name TEXT, status TEXT NOT NULL DEFAULT 'ACTIVE',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz,
  UNIQUE (tenant_id, email)
);
CREATE TABLE roles (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, name TEXT NOT NULL, UNIQUE (tenant_id, name)
);
CREATE TABLE members (
  tenant_id UUID NOT NULL, user_id UUID NOT NULL, role_id UUID NOT NULL,
  PRIMARY KEY (tenant_id, user_id, role_id)
);
CREATE TABLE policies (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  name TEXT NOT NULL, effect TEXT NOT NULL CHECK (effect IN ('ALLOW','DENY')),
  subject_json JSONB NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL,
  condition_json JSONB, priority INT NOT NULL DEFAULT 0, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  version INT NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE INDEX idx_policies_action ON policies (tenant_id, action);
```

## C.2 Agent / Session / Run

```sql
CREATE TABLE agents (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, owner_id UUID NOT NULL,
  name TEXT NOT NULL, slug TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
  UNIQUE (tenant_id, slug), deleted_at timestamptz
);
CREATE TABLE agent_versions (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, agent_id UUID NOT NULL REFERENCES agents(id),
  version INT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',   -- DRAFT/ACTIVE/GRAY/DISABLED
  system_prompt TEXT, config_json JSONB NOT NULL, tool_refs JSONB, model_ref TEXT,
  UNIQUE (tenant_id, agent_id, version), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE sessions (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  agent_id UUID NOT NULL, agent_version INT NOT NULL, status TEXT NOT NULL DEFAULT 'ACTIVE',
  summary TEXT, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE agent_runs (
  run_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  agent_id UUID NOT NULL, agent_version INT NOT NULL, session_id UUID NOT NULL,
  state TEXT NOT NULL, budget_json JSONB NOT NULL, cost NUMERIC(12,4) NOT NULL DEFAULT 0,
  tokens_in INT NOT NULL DEFAULT 0, tokens_out INT NOT NULL DEFAULT 0,
  model_config JSONB, input_json JSONB NOT NULL, output_json JSONB,
  error_json JSONB, checkpoint_id TEXT, lock_expires_at timestamptz,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, updated_at timestamptz
);
CREATE INDEX idx_runs_tenant_state ON agent_runs (tenant_id, state, started_at);
CREATE INDEX idx_runs_session ON agent_runs (session_id, started_at);
CREATE INDEX idx_runs_user ON agent_runs (tenant_id, user_id, started_at);
CREATE TABLE agent_steps (
  id BIGSERIAL PRIMARY KEY, run_id UUID NOT NULL REFERENCES agent_runs(run_id),
  seq INT NOT NULL, state TEXT NOT NULL, input_summary TEXT, llm_json JSONB,
  tool_calls_json JSONB, observations_json JSONB, decision TEXT,
  tokens_used INT NOT NULL DEFAULT 0, cost NUMERIC(12,4) NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (run_id, seq)
);
CREATE TABLE tool_calls (
  call_id TEXT PRIMARY KEY, run_id UUID NOT NULL, step_id UUID, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  tool_ref TEXT NOT NULL, tool_version INT, args_json JSONB NOT NULL,
  result_json JSONB, status TEXT NOT NULL, risk_level TEXT, approval_id UUID,
  error_code TEXT, latency_ms INT, cost NUMERIC(12,4),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_calls_run ON tool_calls (run_id, created_at);
```

## C.3 Knowledge

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, owner_id UUID NOT NULL,
  kb_id UUID NOT NULL, title TEXT NOT NULL, source_uri TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',   -- PENDING/PARSING/READY/FAILED/DELETED
  hash TEXT NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE TABLE document_versions (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, document_id UUID NOT NULL,
  version INT NOT NULL, storage_uri TEXT NOT NULL, hash TEXT NOT NULL, meta_json JSONB,
  UNIQUE (tenant_id, document_id, version), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE chunks (
  chunk_id UUID PRIMARY KEY, tenant_id UUID NOT NULL, document_id UUID NOT NULL,
  version INT NOT NULL, seq INT NOT NULL, section TEXT, source TEXT NOT NULL,
  position INT, text TEXT NOT NULL, token_count INT NOT NULL,
  permission TEXT, vector vector(1024), meta_json JSONB, hash TEXT NOT NULL,
  UNIQUE (tenant_id, document_id, version, seq), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON chunks (tenant_id, document_id, version);
CREATE INDEX idx_chunks_text_gin ON chunks USING GIN (to_tsvector('simple', text));
CREATE TABLE knowledge_facts (   -- Graph 最小可审计单元（§14.2）
  fact_id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  subject_entity TEXT NOT NULL, predicate TEXT NOT NULL, object TEXT,
  confidence NUMERIC(3,2), source_doc TEXT, source_chunk TEXT, source_version TEXT,
  extracted_by TEXT, valid_from timestamptz, valid_to timestamptz,
  status TEXT NOT NULL DEFAULT 'ACTIVE'   -- ACTIVE/SUPERSEDED/CONFLICTING
);
```

## C.4 Memory / Eval / Ops

```sql
CREATE TABLE memories (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  agent_id UUID, scope TEXT NOT NULL,          -- USER/AGENT/TENANT
  memory_type TEXT NOT NULL,                   -- EPISODIC/SEMANTIC/PREFERENCE...
  content TEXT NOT NULL, source TEXT, confidence NUMERIC(3,2),
  ttl_at timestamptz, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE INDEX idx_memories_scope ON memories (tenant_id, user_id, scope, ttl_at);

CREATE TABLE evaluation_cases (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, dataset_id UUID NOT NULL,
  query TEXT NOT NULL, expected_json JSONB, category TEXT, risk_level TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE evaluation_runs (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, dataset_id UUID NOT NULL,
  config_json JSONB, metrics_json JSONB, status TEXT NOT NULL DEFAULT 'RUNNING',
  created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz
);
CREATE TABLE approvals (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, requester_id UUID NOT NULL,
  approver_id UUID, tool_ref TEXT, call_id TEXT, risk_level TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',     -- PENDING/APPROVED/REJECTED/TIMEOUT
  reason TEXT, decided_at timestamptz, expires_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_logs (
  id BIGSERIAL PRIMARY KEY, tenant_id UUID NOT NULL, trace_id TEXT,
  actor_id UUID, action TEXT NOT NULL, resource TEXT NOT NULL, resource_id TEXT,
  outcome TEXT NOT NULL, detail_json JSONB, ip TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_tenant_time ON audit_logs (tenant_id, created_at DESC);
CREATE INDEX idx_audit_action ON audit_logs (action, created_at DESC);

CREATE TABLE configurations (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, scope TEXT NOT NULL,   -- GLOBAL/AGENT/TOOL...
  scope_id TEXT, key TEXT NOT NULL, value_json JSONB NOT NULL, version INT NOT NULL DEFAULT 1,
  UNIQUE (tenant_id, scope, scope_id, key), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE feature_flags (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, key TEXT NOT NULL,
  rules_json JSONB NOT NULL, version INT NOT NULL DEFAULT 1, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE spans (
  span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_span_id TEXT,
  tenant_id UUID NOT NULL, user_id UUID, run_id TEXT, step_id TEXT,
  name TEXT NOT NULL, kind TEXT, start_time timestamptz NOT NULL,
  duration_ms INT, attributes_json JSONB, status TEXT, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_spans_trace ON spans (trace_id);
CREATE INDEX idx_spans_run ON spans (run_id, start_time);
```

## C.5 生命周期与 TTL

- 软删 + TTL：session 90d、memory 30~365d、临时 Run 快照；过期先归档 S3 再清。
- 版本不可变：`agent_versions / document_versions / configurations` 只增不改（灰度/回滚数据基础）。
- 保留策略：审计 180d、Trace 元数据 90d、payload 快照 30d、评测集长期。

---

# 附录 D：请求时序图

## D.1 一次对话请求（Agent Run）主时序

```
User        Gateway         Agent Runtime      Context Eng     Model Gw        Tool Runtime      Policy        Storage/OTel
 │  POST /runs │                 │                 │              │                │              │              │
 │────────────▶│  authN/限流      │                 │              │                │              │              │
 │             │────────────────▶│ create_run      │              │                │              │              │
 │             │                 │──(persist run)──│              │                │              │              │
 │             │                 │───────────────▶│ build ctx     │                │              │              │
 │             │                 │                 │──(memory/retr)│               │              │              │
 │             │                 │                 │─ctx ready────▶│ llm()          │              │              │
 │             │                 │                 │              │─tool_calls────▶│              │              │
 │             │                 │                 │              │               │──▶ perm? ───▶│ is_allowed   │
 │             │                 │                 │              │               │◀── allow ────│ (audit)      │
 │             │                 │                 │              │               │─execute(sandbox/retry)─│
 │             │                 │                 │              │               │─result──────▶│ persist call │
 │             │                 │─observe──▶ ctx append          │              │              │              │
 │             │                 │                              │ llm()         │              │              │
 │             │                 │◀── final answer ──────────────│              │              │              │
 │             │                 │─finalize(step+run+trace)─────────────────────────────────────▶│              │
 │             │◀── answer+refs──│                 │              │                │              │              │
 │◀────────────│                 │                 │              │                │              │              │
```

## D.2 审批时序（高风险工具）

```
Agent Runtime          Risk Engine          Approval Service         Human Approver
     │  tool call          │                      │                      │
     │────────────────────▶│  risk=HIGH_RISK      │                      │
     │◀─ WAITING_APPROVAL ─│                      │                      │
     │  (持久化 run 状态)   │─────────────────────▶│ create ApprovalRequest│
     │                     │                      │───── 通知 ───────────▶│
     │                     │                      │◀──── approve ─────────│
     │                     │                      │────────────────────▶│ (audit)
     │◀──── approved ──────│                      │                      │
     │  → RUNNING → 执行 tool
```

- 审批请求 `PENDING → APPROVED/REJECTED/TIMEOUT(24h)`；每次决策写审计；Run 在 `WAITING_APPROVAL` 可被用户取消，期间不消耗 LLM 预算。

## D.3 崩溃恢复时序

```
Executor(新实例)
  scan runs WHERE state IN (PLANNING,RUNNING,WAITING_TOOL) AND lock_expired
  for each: acquire_run(lock)
    load last checkpoint (agent_steps 末行 + budget 快照)
    re-enter state:
      WAITING_TOOL → 重查 tool_calls 幂等结果 → 继续 OBSERVING
      RUNNING/PLANNING → 重放 LLM 调用（记录在案）→ 继续
    finalize
```

## D.4 检索时序（RAG）

```
Context Eng ─▶ RetrievalService
  ├─▶ (query rewrite) ─▶ embed ─▶ vector top-50
  ├─▶ BM25 top-50
  ├─▶ RRF fuse ─▶ policy filter ─▶ rerank top-5
  └─▶ RetrievalResult{chunks+provenance} ─▶ Context（UNTRUSTED 分区）
```

## D.5 失败时序示例（Tool 超时 → 降级）

```
Tool Runtime: execute(30s timeout) → TOOL_TIMEOUT
  → retry?（该工具不可重试）→ 不重试
  → 返回 ToolCallResult{ok=False, error=TOOL_TIMEOUT}
Agent Runtime: OBSERVING 收到失败 → 触发降级链（换工具 / 拒答）
  → 写 span(error_code=TOOL_TIMEOUT) + audit
  → 进入 REFLECTING 决定"降级回答 or 终止"
```

---

---

# 附录 E：会话与异步任务隔离细则（防串会话）

## E.1 会话身份全程携带

Session 相关结构至少含：`tenant_id, user_id, session_id, agent_id, conversation_id, run_id`。任何 Context/Memory/Retrieval/Cache/Tool 调用**必须带上主体与作用域**（调用链透传，不是读全局变量）。

## E.2 禁止全局 Context 与 Worker 本地状态

- 禁止 `global_history / global_memory / global_agent_state` 承载会话。
- 禁止用进程内全局变量保存 Session。
- **禁止把 Worker 本地状态当作唯一 Session State**——Worker 会处理不同用户，本地缓存/单例一旦漏键即串会话。
- 会话状态只允许：DB / Redis（带 session key）/ 请求上下文对象（显式传入）。

## E.3 Memory / Cache 隔离

- Memory 查询同时带 `tenant + user + agent + scope`，由 Repository 层强制注入；**先钉死 scope 再相似度**（User B 记忆即使 embedding 最相似也不返回）。
- Cache Key 必须含 Tenant/User/Session 维度（§17.2）；命中任何缓存先过权限校验。

## E.4 Async Job 隔离

- Queue Message 必须携带完整身份：`tenant_id, user_id, session_id, agent_id, run_id, trace_id`。
- **Worker 取到消息后重新验证权限，不能只信任 Queue Payload**——消息可能被伪造/过期/来自已变更权限的主体。

## E.5 测试

- 并发两个不同用户 Run，断言所有查询/缓存/记忆互不可见。
- 同一 Worker 依次处理不同用户任务，断言无状态泄漏。
- 篡改 Queue Payload 身份字段，断言 Worker 拒绝。

---

# 附录 F：服务生命周期与发布细则

## F.1 生命周期操作

`Start / Stop / Restart / Drain / Pause / Resume`。

## F.2 Graceful Shutdown（不能直接 kill）

```
Stop Accept New Request
  → Stop New Agent Run
  → 等待正在执行的 Run（限时）
  → Cancel 超时任务（状态转 CANCELLED，交给恢复/Queue）
  → Drain Queue（消费完已领取任务）
  → Close Connection（HTTP/SSE/WebSocket/DB/Redis）
  → Shutdown
```

- **Grace Period**（30s/60s/120s 可配）；超时剩余任务交给 Queue/Recovery，绝不强杀丢数据。

## F.3 Startup 与 Readiness Gate

```
Load Config → Init Dependency → Check DB → Check Redis → Check Queue
  → Check Model Gateway → Warmup（连接池/缓存预热）→ Ready
```

只有 Readiness 通过才接流量。**Liveness ≠ Readiness**：Liveness = 进程活着（挂了才重启）；Readiness = 能否接请求（依赖不可用，如 LLM 挂 → 置否摘流量，不杀进程，防 K8s 无限重启）。

## F.4 Rolling Deployment

```
Old → New → Health Check 通过 → 1% → 5% → 20% → 50% → 100%
任何指标恶化（error/latency/cost）→ 自动停止发布并回滚
```

## F.5 发布不丢体验

- **Stateless Runtime**：会话/运行状态放 DB/Redis，不放进程内存（ADR-02）。
- **Connection Draining**：旧实例停接新请求，继续处理已有 HTTP/SSE/WS/进行中 Run。
- **Message Schema 向后兼容**（新旧 Worker 共存消费同一队列）。
- **Schema Migration**：`Expand（加列双写）→ Migrate（后台迁移校验）→ Contract（删旧列）`，保证新旧版本共存正确。
- **Feature Flag**：高风险功能按 `tenant → agent → user → percentage` 放量。

## F.6 Canary 指标与自动停止

灰度期看：Error Rate、Latency、Token Cost、LLM 429、Agent Success、Tool Success、RAG Recall、User Feedback。任一关键指标恶化（Error Rate ↑ / Latency ↑ / Cost ↑ 超阈值）→ 立即停止灰度并回滚。

## F.7 Rollback（不只回代码）

`Code + Prompt Version + Model Version + Agent Config + Tool Version + Knowledge Version + Schema Version`（一致版本集，配置只增不改，回滚=切换版本指针）。

## F.8 Agent Release Contract（发布前 10 项检查）

| # | 检查项 | 失败动作 |
|---|---|---|
| 1 | API Compatibility | 阻断 |
| 2 | Queue Compatibility（Message 向后兼容） | 阻断 |
| 3 | DB Compatibility（Expand→Migrate→Contract） | 阻断 |
| 4 | Prompt Compatibility（旧 Traces/评测集无回退） | 阻断/降级灰度 |
| 5 | Tool Compatibility（ref/参数/返回 schema） | 阻断 |
| 6 | Model Compatibility（能力/价格/健康） | 阻断 |
| 7 | Config Compatibility（可回滚、无缺键） | 阻断 |
| 8 | Memory Compatibility（不破坏存量记忆） | 阻断 |
| 9 | Trace Compatibility（可观测不被破坏） | 阻断 |
| 10 | Rollback Compatibility（可一键回滚） | 阻断 |

---

---

# 附录 G：缓存治理细则

## G.1 缓存分类（12 类，各带 Scope/TTL/失效/安全）

| # | Cache | Scope | 默认 TTL | 失效 | 安全 |
|---|---|---|---|---|---|
| 1 | Public | 全局/租户 | 长（30d） | 定时/事件 | 内容公开非敏感 |
| 2 | Tenant | tenant | 中 | 事件/版本 | 严格 tenant 隔离 |
| 3 | User | user | 短~中 | 事件/会话结束 | 严格 user 隔离 |
| 4 | Session | session | 会话级 | 会话结束 | 仅会话内 |
| 5 | Agent | agent+version | 中 | Agent 版本变更 | 绑定 agent_version |
| 6 | Query | tenant+user | 短 | 数据版本/权限变更 | query_hash + scope |
| 7 | Retrieval | tenant+kb | 短（5min） | kb_version 升级 | 权限 scope 入 key |
| 8 | Embedding | 全局 | 长 | embed 版本变更 | 内容本身安全 |
| 9 | LLM Response | tenant+user+session | 会话级 | 会话/prompt 变更 | 仅会话内，脱敏 |
| 10 | Tool Result | tenant+agent | 短（幂等窗口） | 工具版本/参数 | 脱敏后缓存 |
| 11 | Configuration | tenant | 长 | 配置版本变更 | 无敏感 |
| 12 | Permission | tenant+user | 极短（30s） | 角色/策略变更 | 决策结果非数据 |

**原则：Scope 越大，TTL 越短、内容越不敏感。**

## G.2 可缓存 vs 禁止缓存

**可缓存**：Embedding（text_hash→vector，幂等）、检索结果（短 TTL + kb_version）、静态配置与 Prompt/Tool/Skill 元数据、模型能力/价格/Provider 健康（短 TTL）、公开知识。

**禁止直接缓存**：用户私有数据、Access Token/Credential/Secret、权限相关数据、实时业务状态、强一致性数据、高敏感数据、会话临时状态（未绑定 session）、未经隔离/脱敏的 Tool Result。

> **硬红线：禁止把 User A 的 Agent Response 直接缓存命中给 User B。** 权限 scope 必须入 key。

## G.3 失效——推荐 Versioned Cache

```
Knowledge v1 → 用户更新文档 → Knowledge v2
key = tenant:123:kb:1024:query_hash     # v1
key = tenant:123:kb:1025:query_hash     # v2 版本号自然产生新 key
```

**能靠版本号翻新 key 的，就不要写复杂全局删除逻辑**（全局删除易漏、慢、并发撕裂）。

## G.4 缓存一致性模式（何时用哪种）

| 模式 | 适用 | 注意 |
|---|---|---|
| Cache Aside | 读多写少、容忍短窗口不一致 | 默认；写后主动失效 |
| Read Through | 统一缓存入口 | 封装在 Repository |
| Write Through | 强一致写路径（配置） | 写放大 |
| Write Behind | 写密集异步落库 | 可能丢更新，慎用于权限/计费 |
| TTL | 弱一致兜底 | 必须有 |
| Versioned Cache | 版本驱动内容（kb/prompt/model） | **优先推荐** |
| Pub/Sub Invalidation | 跨实例主动失效 | Redis Pub/Sub |

> **红线：不得为缓存命中率牺牲权限正确性、数据正确性、安全性。**

## G.5 Cache Stampede 防护

- **Singleflight**：同 key 并发 Miss 只加载一次；只有发起者真正加载。
- **TTL Jitter**：`expire_at = ttl * (0.7 + random*0.6)` 防同时过期。
- **Warmup**：热点 key 后台预加载；分布式单飞用 Redis `SET NX` 锁防多 Worker 同时 Miss。

---

# 附录 H：成本归因与模型调度细则

## H.1 CostBreakdown（每个 LLM Call 落一条，随 Run 聚合）

```python
class CostBreakdown(BaseModel):
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int  # prompt 缓存命中
    reasoning_tokens: int
    tool_tokens: int  # 工具 schema + 结果折算
    rag_context_tokens: int
    prompt_tokens: int
    history_tokens: int
    estimated_cost: Decimal  # 用量×单价（下单前估算，预算预检）
    actual_cost: Decimal  # 账单口径（计费后校正）
```

## H.2 Token 持续增长排查（按租户/用户/Agent 维度）

监控：平均 Context/History/Tool Result/RAG/Output Token、平均 Steps、平均 LLM Calls、平均 Retry 次数。**`Token/Run` 相对基线持续上升（如连续 7 天环比 > 5%）自动告警**，告警带租户/Agent 归因可直接下钻。

## H.3 Token 优化优先级（从高到低）

1 Context Compression → 2 History Compression → 3 Tool Result Compression → 4 RAG Top-K → 5 Prompt Compression → 6 Duplicate Removal → 7 Tool Output Schema → 8 Max Output Tokens → 9 Agent Step Limit → 10 Model Routing。

**禁止把完整历史每次全量发给 LLM。**

## H.4 Context 生命周期分层

| 层 | 保留策略 |
|---|---|
| System/Task | 每轮都在，压缩后固定 |
| Recent Conversation | **保留原文**（近 N 轮，默认 5） |
| Old Conversation | **摘要**（每 M 轮折一条，默认 M=10） |
| Long-term Memory | 记忆库按需检索 |
| Retrieved Context | 按需检索，不常驻 |
| Tool Observation | 只留必要结果，可舍弃 |

## H.5 Model Scheduler 输入与过滤管线

```
Agent → Model Gateway → Scheduler → Model Pool → Provider
Scheduler 输入：Tenant · Priority · TaskType · ModelCapability · Cost
  · Latency · Quota · Concurrency · ProviderHealth · Region · TokenBudget
策略：Capability Filter → Health Filter → Quota Filter → Cost Filter
  → Latency Filter → Load Balance
```

**Provider Health**：持续记录 `P50/P95/P99、Error Rate、429 Rate、Timeout Rate、Token Throughput`；状态 `Healthy / Degraded / Unavailable`，Degraded 自动降低流量权重，Unavailable 剔除候选池并告警。降级必须可观测：`routing.provider_health = degraded(reason)` 写 Trace。

---

---

# 附录 I：每模块测试策略矩阵

| 模块 | 测试要点 |
|---|---|
| 状态机 | 每个 `(state,event,guard)` 组合断言目标态+副作用；非法转换抛错；终态无出边；CAS 竞态收敛 |
| 执行预算 | 分别打到 max_steps/tokens/cost/tool_calls/runtime，断言 TIMEOUT 且无泄漏 |
| 执行引擎 | 崩溃注入（任意点 kill）→ 重启从检查点恢复且工具不重复执行；死循环桩 N 步中断；并发双执行只一个执行者 |
| Tool 校验/幂等 | JSON Schema 拒非法参数；同 call_id 重放返回缓存；权限拒绝；SSRF 拦截回环/内网 |
| ToolRuntime 管线 | 放行/默认拒绝/限流/风险闸/幂等/审计各一例；工具自身抛 ToolError 原样透传 |
| PolicyEngine | 默认拒绝、allow 命中、DENY 优先、通配符、资源隔离不越权 |
| 审计 | 每次工具调用产生 ALLOWED/SUCCEEDED/DENIED 记录；trace_id 关联 |
| RAG 分块 | 结构分节、token 预算、overlap 携带上下文、seq 单调 |
| RAG 检索 | 相关命中、跨租户隔离、provenance、RRF 双检索器命中、空库 |
| kb.search 工具 | 走全管线；租户只信 subject（LLM 伪造 tenant 无效）；默认拒绝 |
| 恢复 | 锁过期非终态 Run → FAILED/RECOVERY_ABANDONED；持锁 Run 不被回收 |
| API | 健康检查、run 同步/异步、trace、工具列表/直调/权限 403、知识 ingest/search/跨租户空 |
| 契约 | 每个契约（Run/ToolCall/LLMRequest）schema 快照 + 兼容性测试；依赖方向 import-linter |
| Chaos | LLM 慢/失败/限流、Vector/Graph/Redis 故障、Queue 堆积、Worker Crash、网络抖动、第三方失败 → 降级/恢复/回滚/清理/一致 |

---

# 附录 J：Replay 与问题定位细则

## J.1 Replay 是排障"时间机器"

每个 Run 保存完整快照：`Input / AgentVersion / PromptVersion / ModelVersion / ToolVersion / KnowledgeVersion / RetrievedContext / ToolInput / ToolOutput / ModelOutput / RuntimeConfig`。

支持：
- **原样 Replay**：确定性复现（固定 model/temperature/种子）。
- **换参 Replay**：换 Prompt/Model/Retrieval/Reranker/Tool 对比找变量。
- **分步 Replay**：任意 step 断点续放，观察决策分叉点。
- **Diff**：两次 Replay 上下文/输出差异，支撑回归测试。

## J.2 敏感数据脱敏（硬约束）

禁止 Password/Token/Secret/PII 进 Debug Log 或 Replay 快照；Recorder 层统一脱敏（SecretReference 只存 ref），白名单字段原样其余脱敏——避免"日志脱敏了快照没脱"的缝隙。Replay 只允许 owner/被授权者触发，执行仍走完整 Policy，不因排障豁免安全。

## J.3 问题定位流程与 20 问

```
用户报错/回答异常 → run_id → Trace 瀑布 → 最慢/失败 span → payload
→ 审计（权限/审批/越权）→ 判定七类错误（Retrieval/Tool/Model/Prompt/Memory/Knowledge/Permission）
→ Replay 复现 + 换参对比 → 修复
```

每 Run 必须能答（见 §20.4）：哪个 Agent/Prompt/Model 版本、为什么选这个模型、检索到什么、用了哪些 Context、调了哪些 Tool、返回什么、多少 token/钱、哪步最慢/失败、是否重试/降级/熔断/缓存命中（含版本）、用户权限、是否串会话、能否 Replay。**答不全 = 可观测不合格**。

---

# 附录 K：MVP 实施计划（Phase 0–3 细化）

## K.1 MVP 验收场景（6 条）

1. 创建 Agent v1（system prompt + 绑定 3 工具：`http.get`、`kb.search`、`calc.add`）。
2. 发起 Run：对话 → 调 `kb.search` 检索文档 → 带引用回答。
3. Run 中低权限用户调 `http.get` 被拒 → 审计可见。
4. 查看该 Run 完整 Trace（每个 span 有 run_id/step_id/耗时/成本）。
5. 杀掉执行进程重启 → 正在执行的 Run 从检查点恢复（或标记失败由幂等兜底）。
6. 跑评测集（10 条）→ 输出 Recall@k + Faithfulness 报告。

## K.2 阶段拆解

| 阶段 | 内容 | 验收 |
|---|---|---|
| Phase 0 工程基础设施（1 周） | repo 结构、docker-compose(PG/Redis/MinIO)、FastAPI 骨架、配置加载、结构化日志+OTel、CI、Makefile | `make up && make test && make lint` 绿 |
| Phase 1 最小 Runtime（2 周） | AgentState 状态机、ExecutionBudget、run/step 落库、Redis run 锁、ModelGateway 单 provider、最小 ContextEngine、崩溃恢复、runs API | 能对话；预算超限 TIMEOUT；kill -9 后恢复；死循环 N 步停 |
| Phase 2 Function Calling + Tool Runtime（2 周） | ToolRegistry、ToolCallRequest/Result、PolicyEngine 默认拒绝、3 工具（calc.add/http.get/kb.search）、审计表、POST /tools/{ref}/execute | 工具调用带 audit+trace；越权拒绝；参数校验拒非法 |
| Phase 3 检索 + 评测雏形（1~2 周） | 文档 ingest（分块→embedding→向量+tsvector）、混合检索+RRF、RetrievalResult 进 Context（UNTRUSTED）、10 条评测集+Recall@k/Faithfulness、GET /runs/{id}/trace | 上传文档→提问带引用回答；评测脚本出报告 |

## K.3 MVP 范围裁剪（明确不做）

不做多租户界面（但模型强制 tenant_id）；不做 MCP/Graph/Memory 服务（留接口）；不做审批流（表先建）；不做重排器（RRF 后直取，接口预留）；不做沙箱（code/shell 工具禁用）；不接专用向量库/ES（pgvector + tsvector）。

## K.4 风险与缓解

| 风险 | 缓解 |
|---|---|
| 状态机被业务绕过 | transition() 唯一入口 + CI 架构测试 |
| 崩溃恢复不可靠 | 故障注入测试 + 幂等键 |
| 死循环打爆成本 | 预算 + 指纹检测 + 单测 |
| 检索质量差 | 先建 10 条评测集，Recall@k 说话 |
| 权限漏洞 | 默认拒绝 + 越权测试 + 审计全覆盖 |

---

> 全文完。本卷 v0.3 在去重结构上补齐了原版全部细节（附录 C–K），单文件即含完整规范。










