# 企业级 Agent Runtime 工程化设计方案

> 面向生产环境的 Agent 平台：Execution / Scheduling / Cancellation / Checkpoint / Timeout / Retry / Circuit Breaker / Queue / RAG / Graph / Memory / Security / Multi-Tenant / Observability / Evaluation / Versioning / Rollback / Developer Debugging。
>
> 立场：Engineering First、Security First、Observability First、Failure First。不依赖任何具体 LLM 厂商，不绑定 LangChain/LlamaIndex/Dify。模块化单体起步（Modular Monolith First）。
>
> 关联文档：`enterprise-agent-platform-design.md`（平台级 §1–§61 详细设计）；本文档按 §82 的 30 章给出完整工程化方案，各章引用详细设计处以 `[§x]` 标注。

- 编写日期：2026-08-20
- 状态：Draft v0.1
- 目标读者：有经验的软件工程师，可据此直接开始编码

---

# 第一章：整体架构与设计哲学

## 1.1 设计哲学（为什么）

企业级 Agent 不是 "Prompt + LLM + Tool"。它是一个**有状态、会失败、必须可恢复、可审计、可评测**的运行时。10 条原则：

| # | 原则 | 含义 | 反例（不合格） |
|---|---|---|---|
| 1 | Engineering First | 每个设计回答"为什么/结构/流程/异常/并发/安全/性能/可观测/测试/坑" | 只有架构图没有决策 |
| 2 | Security First | 默认拒绝、最小权限、UNTRUSTED 数据隔离 | 前端隐藏当隔离 |
| 3 | Observability First | 任何一次 Run 可答"发生了什么、为什么" | 只有日志没有 Trace |
| 4 | Evaluation Driven | 改动用评测集说话，不靠感觉 | 凭感觉换模型 |
| 5 | Failure First | 先设计失败路径：LLM 挂/慢/限流、Tool 挂、Worker 崩、取消竞态、队列堆积 | 只写 happy path |
| 6 | Multi-Tenant Isolation | tenant_id 全模型，服务端强制 | 靠前端过滤 |
| 7 | Cost Aware | 成本可归因（Tenant→Run→LLM Call）、可预算 | "今天花了 $500" |
| 8 | Graceful Degradation | 依赖失败降级链，不硬编 | 一直 Retry |
| 9 | Recoverability | 崩溃可恢复、任务不悬挂、副作用幂等 | 崩了重跑一遍 |
| 10 | Developer Debuggability | 5 分钟内定位线上问题 | 只能加日志重跑 |

## 1.2 四层架构

```
                    Agent Application（业务 Agent / Skill / Workflow）
                                  │
                                  ▼
              ┌─────────────────────────────────────────┐
              │   Agent Runtime / Control Plane（§2-9）    │
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

**关键分层决策（对应 §82 不把一切塞进 Runtime）**：
- **Core Runtime**：只负责执行与治理（状态机、调度、取消、预算、策略、隔离）。
- **Capability Layer**：RAG / Graph / Memory / Tool / MCP / Skill —— 可插拔、可替换、可离线演进。
- **Infrastructure**：Queue / Cache / DB / Object Storage —— 通用中间件。
- **Cross-Cutting**：Security / Observability / Evaluation / Cost / Audit / Versioning —— 横切，不依赖业务模块。

## 1.3 模块依赖规则（防止腐化）

1. 依赖方向单向：`Application → Runtime → Capability → Infrastructure`；Capability 不得反向依赖 Runtime。
2. 横切基础设施不依赖任何业务模块。
3. 模块间以**版本化契约**通信（RunRequest/ToolCallRequest/LLMRequest/RetrievalResult/ContextBlock）。
4. CI 用 import-linter / 架构测试强制，不允许"忍不住 import 一下"。

## 1.4 技术选型（简表，详见第二十六章）

| 域 | 选型 | 何时换 |
|---|---|---|
| Runtime/API | Python + FastAPI | 独立扩缩容需求出现 |
| 关系库 | PostgreSQL | 无 |
| 缓存/锁/队列 | Redis | 队列吞吐不足换 Kafka/Pulsar |
| 向量 | pgvector 起步 | 块 >500 万 或 复杂过滤 → 专用向量库 |
| 全文 | PG tsvector → OpenSearch | 检索延迟/中文分词 |
| 图 | 后置（Neo4j 或 PG 递归 CTE） | 关系型数据规模大时 |
| 对象 | S3 兼容 | 无 |
| 追踪 | OpenTelemetry | 无 |

---

# 第二章：Agent Runtime 核心模型

## 2.1 为什么需要正式数据模型

Runtime 的一次 Run 是**异步、跨进程、可中断、可恢复**的执行单元。没有正式的 `Run/Step/Task/ToolCall/LLMRequest/Checkpoint/Event/Trace` 结构，就无法做取消传播、断点续跑、审计、重放。所有结构均为 Pydantic 契约（版本化，变更走演进）。

## 2.2 核心数据结构

```python
# ---- Run：一次 Agent 执行（生命周期主体）----
class Run(BaseModel):
    run_id: str
    tenant_id: str
    user_id: str
    agent_id: str
    agent_version: str  # 绑定的版本集（§21：prompt/model/tool/knowledge 版本）
    session_id: str
    state: RunState  # §3 状态机
    budget: ExecutionBudget  # §16：steps/tokens/cost/tool_calls/wall_time
    model_route: ModelRoute  # §6：路由决策（含 reason，落 Trace）
    input: RunInput
    output: RunOutput | None
    error: ErrorInfo | None
    checkpoint: CheckpointRef  # 最新检查点
    deadline: datetime  # 绝对截止时间（wall clock）
    created_at / updated_at / started_at / finished_at


# ---- Step：一次"思考+动作"循环迭代 ----
class Step(BaseModel):
    step_id: str
    run_id: str
    seq: int
    state: StepState  # PENDING/RUNNING/WAITING_TOOL/OBSERVING/...
    input: StepInput  # 进入时的上下文摘要
    llm_call: LLMRecord  # model/messages/tool_calls/tokens/cost/latency
    tool_calls: list[ToolCallRecord]
    observations: list[Observation]
    decision: StepDecision  # continue / done / escalate / cancel
    tokens_used: int
    cost: Decimal
    checkpoint_before: bool  # 是否在本步前打点（恢复粒度）


# ---- ToolCall：一次工具执行（含幂等键与决策链）----
class ToolCall(BaseModel):
    call_id: str  # 幂等键 = hash(tenant,run,step,tool,args)
    run_id: str
    step_id: str
    tool_ref: str
    args: dict
    permission_decision: PolicyDecision
    risk_decision: RiskDecision  # 审批闸
    status: CALL_STATUS  # PENDING/RUNNING/SUCCEEDED/FAILED/UNKNOWN
    result: ToolResult | None
    latency_ms: int
    cost: Decimal


# ---- LLMRequest：一次模型调用（可取消、可重放）----
class LLMRequest(BaseModel):
    request_id: str
    run_id: str
    step_id: str
    provider: str
    model: str
    messages: list[Message]
    tools: list[ToolSchema]
    params: LLMParams  # temperature/max_tokens/top_p/...
    deadline: datetime
    cost_estimate: Decimal


# ---- Checkpoint：可恢复的持久化快照 ----
class Checkpoint(BaseModel):
    checkpoint_id: str
    run_id: str
    run_state: RunState
    completed_steps: int
    current_step: int
    variables: dict  # 运行变量（不存整个 Context）
    tool_results: dict[str, ToolResult]  # call_id -> result（幂等续跑用）
    trace_id: str
    created_at: datetime


# ---- 事件：一切状态/副作用变更的不可变记录（§27 事件模型）----
class Event(BaseModel):
    event_id: str  # 幂等（event_id 去重）
    event_type: str  # RunStarted/StepStarted/ToolCalled/CancelRequested/...
    run_id: str
    step_id: str
    tenant_id: str
    user_id: str
    trace_id: str
    payload: dict
    created_at: datetime


# ---- Trace：观测骨架（§17）----
class Span(BaseModel):
    span_id: str
    trace_id: str
    parent_span_id: str
    name: str  # run/step/llm/tool/retrieval/rerank/...
    start: datetime
    end: datetime
    duration_ms: int
    status: str
    error: ErrorInfo | None
    attributes: dict  # model/tokens/cost/tool_ref/...（脱敏后）
```

## 2.3 生命周期与存储

- Run 状态与 Step 存 PostgreSQL（`agent_runs` / `agent_steps`，§25/§26）。
- 检查点 = `completed_steps` 计数 + `tool_results` 幂等表 + 运行变量；存 PG（小）+ S3（大 artifact）。
- 事件写 `event_ledger`（§27）；Trace 写 OTel 后端。
- 崩溃恢复：从最后 Checkpoint 重放，工具副作用由幂等键保证**至多一次**（§8/§9）。

## 2.4 关键不变量

1. **状态只经 StateMachine.transition() 变更**（带守卫 + 乐观锁 CAS），禁止直接改字段。
2. **同一 run 只有一个执行者**：Redis 分布式锁 + Lease/Heartbeat（§8 Zombie 检测）。
3. **工具副作用至多一次**：幂等键（§5/§9）。
4. **版本集在 Run 创建时冻结**（agent/prompt/model/tool/knowledge 版本），运行中不漂移（§21）。
5. **UNTRUSTED 数据永远隔离**（§13）：RAG/网页/工具结果/记忆不是指令。

---

---

# 第三章：Agent State Machine

## 3.1 为什么是正式状态机

企业级 Run 不是 "PENDING→RUNNING→SUCCESS/FAILED" 三个布尔。它要处理**取消竞态、暂停/恢复、超时、审批阻塞、崩溃恢复**——没有显式状态机，多个 Worker 并发改状态必然错乱。

## 3.2 状态全集（完整）

```
PENDING（已入队）
RUNNING（执行中）
PAUSING（收到暂停，正在收尾当前步）
PAUSED（已暂停，不消耗预算）
RESUMING（恢复中，装载检查点）
CANCELLING（收到取消，正在传播取消信号）
CANCELLED（已取消，终态）
TIMEOUT（超预算/超时，触发 TERMINATING）
TERMINATING（正在清理资源/取消下游）
FAILED（不可恢复失败，终态）
SUCCESS（完成，终态）
UNKNOWN（副作用结果未知，如支付请求超时）
```

## 3.3 合法状态转换（§83 Q6/Q7：取消与成功竞态必须收敛）

```
PENDING → RUNNING
RUNNING → CANCELLING | PAUSING | TIMEOUT | FAILED | SUCCESS
CANCELLING → CANCELLED | TIMEOUT
PAUSING → PAUSED | CANCELLING
PAUSED → RESUMING | CANCELLING | TIMEOUT
RESUMING → RUNNING | FAILED
TIMEOUT → TERMINATING
TERMINATING → FAILED | CANCELLED | UNKNOWN
RUNNING → UNKNOWN（副作用工具超时，结果未知）
UNKNOWN → SUCCESS | FAILED（查询第三方后收敛）
```

**竞态处理**：状态转换必须**原子 + 乐观锁**：

```sql
UPDATE agent_runs SET state='CANCELLING', version=version+1
WHERE run_id=$1 AND state='RUNNING' AND version=$2
-- 影响行数=0 => 状态已变，重读决策
```

- **取消与 Step 完成同时发生**：以 CAS 结果为准——谁先提交谁生效；后到的一方读新状态走补偿（已完成的副作用由幂等键幂等，§9）。
- 状态机实现要点：唯一 `transition()` 入口、守卫、历史审计、终态无出边（详见平台文档 §3.3）。

## 3.4 UNKNOWN 状态（§82 第十节）

工具调用"请求已发出但超时"时，**不知道第三方是否成功**。不能简单标 FAILED：

```
工具请求发出 → 网络超时 → 状态 = UNKNOWN
  → 查询第三方状态（工具提供 reconcile()）→ SUCCESS / FAILED
  → 无法查询 → 保留 UNKNOWN + 告警 + 人工介入
```

`ToolDefinition.reconcile(call_id)` 是**可恢复副作用工具**的必需接口（§5）。

---

# 第四章：Execution Engine

## 4.1 执行模型

```
User Input
  → Context Assembly（§2/§5 ContextEngine）
  → Policy Check（主体/工具/预算）
  → Planner / LLM（Model Router 选型）
  → Tool Selection → Tool Execution（§5 全管线）
  → Observation → State Update
  → 是否继续？ Yes→Planner / No→Final Answer
```

## 4.2 并发模型

- **每个 Run 一个执行器协程**；Run 内 Step 串行（语义正确的前提）。
- **Step 内 Tool 并行**（有界并发，默认 4）；声明依赖的工具串行（§5）。
- **Run 间水平并行**：Executor 无状态；`acquire_run` 用 Redis 锁保证单执行者。
- **全局有界并发**：信号量限制并发 Run 数，超水位进队列（§9）。

## 4.3 执行循环（伪代码）

```python
async def execute_run(run, deps):
    await acquire_run_lock(run.run_id)  # 单执行者
    sm = StateMachine(run.state)
    ctx = ExecutionContext(run, CancellationToken(), Deadline(run.deadline))
    spent = BudgetSpent()
    while not sm.is_terminal():
        check = BudgetGuard(run.budget).check(spent)  # §16
        if check.exceeded:
            sm.transition(TIMEOUT)
            break
        if ctx.token.cancelled:
            sm.transition(CANCELLING)
            await propagate_cancel(ctx)
            break
        result = await deps.llm.complete(LLMRequest(...))  # 可取消（§7/§8）
        spent.accumulate(result)
        if result.tool_calls:
            sm.transition(RUNNING)  # 内部子状态
            for tc in result.tool_calls:
                spent.tool_calls += 1
                obs = await deps.tool_runtime.execute(tc, ctx)  # §5 全管线
                ctx.messages.append_tool_result(obs)
            if loop_detected(ctx):
                sm.transition(FAILED, LOOP_DETECTED)
                break
        else:
            sm.transition(SUCCESS)
            break
        await checkpoint(run, spent)  # §8：每步后打点
    await finalize(run, sm.state, spent)
```

## 4.4 执行预算（防死循环 + 成本闸，§16/§42）

| 维度 | 默认 | 触发 |
|---|---|---|
| max_steps | 30 | TIMEOUT |
| max_tokens | 200k | 停止下一次 LLM |
| max_cost | ¥10 | 停止，可配审批放行 |
| max_tool_calls | 50 | 不再接受新工具 |
| max_wall_time | 600s | 强杀协程 + TERMINATING |
| max_retries | 3 | 超即 FAILED |

**死循环检测**：`(意图摘要, 工具名, 参数指纹)` 连续 N 步相同 → 判定循环 → 中断 + 告警。

## 4.5 失败处理（§7/§40）

- 可重试：超时/429/5xx/网络 → 指数退避 + 抖动重试（上限内）。
- 不可重试：参数错误/权限拒绝/业务错误 → FAILED（保留现场）。
- 一律映射统一错误模型（§51）：`ErrorCode / ErrorType / Retryable / UserVisible / InternalMessage / Cause / TraceID`。

---

# 第五章：Function Calling / Tool Runtime

## 5.1 核心论断

**Function Calling ≠ 直接执行。** LLM 输出的 `tool_calls` 是"意图"，不是"命令"。中间隔着裁决链：

```
LLM → Tool Call → Tool Registry → Policy Engine → Permission
  → Argument Validation → Quota/Rate Limit → Risk/Approval
  → Sandbox/Execution → Result Validation → Observation → LLM
```

## 5.2 Tool 契约

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
    cost: ToolCost  # 执行成本估算
    tenant_scope: bool  # 是否需要主体身份（context_aware）
    kind: FUNCTION | HTTP | MCP | DB | BROWSER | CODE | SHELL | FILE | SEARCH | RAG | GRAPH
    status: DRAFT | ACTIVE | DEPRECATED | DISABLED
    version: str
    reconcile: Callable | None  # UNKNOWN 状态下查询第三方（§3.4）
```

风险分级（§82 第六节）：

| 级 | 例子 | 控制 |
|---|---|---|
| READ | 查询订单、检索 | 权限 + 限流 |
| WRITE | 创建订单 | 权限 + 幂等键 |
| SIDE_EFFECT | 支付、发邮件 | 权限 + 审批 + 幂等键 + 可查账 |
| ADMIN | 删数据、改权限、发布 | 权限 + 审批 + 双人复核 |

## 5.3 执行管线（§82 第五节，全量）

```
1 resolve（registry，TOOL_NOT_FOUND）
2 status check（ACTIVE）
3 permission（PolicyEngine，default-deny，TOOL_PERMISSION_DENIED）
4 argument validation（JSON Schema + 业务校验，TOOL_INVALID_ARGUMENT）
5 quota / rate limit（tenant:user:tool，TOOL_RATE_LIMITED）
6 risk gate（SIDE_EFFECT/ADMIN → ApprovalRequired，§19 审批）
7 circuit breaker（熔断开门 → TOOL_BREAKER_OPEN）
8 idempotency（call_id 命中 → 返回缓存，至多一次）
9 execute（timeout + retry + sandbox + secret 注入）
10 output validation（脱敏 + 注入检测）
11 reconcile 注册（UNKNOWN 支持）
12 audit + metrics + trace
```

## 5.4 幂等键与副作用（§83 Q5/Q9：Tool 已产生副作用但 Agent 超时）

```
idempotency_key = hash(tenant_id, run_id, step_id, tool_ref, canonical_args)
```

- 同一 key 的重复执行返回**缓存结果**（窗口内），绝不重复副作用。
- **补偿（Compensation）**：`ToolDefinition.compensatable=true` 时提供撤销工具（如 `ticket.reopen` 补偿 `ticket.close`）。
- 超时后：状态 → UNKNOWN，凭 `idempotency_key` 调 `reconcile()` 判定真实结果。
- **审计成对**：副作用操作 + 补偿/查询记录成对，可完整重放"发生过什么"。

## 5.5 Tool 治理

| 能力 | 默认 | 说明 |
|---|---|---|
| timeout | 30s | 不悬空，返回 TOOL_TIMEOUT |
| retry | 0（仅幂等+瞬时） | 指数退避 |
| circuit breaker | 5 败/60s | 熔断期直接拒 |
| rate limit | 租户+用户级 | 滑动窗口 |
| audit | 强制 | 每次调用落 AuditLog |

## 5.6 统一抽象（MCP/HTTP/Function，§82 不绑定框架）

```
Agent Runtime 只认识 ToolCallRequest / ToolCallResult
        │
  ToolProvider（统一接口：resolve / execute / health / reconcile）
     ├─ FunctionProvider（本地函数）
     ├─ HttpProvider（HTTP API，SSRF 防护）
     ├─ McpProvider（MCP Client → MCP Server，白名单 + 参数校验 + 网络隔离）
     └─ ...
```

上层 Agent **不感知**底层是 MCP 还是 HTTP。MCP 是"发现/传输协议"，Function Calling 是"意图编排层"，两者在 ToolProvider 处汇合（详见平台文档 §12）。

---

# 第六章：LLM Provider / Model Router

## 6.1 分层

```
Agent → Model Gateway → Scheduler → Model Pool → Provider
              │                    │
         统一入口            决策写入 Trace（为什么选这个模型）
```

- **LLM Provider Interface**（§85）：抽象 `complete(LLMRequest) -> LLMResult`，支持 OpenAI / Anthropic / DeepSeek / GLM / Qwen / 本地模型。不绑定任何厂商。
- **统一度量**：token（in/out/cached/reasoning）、cost、latency、request_id、错误归一化（`MODEL_TIMEOUT/429/5xx`）。

## 6.2 Model Router（§35/§36）

输入：TaskComplexity · ContextSize · ToolCount · RiskLevel · LatencyBudget · CostBudget · TenantTier · ModelHealth · Quota。

输出：Model + `routing.reason`（落 Trace，支持复盘"为什么用了贵模型"）。

```
Capability Filter（匹配任务分级）
  → Health Filter（排除 Unavailable）
  → Quota Filter（配额内）
  → Cost Filter（预算内）
  → Latency Filter（SLA 内）
  → Load Balance（RR/Least Load）
```

**任务分级（Model Tier）**：

| 级 | 任务 | 档位 |
|---|---|---|
| L0 | 规则任务 | 不调 LLM |
| L1 | 分类/抽取 | Small |
| L2 | 简单问答 | Small |
| L3 | 复杂 RAG | Medium |
| L4 | 复杂 Agent Planning | Large |
| L5 | 高风险决策 | Strong + Guardrail + Human Review |

**Dynamic Routing（不写死"永远用 GPT-X"）**：实时看 latency/error/429/quality/quota/provider health 动态调流（§7.3）。

**Model Escalation（§36 小模型先处理）**：

```
Small → confidence≥θ → 返回
     → confidence<θ → Medium → … → Large / 拒答转人工
```

Escalation 链写 Trace，成本可归因。

## 6.3 LLM 限流（§37）

| 维度 | 载体 |
|---|---|
| Global/Model | Redis 滑动窗口（RPM/TPM/并发） |
| Tenant | 配额 + 权重 |
| User | 配额 |
| Provider 侧 429 | 退避 + 换 provider |

用 Token Bucket / Semaphore；不能让请求无限堆进 Worker（§9 Backpressure）。

---

---

# 第七章：Timeout / Retry / Circuit Breaker / Degradation

## 7.1 分层 Timeout（§38，数字按 SLA 评测定，不照抄）

| 层 | 默认 | 说明 |
|---|---|---|
| API | 30s | 网关层 |
| Agent | 5min | Run 总墙钟 |
| Step | 60s | 单次循环 |
| LLM | 30s | 请求超时，含连接取消（§8 传播） |
| Tool | 10s | 含沙箱强杀 |
| RAG | 5s | 检索 |
| Queue | — | 任务可见性/租约 |

**Deadline 传播**：每个请求携带 `deadline`；子调用 deadline = min(parent.deadline, now + 本层预算)。绝不无限等待。

## 7.2 Retry（§40）

```
可重试：Timeout / 429 / 临时 5xx / 网络抖动
不可重试：InvalidParameter / PermissionDenied / BusinessError
策略：Exponential Backoff + Jitter，max_attempts=3
```

- **Retry Storm 防护**：全局退避上限 + 请求去重 + 熔断优先于重试（熔断开门不重试）。
- 副作用工具**不自动重试**（靠幂等键，§5.4）。

## 7.3 Circuit Breaker（§39）

```
CLOSED（正常）→ 错误率/慢调用超阈值 → OPEN（熔断，快速失败）
OPEN → 冷却窗口 → HALF_OPEN（放少量试探）
HALF_OPEN → 成功 → CLOSED / 失败 → OPEN
```

按 Provider 与 Tool 分别熔断。熔断事件写 Trace + 审计 + 告警。

## 7.4 Degradation（§39 降级链，Fail Gracefully）

```
Large → Medium → Small → Cached Result → Rule Based → Graceful Failure（拒答+可选项）
RAG 挂 → 关键词检索 → 拒答
Graph 挂 → 向量检索
Reranker 挂 → 原始 RRF 顺序
```

**绝不硬编**：检索为空/低分 → 显式拒答或降级，不是幻觉回答。每次降级写 Trace（`degradation` 事件），供线上质量监控（§57 线上指标）。

---

# 第八章：Cancellation / Pause / Resume / Checkpoint

## 8.1 Cancel 是 Runtime 一等能力（§82 第七节，§83 Q6/Q7）

用户点 Cancel ≠ 改一个字段。后台 Worker 可能仍在跑。流程：

```
Cancel API → Task.state=CANCELLING → CancellationToken
  → ExecutionContext → 传播到 LLM / Tool / RAG / Queue
  → 停止执行 → Cleanup（取消下游、释放资源、审计）→ CANCELLED
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

## 8.2 Cancellation Propagation（下游必须可取消）

- **LLM 取消**（§83 八节）：LLM HTTP 请求必须支持取消——用户取消后请求不再跑、不再耗 token/连接/费用。Provider SDK 支持 `abort()` 或 httpx timeout 内取消；Request 带 `request_id` 以便 provider 侧取消计费。
- **Tool 取消**（§9）：可取消工具（Search/RAG/HTTP GET/DB Query/Embedding）→ 取消信号直传；**不可简单取消工具**（Payment/Order/Email/DB Write）→ 不取消执行，但标记 UNKNOWN + 幂等键兜底（§5.4/§3.4）。
- **Queue 取消**：任务仍在队列/已在 Worker 执行中 → 取消标记传播到 Worker（幂等处理，§9）。

## 8.3 Pause / Resume（§12）

```
RUNNING →(Pause)→ PAUSING（当前步收尾）→ PAUSED（不耗预算）
PAUSED →(Resume)→ RESUMING（装载检查点）→ RUNNING
```

- 暂停发生在**Step 边界**（不在工具执行中途切），保证可恢复语义。
- 暂停/恢复均事件化 + 审计。

## 8.4 Checkpoint / Resume（§11，长任务不依赖内存）

```
Step1 SUCCESS → Step2 SUCCESS → Step3 SUCCESS → Step4 RUNNING → Step5 PENDING
                                        │
                                  Worker 崩溃
                                        ▼
                      重启 → Load Checkpoint → 重放 Step4（幂等）
```

- **Checkpoint 内容**（不存整个巨大 Context）：`completed_steps / current_step / run_state / variables / tool_results（幂等缓存）/ trace_id`。
- **持久化**：每步后打点（PG 小对象 + S3 artifact）。
- **重放语义**：LLM 调用重做（幂等记录请求，§2.4），工具调用按幂等键跳过；**至多一次副作用**（§5.4）。
- **Zombie 检测**（§9）：Lease/Heartbeat——锁过期即视为崩溃，任务重新入队。

## 8.5 取消/暂停/成功的竞态收敛

- 所有状态变更走 **乐观锁 CAS**（§3.3）：谁先提交谁生效。
- 取消传播是**尽力而为**：即使取消迟到（Step 已完成），副作用由幂等键保证不重复；Run 终态由 CAS 裁决。

---

---

# 第九章：Queue / Scheduler / Backpressure

## 9.1 为什么需要队列

Agent 不能全部同步执行。异步面：Document Ingestion、Embedding、Rerank、Graph Construction、Evaluation、Long Running Agent、Async Tool、Batch。

```
Producer → Message Queue → Scheduler → Worker Pool → Result Store
                    │
           Retry Queue · DLQ · Delay Queue
```

## 9.2 Job State Machine（禁止用 boolean）

```
CREATED → QUEUED → RUNNING → SUCCEEDED
              │        │  ↘ RETRYING → RUNNING
              │        │  ↘ WAITING（依赖/审批）
              │        ▼
              │      FAILED → DEAD_LETTER（重试耗尽）
              ▼
            CANCELLED / EXPIRED
```

## 9.3 队列治理（§45/§46，§83 Q10 队列堆积）

- **容量上限 + Admission Control**：`<50% 正常 / 50-70% 告警 / 70-85% 限流 / 85-95% 仅高优 / >95% 拒绝低优`。
- **优先级**：P0 用户实时 > P1 后台任务 > P2 普通 > P3 离线评测/索引。
- **公平性**：Per-Tenant Queue + 配额 + Weighted Scheduling，防一个大租户占满 Worker；**Aging**（等待越久优先级越高）防饿死。
- **Zombie 防护**：Lease（30s）+ Heartbeat + Visibility Timeout——Worker 崩溃 → 租约过期 → 任务重入队。
- **DLQ + 告警**：重试耗尽进死信队列，人工/自动处理，不静默丢失。
- **Backpressure**（§68）：生产速度 > 消费速度 → 降生产/加消费者/降优先级/丢弃低价值/暂停非核心。

## 9.4 指标

`queue_depth / consumer_lag / processing_rate / failure_rate / retry_rate / dlq_depth`。P0 饥饿时告警。

---

# 第十章：RAG（Knowledge Capability，非系统核心）

## 10.1 定位

RAG 是 Knowledge Layer 的一种检索能力（§82 二十节）。可插拔、可替换。完整管线：

```
索引期：Document → Parse → Clean → Structure → Chunk → Embedding → Index（向量+倒排）
查询期：Query → Query Rewrite → Permission Filter → Hybrid Retrieval
     → RRF → Rerank → Context Assembly → LLM
```

## 10.2 Chunk 元数据（§23：不是附属信息）

```
chunk_id / document_id / version / tenant_id / workspace_id / source
title / section / page / language / created_at / updated_at
permission / access_level / parent_id / position / hash
```

元数据是检索/权限/审计/增量更新/引用/排障的基础。

## 10.3 混合检索（§27）与 Rerank（§28）

```
Vector top-50 + BM25 top-50
  → RRF 融合：score(d)=Σ 1/(k+rank(d))，k=60
  → Top 20 → Cross-Encoder Rerank → Top 5~10 → Context
```

- **Rerank 漏斗**：绝不 `百万 → 全量 rerank`。
- **权限前置**（§29）：检索**前**按权限过滤，绝不让越权内容进入上下文再靠 LLM 判断。

## 10.4 增量更新（§62）

```
Document Hash → Diff → 变更 Section → 变更 Chunk
  → 只 Embed 变更块 → Upsert（按来源整体替换）
```

- Embedding 幂等（text_hash 缓存，§24）；删除按来源 id。
- **Knowledge Version**（§63）：Run 绑定 knowledge_version，保证"同一问题今天/昨天检索结果为何不同"可解释。

## 10.5 关键坑

- 分块质量决定上限（§4.3 原 RAG 文档）：结构感知 + 父子分块是首选，块参数必须过评测集（§19/§20）。
- 纯向量对代码符号/专有名词/条款号弱 → 必须混合检索。
- RAG 文档是 UNTRUSTED 数据（§13）：进 Context 单独分区，绝不拼进 system prompt。
- 百万级性能单独成章（§23）。

---

# 第十一章：Knowledge Graph

## 11.1 定位（§82 三十/三十三节）

Graph 不是 RAG 的子模块，是独立 Knowledge Capability。**但不要盲目建图**：只有"跨实体全局性问题"（组织关系、上下游、多跳）才值得；普通 FAQ 用 RAG。

```
Docs → Entity Extraction → Normalization → Resolution → Relation Extraction
  → Linking → Graph Validation → Storage → Retrieval（子图/多跳/社区）
```

## 11.2 Provenance 是硬要求（§32）

每条事实必须可审计：

```
Relation: Company —CEO→ Person
  source_document: doc-123
  source_chunk:    chunk-456
  document_version: 7
  confidence:       0.92
  extracted_by:     model-x
  created_at:       2026-08-20
```

回答不了"谁说的/哪个版本/多大把握/何时有效"的图，不能上生产。

## 11.3 时间有效性 + 冲突（§31，§83 Q14 错误关系）

- 时间敏感事实用 `valid_from / valid_to`（CEO 会换届），**不直接覆盖**。
- 冲突仲裁：`confidence × source_trust × recency`，胜出 ACTIVE，其余 SUPERSEDED（保留供审计/回滚）；无法自动判定 → 人工仲裁队列。
- 错误关系修正 = 按来源版本标记 SUPERSEDED（回滚复用同一机制）。

## 11.4 增量与删除（§61/§62）

- 增量：按来源文档版本重抽取受影响子图。
- 删除：按来源整体标记失效；用户删除数据后 Vector/Graph/Cache/Memory/索引必须最终删除。

---

# 第十二章：Memory

## 12.1 定位

Memory 独立于 RAG（§34）。RAG 管外部文档，Memory 管个体经验。

## 12.2 分类与隔离

| 类型 | 作用域 | 生命周期 |
|---|---|---|
| Working | Run | Run 内 |
| Conversation | Session | 会话（近轮原文 + 旧轮摘要） |
| Episodic | User | 短~中 |
| Semantic | User/Agent/Tenant | 长 |
| Preference | User | 长 |

**严格隔离**：tenant + user + session + run；Repository 层强制注入 scope，**先钉死 scope 再做相似度**——User A 不能召回 User B 记忆，即使 embedding 最相似（§14/§15）。

## 12.3 写入也要策略（§34）

Memory 写入需过 Policy + 注入检测 + 敏感检测（**Memory Poisoning** 防护，§13）。`source_trust` 分级：用户明确表达（可信）vs 网页自动提炼（不可信，TTL/置信度不同）。recall 结果进 Context 的 UNTRUSTED 分区。

---

---

# 第十三章：Security / Prompt Injection / Data Security

## 13.1 核心思想（§16）

**所有外部内容 = UNTRUSTED DATA**：用户输入、RAG 文档、网页、Graph、Tool Result、第三方 API、Memory、文件。

**绝对不能把外部内容拼进 System Prompt。** 必须：

```
System Instructions（TRUSTED）

<context>（UNTRUSTED DATA，模型只当数据，不当指令）
  [1] (source) chunk 文本
  [2] (source) 工具返回
</context>
```

## 13.2 多层防御（§17，不靠单个 Prompt）

| 层 | 防御 | 落地 |
|---|---|---|
| L1 | 输入检测（注入特征） | Gateway / Ingest / Context |
| L2 | Trust Boundary（信任分级） | Context Engine |
| L3 | Instruction/Data 分离 | Context 分区 |
| L4 | Tool Permission（default-deny） | Policy Engine |
| L5 | 参数校验 + 输出校验 | Tool Runtime |
| L6 | 敏感数据 Filter/Mask | 敏感数据层 |
| L7 | Audit + 告警 | Audit |

**关键认知（§18）**：Prompt Injection 的最终风险不是"模型说奇怪的话"，而是**模型被诱导调用危险 Tool**。所以 **Tool Permission > Prompt**。每次 Tool Call 都过 Policy → Permission → Risk → Schema → Quota → Execute。

## 13.3 敏感数据（§19）

- **分类**：PUBLIC / INTERNAL / CONFIDENTIAL / SECRET。
- 敏感数据**默认不进**：普通日志、Trace、Prompt、Cache、训练集；除非显式允许。
- **Mask/Redact**：日志与 Trace 统一脱敏（`sk-****`、`138****1234`）。脱敏规则在 Recorder 层统一，避免"日志脱敏了 Trace 没脱"的缝隙。
- **Secret Reference**（§83 Q13 关联）：LLM 只见 `credential_ref`，真实凭据由 Tool Runtime 执行时注入（§5.9），绝不落地到 Prompt/日志。

## 13.4 SSRF / 命令注入 / 沙箱

- HTTP 工具做 SSRF 防护（解析 DNS → 拦截内网/回环/保留地址）；沙箱要求见 Ch26。
- Shell/Code/文件工具必须沙箱（进程/容器隔离、CPU/内存限制、网络策略、seccomp、超时、Secret 隔离），见 Ch22/Ch26。

---

# 第十四章：Multi-Tenant / User Isolation

## 14.1 原则（§60/§82 十四节）

- **所有核心表带 tenant_id**；必要时 user_id / workspace_id / session_id / run_id。
- **服务端强制**：Repository/ORM 层自动注入 tenant scope，禁止"业务代码忘记 WHERE tenant_id"。
- 禁止只靠 `conversation_id` 查询——必须验证会话属于该用户该租户（§15）。

## 14.2 各层隔离

| 层 | 隔离手段 |
|---|---|
| DB 查询 | Repository 统一注入 `WHERE tenant_id=...` |
| RAG | tenant filter + 块 permission（检索前过滤） |
| Memory | tenant + user + scope 钉死再相似度 |
| Graph | facts 带 tenant，来源块权限沿 provenance 传导 |
| Cache | key 含 tenant + user/permission scope（§15.3） |
| Queue | 消息携带完整身份，Worker 重验权限（不信任 payload） |
| Object Storage | tenant prefix |
| Logs/Trace | tenant_id + user_id 全量属性 |

## 14.3 租户配额（§67，§83 Q11 一个租户打爆系统）

Tenant Quota：并发 Run、Token、Queue、Storage、Tool Calls、Rate。超配额 → 限流/降级/拒绝。按租户队列 + 权重调度防饿死（§9）。

---

# 第十五章：Cache

## 15.1 分级（§43，§83 Q12 缓存越权）

| 类别 | 处理 |
|---|---|
| 可缓存 | Embedding（text_hash→vector，幂等）、检索结果（短 TTL + kb_version）、静态配置、模型元数据、公开知识 |
| 谨慎 | LLM Response / RAG Answer / 用户 Query（仅会话内，脱敏） |
| 禁止 | 用户私密数据、敏感信息、权限相关结果、未隔离的 Tool Result、短期授权 |

## 15.2 Cache Key 必须含隔离维度

```
❌ cache[query]
✅ cache[f"{type}:{tenant_id}:{scope}:{version_set}:{content_hash}"]
   scope = user/session/agent；version_set = kb_version+embed_version+prompt_version+model_version
```

依赖权限的内容，**permission scope 必须入 key**，否则权限窄化后命中即越权。

## 15.3 失效与 Stampede（§49 平台文档）

- **Versioned Cache**：版本号翻新 key 代替全局删除（kb 升级自动产生新 key）。
- **Singleflight**：同 key 并发 Miss 只加载一次；TTL Jitter 防同时过期；热点预热。
- 命中任何缓存**先过权限校验**（缓存内容 + 已过期权限 = 越权）。

---

# 第十六章：Cost Governance

## 16.1 成本可归因（§41/§50，§83 Q17/Q18）

```
Tenant → User → Agent → Run → Step → LLM Call
每层可见：input/output/cached/reasoning tokens、model、price、estimated_cost、actual_cost
```

- **estimated_cost**（下单前估算，预算预检用）与 **actual_cost**（账单口径）分开字段。
- Run 绑定 `money_budget / token_budget / step_budget / tool_budget / time_budget`；超限 → Stop / Downgrade。

## 16.2 Token 持续上涨治理（§42，§83 Q17）

监控 `Context/History/Tool Result/RAG/Output token、Steps、LLM Calls、Retry` 均值，`Token/Run` 环比上涨自动告警。

优化优先级：1 Context 压缩 → 2 History 摘要 → 3 Tool Result 压缩 → 4 RAG Top-K → 5 Prompt 压缩 → 6 去重 → 7 输出 schema → 8 Max Output → 9 Step Limit → 10 Model Routing。

**禁止把完整历史每次全量发给 LLM**（成本黑洞 + lost-in-middle）。

## 16.3 成本维度 × 优化约束

任何优化必须回答三维：**Quality / Latency / Cost** 各变化多少（§65）。不做只看延迟不看成本的优化。

---

---

# 第十七章：Observability / Trace / Logs / Metrics

## 17.1 可观测不是后补（§48）

Logs + Metrics + Traces + Events + Evaluation 从第一天设计。

## 17.2 Trace 结构（§49）

```
Run
 ├── Planning → LLM
 ├── Tool Call → RAG
 │     ├── Query Rewrite → Vector Search → BM25 → RRF → Rerank
 ├── Tool Call → API
 └── Final LLM
```

每个 Span：`start / end / duration / status / error / input(脱敏) / output(脱敏) / model / tokens / cost`。

必带属性：`trace_id / span_id / parent_span_id / tenant_id / user_id / session_id / agent_id / agent_version / run_id / step_id / model / prompt_version / tool_ref / call_id / knowledge_version`。

## 17.3 全量采样策略

- **元数据全量**（ID、耗时、状态、属性），**payload 采样**（prompt/输出默认 10%，可配 100%）。
- 敏感字段在 Recorder 层统一脱敏后再落盘（§13.3）。

## 17.4 关键指标（§57 线上质量）

| 类 | 指标 |
|---|---|
| 稳定性 | Success/Error/Fallback/Timeout/Cancellation/Tool Failure 率 |
| 质量 | RAG Empty / Low Score 率、引用准确率、用户 Like/Dislike |
| 成本 | Token（in/out/cached）、Cost per run/user/tenant |
| 性能 | P95/P99：LLM/Tool/Retrieval/总耗时 |

用户反馈进入质量闭环（§20）。

---

# 第十八章：Developer Debugging System

## 18.1 目标（§50，§83 Q24/Q25）

5 分钟内定位：问题在哪、为什么、哪个 Step/Tool/Model/Version/User/Tenant/Knowledge/Prompt。

用户投诉"Agent 说错了" → 判别是 **Retrieval / Tool / Model / Prompt / Memory / Knowledge / Permission** 哪一类错误。

## 18.2 Run Timeline（§50）

```
10:01:01 Run Started
10:01:02 Planner Started
10:01:03 LLM Request
10:01:08 LLM Response
10:01:09 Tool Call
10:01:10 RAG Started → Vector Search → BM25 → Rerank
10:01:13 Tool Response
10:01:14 LLM Started
10:01:30 Timeout（STEP_TIMEOUT）
```

开发者直接看到：哪里慢、哪里失败、哪里重试、哪里取消、哪里降级、哪里产生大量 token。

## 18.3 定位方法

1. `trace_id` → Trace 瀑布（§17）→ 最慢/失败 span → payload。
2. 审计交叉验证（权限拒绝/审批/越权）。
3. **Replay**（§60 平台文档）：原样/换参/分步重放 + Diff——"换 prompt/model/检索/tool，对比找变量"。
4. 成本下钻：Tenant→Agent→Run→LLM Call 定位"为什么贵"（§16）。

## 18.4 每 Run 必答清单（20 问，见平台文档 §59.2）

从 run_id 必须能答：哪个 Agent/Prompt/Model 版本、为什么选这个模型、检索到什么、用了哪些 Context、调了哪些 Tool、返回什么、多少 token/钱、哪步最慢/失败、是否重试/降级/熔断/缓存命中、用户权限、是否串会话、能否 Replay。

---

# 第十九章：Evaluation Platform

## 19.1 评测维度（§52-§55）

- **Retrieval**：Recall@K / Precision@K / MRR / NDCG。
- **Generation**：Faithfulness / Answer Relevance / Answer Correctness。
- **Citation**：Citation Accuracy / Completeness。
- **Agent**：Task Success / Tool Selection Accuracy / Tool Argument Accuracy / Planning / Step Count / Loop Rate / Failure Recovery / Cost / Latency。
- **Security**：Prompt Injection 成功率、权限绕过、越权、跨租户、敏感泄露（专用 Adversarial Dataset）。

## 19.2 评测集类型（§56）

| 集 | 来源 | 用途 |
|---|---|---|
| Golden | 人工标注 | 主指标 |
| Adversarial | 专门攻击 | 安全/健壮性 |
| Regression | 生产 bad-case + 修正 | 防止改代码回退 |
| Production | 真实问题脱敏采样 | 线上质量 |

## 19.3 评测框架

- 检索用规则（gold chunk 命中）；生成用 LLM-as-judge（RAGAS 风格）+ 人工抽样锚定。
- **评测集建设**：检索集（gold_chunks）+ 生成集（gold_answer）+ 安全集（注入/越权样本），一次 100 条起步。

---

# 第二十章：Offline / Online Evaluation

## 20.1 离线评测（每次发布前必跑）

```
Golden/Regression 集 → 基线跑一遍 → 改模型/prompt/检索 → 重跑 → 对比
只保留"评测提升"的改动。Recall@k / Faithfulness / Task Success 是门禁。
```

## 20.2 在线评测与数据飞轮（§57）

```
生产流量 → Online 指标监控 → Bad Case → 人工标注 → 评测集
  → Regression Test → 改进 → 离线评测 → 灰度 → 上线 → 监控
```

- 线上监控：Success/Error/Fallback/Timeout/Cancellation/Tool Failure/RAG Empty/Low Score/Token/Cost/P95。
- 用户 Like/Dislike 进反馈系统；bad-case 自动进标注队列，进入飞轮。

---

---

# 第二十一章：Versioning / Gray Release / Rollback

## 21.1 一切可版本化（§58，§83 Q19/Q20/Q21/Q22）

Agent / Prompt / Model / Skill / Tool / RAG 配置 / Chunking / Embedding / Reranker / Policy / Knowledge 全部版本化。**Run 创建时冻结版本集**：

```
agent_version + prompt_version + model_version + tool_version + knowledge_version
```

运行中绝不漂移（保证可复现、可 Replay，§18）。

## 21.2 灰度（Canary / A-B / 百分比）

```
Agent v1 → 5% → 20% → 50% → 100%
```

灰度观察：Quality / Latency / Cost / Error / 用户反馈。任一恶化 → **自动停止灰度并回滚**。

## 21.3 Rollback（§59，§83 Q22）

Rollback 不是只回代码：

```
Code + Prompt Version + Model Version + Tool Version
     + Agent Config + Knowledge Version + Schema Version（一致版本集）
```

- 配置只增不改（新版本 = 新行），回滚 = 切换版本指针（平台文档 §57.7）。
- 知识版本建议不回滚内容，而是用 versioned cache 切换检索版本（§15.2）。
- **Release Contract**（平台文档 §58）：发布前 10 项兼容性检查（API/Queue/DB/Prompt/Tool/Model/Config/Memory/Trace/Rollback）。

---

# 第二十二章：Deployment / Startup / Shutdown / Drain

## 22.1 生命周期操作（§12/§70）

`Start / Stop / Restart / Drain / Pause / Resume`。

## 22.2 Graceful Shutdown（§12）

```
Stop Accepting New Tasks → Stop Scheduling → Drain
  → Checkpoint Running Tasks → Cancel/Pause → Release Resources → Shutdown
```

- **Grace Period**（30s/60s/120s）限时；超时任务交给 Queue/Recovery，**绝不 kill 丢数据**。
- **Liveness ≠ Readiness**：LLM 挂 → Readiness 置否（摘流量），不杀进程（防 K8s 无限重启）。

## 22.3 发布不丢体验（§12，§83 Q9）

- **Stateless Runtime**：会话/运行状态放 DB/Redis，不放进程内存。
- **Connection Draining**：旧实例停接新请求，继续处理已有 HTTP/SSE/WS/进行中 Run。
- **Message Schema 向后兼容**（新旧 Worker 共存）；**Schema Migration** 用 Expand → Migrate → Contract（新旧版本短时共存正确）。
- **Feature Flag** 放量高风险功能（tenant → agent → user → percentage）。
- **Canary 自动停 + 快速 Rollback**（§21.3）。

## 22.4 Sandbox（§18/§82 涉及）

Shell/Code/Browser/File 必须沙箱：进程/容器隔离、CPU/内存限制、网络策略、文件权限、超时强杀、seccomp、Secret 隔离。禁止 Agent 直接访问生产环境。

---

# 第二十三章：百万级知识库性能优化

## 23.1 检索漏斗（§26，§83 Q16）

```
百万块 → Tenant/Partition/Metadata Filter（先过滤后召回）
  → ANN（HNSW/IVF）Top-100 → RRF 融合 50 → Rerank 20~50 → Top 5~10 → Context
```

**绝不** `1,000,000 vectors 全扫描` 或 `全量 → Rerank`。

## 23.2 Partition / 分层索引

```
Tenant → Knowledge Base → Domain/Region Partition → Vector Index
查询：先确定"去哪搜"，再"搜什么"。
```

## 23.3 HNSW / IVF 参数用 Benchmark 定（不凭经验）

| 索引 | 参数 | 调优 |
|---|---|---|
| HNSW | M / efConstruction / efSearch | 数据量/Recall/QPS/延迟/内存基准 |
| IVF | nlist / nprobe | 同上 |

## 23.4 缓存分层（§15/§26）

Query Cache（含 kb_version + permission scope + embed_version）、Retrieval Cache、Embedding Cache（text_hash）、热点预热。冷热数据分离（热数据驻内存/SSD，冷数据对象存储）。

## 23.5 Sharding

按 `tenant_hash / kb / domain` 分片；Cross-Shard 检索 = Parallel Search → Top-K Merge → RRF → Rerank。**过滤优先于检索**（§29 权限前置）。

---

# 第二十四章：高并发与容量治理

## 24.1 容量规划（§66）

| 规模 | 关键约束 | 变化 |
|---|---|---|
| 100 QPS | 单机 + 进程内队列 | — |
| 1K QPS | 多实例 + Redis 限流/锁 | 拆队列 |
| 10K QPS | 分区 + 连接池 + 缓存分层 | 可能拆服务 |
| 100K QPS | 专用向量库 + 消息系统 + HA | 必须拆 |

## 24.2 资源隔离与 Backpressure（§67/§68）

- **Tenant Quota**：并发 / Token / Queue / Storage / Tool Calls / Rate。
- **Backpressure**：LLM/RAG/Embedding/Reranker/Graph 全支持；下游慢 → 上游限产，不无限堆任务。
- **队列水位限流**（§9.3）、**限流分层**（全局/租户/用户/模型，§6.3）。

## 24.3 防无限循环（§69）

`max_steps / max_tool_calls / max_retries / max_wall_time` + 重复 Tool Call/Query/Reasoning 指纹检测（§4.4）。

---

---

# 第二十五章：数据一致性与生命周期

## 25.1 一致性等级（§82 二十五节）

| 数据 | 一致性 | 手段 |
|---|---|---|
| Run/Step 状态 | 强一致（CAS + 事务） | PostgreSQL + 乐观锁 |
| 工具副作用 | 至多一次 | 幂等键 + 缓存结果 |
| 缓存 | 最终一致 | TTL + Versioned Cache + Pub/Sub 失效 |
| 知识索引 | 最终一致 | 增量 Upsert，版本切换 |
| 事件 | 至少一次 + 幂等去重 | event_id |

## 25.2 数据生命周期（§61，§83 Q25 半年可维护）

`Create → Update → Delete → Archive → Retention`：

- 软删 + TTL；删除前归档 S3。
- **用户删除数据 → Vector / Graph / Cache / Memory / Object Storage / 搜索索引必须最终删除**（级联清理任务，§62）。
- 保留策略：审计 180d、Trace 元数据 90d、payload 快照 30d、评测集长期。

## 25.3 知识更新与删除（§62/§63）

Document/Chunk Hash Diff → 只处理新增/修改/删除 → Embedding 缓存跳过未变块 → 按来源整体替换。Knowledge Version 入 Run 版本集（§21.1）。

---

# 第二十六章：数据库与基础设施设计

## 26.1 存储职责划分（§76，不重复存储）

| 数据 | 载体 |
|---|---|
| 身份/Agent/版本/Session/Run/Step/工具/文档/图事实/评测/审批/审计/配置 | PostgreSQL |
| 向量 | pgvector（规模大换专用库） |
| 缓存/锁/限流/Stream | Redis |
| 全文检索 | PG tsvector → OpenSearch |
| 文档原件/快照/artifact | S3 |
| Trace/Metric | OTel 后端（OpenSearch/Tempo/Prometheus） |
| 密钥 | KMS / Secret Manager |

## 26.2 核心表（§75 全模型，字段/索引/约束/状态见平台文档 §8.3 DDL）

Tenant / User / Workspace / Agent / AgentVersion / Session / Run / Step / Tool / ToolVersion / ToolCall / LLMRequest / Message / Memory / KnowledgeBase / Document / DocumentVersion / Chunk / Entity / Relation / Checkpoint / Job / QueueTask / Artifact / Trace / EvaluationCase / EvaluationRun / CostRecord / AuditLog / Configuration / FeatureFlag。

共性：`tenant_id` 全表、`id` UUID PK、`created_at/updated_at/deleted_at` 软删、`version` 乐观锁、唯一约束带 `tenant_id` 前缀、状态字段用状态机非 boolean。

## 26.3 事务边界

- 状态转换 + 事件写入**同一事务**（先写事件再提交状态，§27 幂等）。
- 工具执行结果 + 审计尽量同事务；跨存储（PG + S3 + Redis）用"先写意图后补偿"（Outbox/事件驱动）。

---

# 第二十七章：API 与 Event Design

## 27.1 REST API（§77）

```
POST /agents                      创建 Agent
POST /agents/{id}/runs            发起 Run
GET  /runs/{id}                   查询 Run + Steps
POST /runs/{id}/cancel            取消
POST /runs/{id}/pause|resume      暂停/恢复
POST /runs/{id}/retry             重试（终态后可重跑）
GET  /runs/{id}/trace             追踪
GET  /runs/{id}/events            事件流
POST /tools                       注册工具
POST /knowledge/documents         导入文档
DELETE /knowledge/documents/{id}  删除文档
POST /evaluations                 触发评测
```

统一：Authentication（网关 OIDC/JWT + mTLS）、Authorization（PolicyEngine）、Idempotency（请求幂等键）、Rate Limit、Error Code（§51 统一错误模型）、Trace ID 透传。

## 27.2 事件模型（§78，事件必须幂等/可追踪/可重放）

`AgentRunCreated / AgentRunStarted / StepStarted / LLMRequested / LLMCompleted / ToolCalled / ToolCompleted / RetrievalStarted / RetrievalCompleted / CheckpointCreated / CancelRequested / CancelPropagated / RunCancelled / RunPaused / RunResumed / RunCompleted / RunFailed`

- 事件 = `event_id`（幂等去重）+ `run_id/step_id/trace_id` + payload + 时间。
- 事件写 `event_ledger`（与状态同事务，§26.3），供审计/重放/订阅（Webhook/Stream）。

---

# 第二十八章：测试与 Chaos Engineering

## 28.1 测试金字塔（§79）

Unit（状态机/预算/契约）→ Integration（Runtime 全流程 + DB）→ E2E（API）→ Load（QPS/延迟）→ Chaos（§80）→ Security（注入/越权样本）。

重点场景：LLM Timeout / 429、Tool Timeout、Worker Crash、DB Failure、Queue Backlog、Cancel Race、Duplicate Tool Call、Cross-Tenant、Prompt Injection、Cache Leakage、Deployment、Rollback。

## 28.2 Chaos Engineering（§80）

主动注入：LLM 慢/失败/限流、Vector DB 慢、Graph DB 慢、Redis 故障、Queue 堆积、Worker Crash、网络抖动、第三方 API 失败。

观察系统是否：降级 / 恢复 / 回滚 / 清理资源 / 保持数据一致性。**每轮 Chaos 出具报告**，作为发布门禁。

---

---

# 第二十九章：项目目录与代码架构

```
agent-platform/
├── api/                    # REST 路由（agents/runs/tools/knowledge/evaluations）
├── runtime/
│   ├── execution/          # 执行引擎（§4）：循环、预算、死循环检测
│   ├── scheduler/          # 调度（§9）：优先级、公平、背压
│   ├── state/              # 状态机（§3）：转换表 + CAS
│   ├── cancellation/       # 取消/暂停/恢复（§8）：CancellationToken 传播
│   ├── checkpoint/         # 检查点/恢复（§8）
│   ├── retry/              # 重试策略（§7）
│   ├── timeout/            # 分层超时 + Deadline（§7）
│   └── budget/             # 执行预算（§16）
├── llm/
│   ├── provider/           # Provider 接口（OpenAI/Anthropic/DeepSeek/...）
│   ├── router/             # Model Router（§6）
│   ├── limiter/            # 限流（§6.3）
│   ├── circuit_breaker/    # 熔断（§7.3）
│   └── cost/               # 成本核算（§16）
├── tools/
│   ├── registry/           # 注册/版本/发现（§5）
│   ├── policy/             # 权限/风险/审批闸（§5/§19）
│   ├── executor/           # 执行管线（§5）
│   ├── sandbox/            # 沙箱（§22.4）
│   └── validation/         # 参数/输出校验
├── knowledge/
│   ├── rag/                # 索引 + 混合检索 + RRF + rerank（§10）
│   ├── graph/              # 抽取 + provenance + 时间有效性（§11）
│   ├── memory/             # 记忆读写/隔离/TTL（§12）
│   └── permission/         # 检索前权限过滤
├── queue/
│   ├── scheduler/          # 优先级/公平/背压（§9）
│   ├── worker/             # Worker Pool + Lease/Heartbeat
│   ├── retry/              # 重试队列
│   └── dlq/                # 死信队列
├── security/
│   ├── auth/               # 认证（网关 + mTLS）
│   ├── authorization/      # PolicyEngine（default-deny）
│   ├── injection/          # 注入检测（§13）
│   ├── pii/                # 敏感数据分类/脱敏
│   └── audit/              # 审计
├── observability/
│   ├── tracing/            # OTel span 约定
│   ├── metrics/
│   ├── logging/            # 结构化日志 + 脱敏
│   └── events/             # 事件流
├── evaluation/
│   ├── dataset/            # Golden/Adversarial/Regression/Production
│   ├── runner/             # 评测运行
│   ├── judge/              # LLM-judge / 规则
│   └── regression/         # 回归门禁
├── storage/                # DB/Redis/S3 访问 + 隔离注入
└── config/                 # 版本化配置 + Feature Flag
```

遵循 §82 七十二节：**Modular Monolith First**，模块边界严格（单向依赖 + import-linter），出现性能瓶颈/团队边界/资源隔离/部署需求再拆服务。

---

# 第三十章：MVP → Production → Enterprise 演进路线

## 30.1 阶段划分（§73）

| Phase | 范围 | 交付物 |
|---|---|---|
| Phase 1 单体 Runtime | LLM + Function Calling + Tool + State Machine + RAG + Trace + Evaluation | 可跑通对话+工具+检索+评测 |
| Phase 2 生产治理 | Tenant + Permission + Timeout + Retry + Circuit Breaker + Cancellation + Checkpoint + Cost | 可上线内部试用 |
| Phase 3 高并发 | Queue + Scheduler + Rate Limit + Backpressure + Model Router + Cache | 可支撑外部流量 |
| Phase 4 Knowledge Platform | RAG + Graph + Memory + Hybrid Retrieval | 知识能力完整 |
| Phase 5 企业治理 | Evaluation Platform + Security + Audit + Gray + Rollback + HA/多区域 | 生产级 |

## 30.2 建议排期（3~5 人团队，从 0 开始）

**P0（生产必须有，~8 周）**：Phase 1 + Phase 2 核心——Runtime 状态机/预算/取消、Tool 全管线（权限/幂等/审计）、PolicyEngine 默认拒绝、Trace、崩溃恢复、评测雏形（Recall@k）。这是"能安全运行的最小内核"。

**P1（强烈建议，~4 周）**：队列 + 调度 + 限流 + 熔断降级 + 模型路由 + 检查点续跑 + 敏感数据脱敏。

**P2（规模化后建设）**：Graph、百万级知识库分片、灰度/AB、在线评测飞轮、Sandbox/审批流、混沌工程。

**P3（未来）**：多区域 HA、专用向量库/图库、MCP 生态网关、Agent 市场。

> 原则：先把 **Runtime 内核**打磨到"能安全、可观测、可恢复地运行"，再谈外部能力。不要第一天上 Kafka/K8s/Milvus/Neo4j/几十个微服务（§72）。

---

# 附录：§83 的 25 个"如果……怎么办"逐条回答

| # | 场景 | 答案（落地章节） |
|---|---|---|
| 1 | LLM 挂了 | 熔断（§7.3）+ 降级链 Small/Cached/规则/拒答（§7.4）；Liveness≠Readiness 摘流量不杀进程（§22.2） |
| 2 | LLM 很慢 | 分层超时 + Deadline 传播（§7.1）；Model Router 按延迟切同档更快模型（§6.2） |
| 3 | LLM 被限流 | 指数退避 + 抖动重试（§7.2）+ 换 provider（§6.3）；429 熔断统计 |
| 4 | Tool 挂了 | 熔断 + 超时 + 审计（§5.5）；降级换工具/拒答（§7.4） |
| 5 | Tool 已产生副作用但 Agent 超时 | 幂等键（§5.4）+ 状态 UNKNOWN（§3.4）+ reconcile() 查询第三方；补偿动作可撤销 |
| 6 | 执行一半用户取消 | Cancellation Token 传播（§8.1/§8.2）；LLM 请求 abort 不再耗 token/连接 |
| 7 | Cancel 与 Step 完成同时发生 | 乐观锁 CAS 收敛——谁先提交谁生效（§3.3/§8.5）；已完成的副作用靠幂等键不重复 |
| 8 | Worker 崩溃 | Checkpoint + 重启装载 + 幂等重放（§8.4）；Zombie 靠 Lease/Heartbeat 重入队（§9.3） |
| 9 | 服务正在发布 | Stateless Runtime + Drain + Connection Draining + Schema 兼容 + Canary（§22.3） |
| 10 | 队列堆积 | 水位限流 + 背压 + 降优先级 + 加消费者 + DLQ（§9.3） |
| 11 | 一个租户打爆系统 | Tenant Quota + 每租户队列 + 权重调度 + 限流分层（§14.3/§24.2） |
| 12 | User A 访问到 User B 缓存 | Cache Key 含 tenant/user/permission scope（§15.2）+ 命中先过权限校验 |
| 13 | RAG 文档含 Prompt Injection | UNTRUSTED 分区（§13.1）+ 多层防御（§13.2）+ 注入检测 + 工具权限兜底（§13.2） |
| 14 | Graph 错误关系 | Provenance + 冲突仲裁 + SUPERSEDED 回滚（§11.2/§11.3） |
| 15 | 知识库更新 | Hash Diff 增量 + 按来源替换 + Knowledge Version（§10.4/§25.3） |
| 16 | 百万级检索变慢 | 过滤前置 + Partition + ANN + Rerank 漏斗 + 缓存分层（§23） |
| 17 | Token 成本持续上涨 | 归因 + 指标告警 + 10 项优化 + 禁止全量历史（§16.2） |
| 18 | 模型价格变化 | estimated vs actual cost 分离 + 路由成本过滤 + 对账（§16.1/§6.2） |
| 19 | 新 Prompt 线上质量下降 | 版本化 + 灰度观察质量/延迟/成本 + 自动停 + 回滚（§21） |
| 20 | 新模型质量下降 | 同上 + 离线评测门禁（§20）+ 熔断按 Provider |
| 21 | 发布过程出错 | Canary 自动停 + Release Contract 兼容检查（§21.3） |
| 22 | 快速 Rollback | 一致版本集回滚（§21.3）+ 配置只增不改 + 可验证 |
| 23 | 诡异错误完整复盘 | Trace 20 问（§18.4）+ Run Timeline + 审计交叉 + Replay（§18.3） |
| 24 | "Agent 说错了"归因 | 判 Retrieval/Tool/Model/Prompt/Memory/Knowledge/Permission 七类（§18.1）+ Trace 下钻 |
| 25 | 运行半年保持可维护 | 模块边界 + 契约版本化 + 评测回归 + 可观测完整 + 可回滚（§1.3/§20/§25.2） |

---

> **本文档为《企业级 Agent Runtime 工程化设计方案》v0.1。** 各章细节（DDL、接口、时序图、伪代码、测试用例）见 `enterprise-agent-platform-design.md`（§1–§61）与本仓库 `app/` 实现（Phase 0–3 已落地 Runtime 状态机/预算/取消/恢复、Tool 全管线、PolicyEngine 默认拒绝、审计、限流、SSRF 防护、混合检索 + kb.search）。








