# Enterprise Agent Platform 技术设计与实施规范

> 面向企业生产环境的 Agent 平台：安全、稳定、可观测、可评测、可灰度、可回滚。
>
> 本文档是**阶段性设计文档**，当前为 **Phase 1：总体设计**。后续按你的指令逐模块深化到
> 接口 → Schema → 状态机 → 时序图 → 伪代码 → 测试 → 实际代码。

- 编写日期：2026-08-19
- 文档状态：Draft v0.2（Phase 1 设计 + §49–§61 生产运行治理）
- 目标读者：5 年以上经验的工程师，负责设计/实现/运维企业 Agent 平台
- 立场：Engineering First。每一节回答：为什么存在 / 输入输出 / 数据结构 / 核心 API / 如何实现 / 如何测试 / 如何观测 / 如何排查 / 出错怎么办 / 如何扩展 / 如何保证安全。

## 技术基线（锁定，避免逐节摇摆）

| 域 | 选型 | 说明 |
|---|---|---|
| Agent Runtime / AI Infra | **Python** | 生态（LLM SDK、向量、图算法）最成熟 |
| Control Plane / API | Python（可扩 TypeScript） | 与 Runtime 同语言，降低 MVP 复杂度 |
| 关系库 | **PostgreSQL** | 控制面 + 运行状态 + 事务 |
| 缓存 / 队列 / 分布式锁 | **Redis** | cache / stream / 锁 / 计数 |
| 向量 | **pgvector** 起步 | 不引专用向量库，规模后按 §35 换 |
| 全文检索 | OpenSearch / ES（后置） | MVP 用 PG `tsvector` 先顶 |
| 图 | 后置（Neo4j 或 PG 递归 CTE） | MVP 不做 |
| 对象存储 | S3 兼容（MinIO） | 文档原件、快照、制品 |
| Tracing | **OpenTelemetry** | 全链路标准 |
| 密钥 | KMS + Secret Manager | Secret 不落地代码 |

---

# 第一部分：总体架构

## 1.1 架构原则

1. **能力分层，不把所有能力耦合进 Agent Runtime。** Runtime 只负责执行循环、状态、预算、编排。RAG / Knowledge Graph / Memory / MCP / Tool / Security / Evaluation / Observability 都是独立能力层。
2. **横切基础设施独立。** IAM、Audit、Observability、Cost、Rate Limit、Config、Feature Flag、Gray Release 不塞进任何业务模块。
3. **可观测是硬性验收条件。** 任何一次 Run 必须能回答 §7 的"可回答清单"，回答不了视为不合格。
4. **简单优先。** 模块化单体起步（Modular Monolith），边界严格，必要时再拆服务。
5. **版本化一切。** Agent / Prompt / Model / Skill / Tool / Knowledge / Policy / Configuration 全部版本化，可灰度、可回滚。
6. **服务端强制隔离。** tenant_id / user_id 全模型覆盖，权限在服务端强制执行，不依赖前端。
7. **默认拒绝（Deny by default） + 最小权限。** 工具、数据、资源默认不可访问，显式授予。

## 1.2 分层架构

```
┌──────────────────────────────────────────────────────────────┐
│  Client Layer                                                  │
│  Web Console │ CLI │ SDK │ Open API                            │
└──────────────────────┬───────────────────────────────────────┘
┌──────────────────────▼───────────────────────────────────────┐
│  Edge Layer                                                    │
│  API Gateway：认证·限流·路由·请求审计入口·TLS 终止              │
└──────┬───────────────────────────────────────────────────────┘
       │
┌──────▼─────────────  ┌──────────────────────────────────────┐
│  Control Plane       │  Data Plane（执行面）                  │
│  （低频·治理·CRUD）    │  （高频·状态·可水平扩展）              │
│                      │                                       │
│  Identity / Tenant   │  Agent Runtime（执行引擎）             │
│  Agent Mgmt          │    · 状态机 · 预算 · 编排 · 恢复        │
│  Tool Registry       │  Model Gateway（LLM 统一出口）          │
│  Skill Mgmt          │  Context Engine                        │
│  Knowledge Platform  │  Tool Runtime（执行面）                 │
│  Eval Platform       │  Memory 服务                            │
│  Experiment / Config │  Retrieval 服务（RAG / Graph 网关）     │
│  Approval Mgmt       │                                        │
└──────┬─────────────  └───────┬──────────────────────────────┘
       │                       │
       │  ┌────────────────────┘
       ▼  ▼
┌──────────────────────────────────────────────────────────────┐
│  Platform Infrastructure（横切，所有模块共同依赖）             │
│  IAM / Policy Engine · Audit · Observability(OTel) ·          │
│  Cost Control · Rate Limit · Config Center · Feature Flag     │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  Storage / Infra                                               │
│  PostgreSQL │ Redis │ pgvector │ OpenSearch │ S3 │ KMS/Secret │
│  Queue(Redis Stream / SQS) │ OTel Backend                     │
└──────────────────────────────────────────────────────────────┘
```

**Control Plane 与 Data Plane 的划分动机**：
- Control Plane 是**治理面**：创建/配置/发布/评估/审计。低频、无状态、天然可水平扩展。
- Data Plane 是**执行面**：真正跑 Agent Loop。高频、有状态（Run/Step 状态外置到 PG/Redis）、是唯一需要认真做并发与恢复的地方。
- 划分后，控制面的故障不应影响正在执行的 Run；执行面的扩容只需加无状态 Executor 实例。

## 1.3 服务边界与模块边界

| 模块 | 归属 | 职责（只做这些） | 不做什么 |
|---|---|---|---|
| API Gateway | Edge | 认证、限流、路由、TLS、请求审计入口 | 不做业务逻辑 |
| Identity | Control | 用户/租户/角色/组/认证 | 不做授权判定（Policy 归 IAM） |
| Agent Mgmt | Control | Agent 定义与版本 CRUD、发布/灰度/回滚 | 不执行 Run |
| Agent Runtime | Data | 执行循环、状态机、预算、编排、恢复 | 不实现检索、不直接调 LLM provider |
| Model Gateway | Data | provider 路由、重试、限流、成本统计、fallback | 不感知 Agent 语义 |
| Context Engine | Data | 组装/预算/过滤/排序/隔离上下文 | 不生成内容 |
| Tool Runtime | Data | 工具执行、沙箱、审批闸、幂等、熔断 | 不决定工具语义（由 Tool 自身定义） |
| Tool Registry | Control | 工具注册、版本、发现、健康、灰度 | 不执行 |
| Knowledge Platform | 能力层 | 文档→解析→分块→索引；检索（RAG/图） | 不做权限判定（只按传入主体过滤） |
| Memory 服务 | 能力层 | 记忆读写、TTL、检索 | 不做跨用户读写 |
| Evaluation | Control | 评测集、评测运行、指标 | 不影响线上流量 |
| Config/Feature Flag | 横切 | 版本化配置、开关 | 无 |
| IAM/Policy | 横切 | 授权判定、资源权限 | 无 |
| Audit | 横切 | 全量审计日志 | 无 |
| Observability | 横切 | Trace/Metric/Log | 无 |

## 1.4 数据流与控制流

**控制流（一次对话请求）**：

```
请求 → Gateway(认证/限流) → Agent Runtime
     → 加载 AgentVersion + Config + FeatureFlag
     → Context Engine（system + session history + memory + 检索结果）
     → Model Gateway → LLM
     → 若 tool_calls：逐 tool → Policy Engine → Tool Runtime（审批闸/沙箱/执行）
       → 结果回写 Context → 再调 LLM（循环，受 Execution Budget 约束）
     → 生成最终答案 → 持久化 Run/Step/Trace → 返回
```

**数据流（两条主链路）**：

- **在线链路**：用户 query → 检索通道（向量/BM25/图）→ 融合/重排 → Context → LLM → 答案 + 引用。每步产生 Trace。
- **离线链路**：文档 → Parser → Cleaner → Chunking → Embedding → 向量+倒排+图索引 → 增量维护；评测集 → 评测 Run → 指标 → 回归。

## 1.5 同步任务 vs 异步任务

| 类型 | 例子 | 载体 |
|---|---|---|
| 同步 | 对话请求、快速工具调用、检索 | HTTP 长连接 / SSE 流式 |
| 异步 | 文档 ingest、批量评测、大模型重排、审批通知、Replay 长任务 | Redis Stream / SQS + Worker |
| 定时 | 知识库增量轮询、成本对账、索引维护 | 调度器（Cron/分布式调度） |

## 1.6 关键架构决策（ADR，含反选理由）

| # | 决策 | 理由 | 什么时候推翻 |
|---|---|---|---|
| ADR-01 | **模块化单体起步** | 3~5 人团队，拆分收益 < 成本 | 单模块职责失衡 / 独立扩容需求明确 |
| ADR-02 | **Runtime 无状态化，状态外置 PG+Redis** | 水平扩展、崩溃恢复的基础 | 无 |
| ADR-03 | **RAG/Graph/Memory 是能力层，非核心** | 可插拔、可替换、不绑架架构 | 无 |
| ADR-04 | **检索通道统一抽象** | Runtime 不感知"向量还是图还是 SQL" | 检索语义分化到无法统一 |
| ADR-05 | **pgvector 起步，不引专用向量库** | 简单优先；数据量起来再换 | 单表块数 > ~500 万 / 需要复杂过滤 |
| ADR-06 | **全模型带 tenant_id，服务端强制** | 隔离是硬性合规 | 无 |
| ADR-07 | **模型访问统一走 Model Gateway** | 路由/限流/成本/fallback 集中一处 | 无 |
| ADR-08 | **所有 artifact 版本化** | 灰度/回滚的前提 | 无 |

---

# 第二部分：核心边界

## 2.1 边界三原则

1. **单向依赖**：依赖方向只能从上往下——`Gateway → Control/Data → 能力层 → 横切 → Storage`。能力层（RAG/Graph/Memory/Tool）**不得反向依赖** Runtime；横切基础设施不得依赖业务模块。
2. **契约即边界**：模块间通过**版本化契约**通信（ToolCall/ToolResult、RetrievalRequest/RetrievalResult、LLMRequest/LLMResponse、ContextBlock）。契约变更必须走版本演进，不允许悄悄改字段。
3. **横切强制接入**：任何模块不得绕过 Policy Engine、不得绕过 Trace/Metric/Log、不得绕过 Audit。这是 CI/评审红线。

## 2.2 关键模块边界契约

| 模块 | 输入 | 输出 | 关键依赖 | 禁止 |
|---|---|---|---|---|
| Agent Runtime | `AgentRunRequest` | `RunResult` + 事件流 | ModelGateway, ToolRuntime, ContextEngine, Memory, Retrieval, Policy | 直连 LLM provider / 直连 MCP / 自己实现检索 / 自己读 secret |
| Model Gateway | `LLMRequest{provider_hint, messages, params}` | `LLMResponse{content, tool_calls, usage, cost}` | provider SDK | 业务绕过它直连 provider |
| Tool Runtime | `ToolCallRequest{tool_ref, args, ctx}` | `ToolCallResult{ok, data, error}` | Registry, Policy, Sandbox, SecretManager | 把 secret/credential 暴露给 LLM / 绕过审批 |
| Context Engine | 原始材料（指令+历史+检索+工具结果） | 组装好的 `Context`（带 trust 分级） | Policy(过滤), Budget | 把 UNTRUSTED 数据当指令混排 |
| Knowledge（检索） | `RetrievalRequest{query, scope, k, filters}` | `RetrievalResult{chunks[], scores, provenance}` | 索引存储 | 跨租户读取 / 返回无 provenance 的结果 |
| Memory 服务 | `MemoryWrite/ReadRequest{subject}` | 记忆条目 / 检索结果 | Policy | 跨用户/租户读写 |
| Evaluation | `EvalRunRequest{dataset, config}` | 指标报告 | 检索/生成管线（只读） | 影响线上流量 |

## 2.3 横切接入点（Enforcement Points）

所有模块必须接入以下切面（由框架层强制，不靠自觉）：

- **Policy Enforcement**：每次对 Tool / 数据 / Memory / 检索的访问，先过 `PolicyEngine.is_allowed(subject, action, resource, ctx)`，Deny 即拒绝并写审计。
- **Trace**：模块内每个内部调用至少一个 span；带 `run_id / step_id / tenant_id / user_id` 等属性。
- **Audit**：权限决策、工具执行、数据访问、审批动作四类事件必须写 AuditLog。

## 2.4 失败边界

每个模块明确自己的"失败责任区"，不得把不确定性扩散：

- **Model Gateway**：负责 provider 超时/限流/降级/成本核算。失败抛出 `MODEL_*` 错误码。
- **Tool Runtime**：负责工具超时/重试/熔断/幂等/沙箱。失败抛 `TOOL_*` 错误码，且**不泄漏内部 secret**。
- **Retrieval**：失败抛 `RAG_FAILED / GRAPH_FAILED`，由 Runtime 降级（关键词检索 / 拒答），绝不把异常当作空结果硬编。
- **Runtime**：任何子环节失败都收敛到**统一错误体系**（§33，Phase 后详），且 Run 状态机转移到可恢复状态。

## 2.5 边界验证方式

- **契约测试**：对每个契约（请求/响应模型）做 schema 快照 + 兼容性测试。
- **依赖方向检查**：CI 中用 import-linter 或架构测试禁止反向依赖。
- **横切接入检查**：静态扫描保证新模块必经的包装器（policy/trace wrapper）被调用。

---

---

# 第三部分：Agent Runtime

## 3.1 为什么存在

Agent Runtime 是整个平台的**执行引擎**，也是唯一真正"有状态、会失败、需要恢复"的地方。它的职责是**把一次 Run 从请求推进到终态**，并且任何一步失败都可以恢复、重放、审计。所有其他能力（检索、工具、模型）对 Runtime 而言都是"被编排的资源"。

## 3.2 核心数据结构（Pydantic 契约）

```python
# ---- 状态 ----
class AgentState(str, Enum):
    REQUESTED = "REQUESTED"  # 已接收，排队
    PLANNING = "PLANNING"  # 首轮上下文组装 + LLM 调用
    RUNNING = "RUNNING"  # 循环推进中
    WAITING_TOOL = "WAITING_TOOL"  # 已发出 tool_calls，等待执行结果
    OBSERVING = "OBSERVING"  # 工具结果回填、校验、注入检测
    REFLECTING = "REFLECTING"  # 评估是否需要继续/自评
    COMPLETED = "COMPLETED"  # 终态：成功
    FAILED = "FAILED"  # 终态：不可恢复失败
    RETRYING = "RETRYING"  # 可重试失败，正在重试
    CANCELLED = "CANCELLED"  # 终态：用户/系统取消
    TIMEOUT = "TIMEOUT"  # 终态：超预算/超时
    WAITING_APPROVAL = "WAITING_APPROVAL"  # 阻塞在高风险工具审批


# ---- Run ----
class AgentRun(BaseModel):
    run_id: str
    tenant_id: str
    user_id: str
    agent_id: str
    agent_version: str  # 快照版本号（配置/提示词绑定在此）
    session_id: str
    state: AgentState
    budget: ExecutionBudget  # 见下
    model_config: ModelConfig  # 本次用哪个模型
    input: RunInput  # 原始用户请求 + 附加
    error: ErrorInfo | None
    timestamps: {...}  # 各阶段耗时
    checkpoint_id: str  # 最后持久化的检查点


class AgentStep(BaseModel):  # 一次循环迭代（一次"思考+动作"）
    step_id: str
    run_id: str
    seq: int
    state: AgentState  # 该步结束时状态
    input: StepInput  # 该步进入时的上下文摘要
    llm_call: LLMRecord | None  # model/messages/tool_calls/usage/cost/latency
    tool_calls: list[ToolCallRecord]
    observations: list[Observation]  # 工具结果 + 注入检测结果
    decision: StepDecision  # 继续 / 完成 / 中止 / 转审批
    tokens_used: int
    cost: Decimal


class ExecutionBudget(BaseModel):
    max_steps: int = 30  # 循环上限
    max_tokens: int = 200_000  # 累计 LLM token 上限
    max_cost: Decimal = 10.0  # 金额上限
    max_tool_calls: int = 50
    max_runtime_s: int = 600
    max_retries: int = 3
```

## 3.3 状态机

```
REQUESTED ──▶ PLANNING ──▶ RUNNING ──▶ WAITING_TOOL ──▶ OBSERVING
   │            │            │   ▲            │              │
   │            │            │   │            ▼              │
   │            │            │   └─────────── REFLECTING ─────┘
   │            │            │                      │
   │            │            │                      │ 完成
   │            │            ▼                      ▼
   │            │        ┌─ 需要审批：WAITING_APPROVAL ──▶ RUNNING（继续）
   │            │        │
   │            └────────┴─▶ COMPLETED（成功）
   │
   └──▶ FAILED / RETRYING / CANCELLED / TIMEOUT（终态或转移）
```

| 当前状态 | 事件 | 目标状态 | 守卫条件 |
|---|---|---|---|
| REQUESTED | `acquire_run`（取锁成功） | PLANNING | 同 run 无并发执行 |
| PLANNING | 首轮 LLM 成功 | RUNNING | — |
| PLANNING | 首轮 LLM 可重试失败 | RETRYING | retries < max |
| RUNNING | LLM 返回 tool_calls | WAITING_TOOL | tool_calls 非空 |
| RUNNING | LLM 返回最终答案 | REFLECTING | tool_calls 为空 |
| RUNNING | 预算超限 | TIMEOUT | 任一 budget 超限 |
| WAITING_TOOL | 全部工具结果就绪 | OBSERVING | 含并行调用全部返回 |
| WAITING_TOOL | 工具需审批 | WAITING_APPROVAL | 风险引擎判定高风险 |
| WAITING_APPROVAL | 批准 | RUNNING | 审批通过 |
| WAITING_APPROVAL | 拒绝 / 超时 | CANCELLED | — |
| OBSERVING | 结果注入检测 + 回填完成 | REFLECTING | — |
| REFLECTING | 判定继续 | RUNNING | steps < max_steps |
| REFLECTING | 判定完成 | COMPLETED | — |
| REFLECTING | 判定中止 | CANCELLED | — |
| RETRYING | 重试成功 | 回到原状态 | retries < max |
| RETRYING | 重试耗尽 | FAILED | — |
| *（任意） | 用户取消 | CANCELLED | 幂等取消 |

**状态机实现要点**：
- 状态转换**只允许通过 `transition()`**（带守卫 + 校验 + 审计），禁止业务代码直接改 `state` 字段。
- 每个转换在 PG 写一条 `agent_steps` + 状态历史，崩溃后可重放。
- `WAITING_APPROVAL` 是唯一可长时间阻塞的状态，必须设置审批超时（默认 24h，超时视为拒绝）。

## 3.4 并发模型

- **每个 Run 一个执行器协程**，单 Run 内部**步骤串行**（这是语义正确的前提：下一步依赖上一步上下文）。
- **步骤内工具调用可并行**：同一轮的多个 `tool_calls` 并行执行，用有界并发（默认 4）控制资源。
- **Run 之间水平并行**：Executor 无状态，`acquire_run` 通过 Redis 分布式锁保证**同一 run 只有一个执行者**，防止重复执行（重试/双实例）。
- **有界并发**：全局信号量限制并发 Run 数；排队超过水位进入队列，避免打爆 Model Gateway。

## 3.5 生命周期

```
create_run(校验输入) → acquire_run(锁+状态置 REQUESTED)
→ execute_loop:
    每步: 组装上下文 → ModelGateway.llm() → 
          [tool_calls? 执行(审批闸/沙箱) : 收束答案]
    每步结束: 持久化 step + 检查点 + 预算快照 + Trace
→ finalize: 置终态，写 run 结果，释放锁，触发事件（回调/Webhook）
```

## 3.6 持久化与恢复

- **持久化**：`agent_runs`（一行）+ `agent_steps`（每步一行）+ `run_state_history`。检查点 = 最后一条 step + 预算快照。
- **崩溃恢复**：Executor 启动时扫描 `RUNNING/PLANNING/WAITING_TOOL` 且锁超时的 Run，从最后检查点**重放**：未完成的工具调用按幂等键跳过，未发起的 LLM 调用重新发起。
- **恢复语义**：工具调用采用**至多一次 + 幂等键**（Tool 层支持 idempotency，见 §4）；LLM 调用本身不可幂等，故记录完整请求以支持 Replay。
- **不丢事件**：关键事件（状态转换、工具结果、审批、失败）先写 `event_ledger` 再推进状态，保证审计与重放的数据完整。

## 3.7 执行预算（防止无限循环）

预算在**每步结束时快照**并持久化，超出任何一项即触发 `transition(TIMEOUT)`：

| 预算 | 默认 | 触发动作 |
|---|---|---|
| max_steps | 30 | 停止循环，置 TIMEOUT |
| max_tokens | 200k | 停止下一次 LLM 调用 |
| max_cost | 10 元 | 停止下一次 LLM 调用，可配审批放行 |
| max_tool_calls | 50 | 不再接受新的工具调用 |
| max_runtime_s | 600 | 强杀执行器协程 |
| max_retries | 3 | 超过即 FAILED |

**死循环检测**：对每步做 `(意图摘要, 工具名, 参数指纹)` 哈希，连续 N 步（默认 3）指纹相同 → 判定循环 → 中断并写告警。

## 3.8 失败处理

- 可重试失败（网络抖动、LLM 5xx、工具超时）→ `RETRYING`，指数退避 + 抖动，上限 `max_retries`。
- 不可恢复失败（参数错误、权限拒绝、契约不匹配）→ `FAILED`，保留完整现场。
- 预算耗尽 → `TIMEOUT`，返回"已达到资源上限"的**显式**结果，不是幻觉回答。
- 所有失败统一映射到错误体系（§33 后续详述），`error` 字段可观测、可 Replay。

## 3.9 测试策略

1. **状态机转移表测试**：每个 `(state, event, guard)` 组合，断言目标状态 + 副作用。
2. **预算测试**：分别打到 max_steps / max_tokens / max_cost，断言 TIMEOUT 且无泄漏。
3. **崩溃恢复注入测试**：在每步任意点 kill 进程 → 重启 → 断言从检查点恢复且不重复执行工具。
4. **死循环检测测试**：喂一个必然重复调用的模型桩，断言在 N+1 步中断。
5. **并发测试**：同一 run 并发触发两次执行，断言只有一个执行者（锁生效）。
6. **可观测断言**：每个测试 run 都产出完整 trace（run_id/step_id/span 齐全），作为 CI 硬门禁。

---

# 第四部分：Tool Runtime

## 4.1 为什么存在

Tool 是 Agent 与真实世界的接口，也是**最大的攻击面**（命令执行、数据外泄、越权）。Tool Runtime 把"执行一个工具"统一成一条**有治理、有安全闸、可观测**的管线，而不是让 Runtime 直接 `await some_function()`。

## 4.2 Tool 抽象（统一契约）

```python
class ToolDefinition(BaseModel):
    tool_ref: str  # 全局唯一，如 "platform.search.web"
    name: str
    version: str  # 工具本身版本
    kind: ToolKind  # FUNCTION/HTTP/MCP/INTERNAL/DB/BROWSER/CODE/SHELL/FILE/SEARCH/RAG/GRAPH
    description: str
    input_schema: dict  # JSON Schema（参数校验 + 暴露给 LLM）
    output_schema: dict | None  # 输出校验
    permission: ToolPermission  # 所需权限点，如 knowledge.search
    risk_level: RiskLevel  # READ / LOW_RISK_WRITE / HIGH_RISK_WRITE / CRITICAL
    policy: ToolPolicy  # 超时/重试/熔断/限流/幂等/是否需审批
    tenant_scoped: bool
    status: ToolStatus  # DRAFT/ACTIVE/DEPRECATED/DISABLED
    executor: ToolExecutorRef  # 绑定到某个执行器实现


class ToolCallRequest(BaseModel):
    call_id: str  # 幂等键
    tenant_id: str
    user_id: str
    agent_id: str
    run_id: str
    step_id: str
    tool_ref: str
    args: dict  # 已解析的参数
    trace_ctx: dict  # 透传 trace/审计上下文


class ToolCallResult(BaseModel):
    call_id: str
    ok: bool
    data: Any | None
    error: ToolError | None  # 错误码体系内
    latency_ms: int
    cost: Decimal | None
    redacted_output: bool  # 是否经脱敏处理
```

## 4.3 执行器类型与沙箱需求

| kind | 执行形态 | 沙箱/隔离要求 |
|---|---|---|
| FUNCTION | 进程内函数调用 | 无（纯计算），走验证 |
| HTTP / INTERNAL | 出站 HTTP（mTLS） | 网络策略、SSRF 防护 |
| DATABASE | 只读 SQL / 白名单操作 | 连接级最小权限、SQL 注入校验 |
| MCP | MCP Client → MCP Server | MCP server 身份认证、工具白名单、网络隔离 |
| BROWSER | 浏览器自动化 | 独立容器/无头浏览器，网络隔离 |
| CODE / SHELL | 代码/命令执行 | **必须沙箱**：容器 + CPU/内存限制 + 超时 + 网络策略 + seccomp |
| FILE | 文件读写 | 仅限临时工作区，禁止越界路径 |
| SEARCH / RAG / GRAPH | 检索能力 | 权限过滤在服务端，返回带 provenance |

## 4.4 执行管线（伪代码）

```
def execute(call: ToolCallRequest) -> ToolCallResult:
    tool = registry.resolve(call.tool_ref, version)          # 1 解析（找不到→TOOL_NOT_FOUND）
    policy.assert_active(tool)                                # 2 状态检查
    policy.is_allowed(subject, tool.permission, resource)     # 3 权限（拒绝→TOOL_PERMISSION_DENIED）
    args = validate(call.args, tool.input_schema)             # 4 参数校验（注入/越界/类型）
    risk_engine.maybe_require_approval(tool, call)            # 5 审批闸（HIGH_RISK/CRITICAL → WAITING_APPROVAL）
    rate_limiter.acquire(tool, tenant, user)                  # 6 限流
    breaker.pre(call)                                         # 7 熔断检查
    idem = idempotency.get(call.call_id)                      # 8 幂等（命中→直接返回上次结果）
    result = executor.run(tool, call, sandbox)                # 9 执行（超时/重试/沙箱，secret 由 runtime 注入）
    out = validate_output(result, tool.output_schema)         # 10 输出校验（脱敏/注入检测）
    breaker.post(call, result.ok)                             # 11 熔断统计
    audit.write(tool, call, result)                           # 12 审计
    metrics.record(tool, result)                              # 13 指标
    return out
```

## 4.5 Tool Registry

- **注册**：Control Plane 提供 `POST /tools`；`tool_ref` 全局唯一，注册即生成 `tool_versions`。
- **发现/版本**：Runtime 按 `tool_ref + version` 解析；支持 Canary（新版本对指定租户/用户生效）。
- **健康**：对 HTTP/MCP/DB 类工具做周期探活，失败进入 DEGRADED，`registry.resolve` 拒绝新调用。
- **灰度/下架**：ACTIVE → DEPRECATED（存量 Run 可继续）→ DISABLED（新调用拒绝）。**不允许直接删工具**（Trace/审计要能回溯）。

## 4.6 工具生命周期

```
DRAFT（草稿，仅测试）
  │ 审批/测试通过
ACTIVE（生产可调）
  │ 发现问题
DEPRECATED（保留存量，禁止新调用）
  │ 迁移完成
DISABLED（完全下线，数据保留）
```

## 4.7 治理能力（每项默认 + 配置）

| 能力 | 默认 | 说明 |
|---|---|---|
| timeout | 30s（HTTP/计算） | 超时返回 TOOL_TIMEOUT，不悬空 |
| retry | 0 次 | 仅对"明确幂等 + 瞬时失败"工具启用 |
| circuit breaker | 5 次失败 / 60s 窗口 | 熔断期间直接拒绝（TOOL_BREAKER_OPEN） |
| rate limit | 租户级 + 用户级 | 见 §29 |
| idempotency | call_id 为幂等键 | 同 call_id 重放返回缓存结果，窗口默认 24h |
| audit | 强制 | 每次调用落 AuditLog |

## 4.8 安全红线

1. **Secret 不暴露给 LLM**：工具需要凭据时，定义 `credential_ref`，由 SecretManager 在**执行阶段**注入执行器，LLM 永远看不到真实值（§17 详述）。
2. **输入校验即注入防线**：参数 JSON Schema + 业务校验（路径越界、SSRF 目标、SQL 注入特征）。
3. **输出脱敏**：工具返回可能含 PII/密钥，执行层做 masking/redaction（§17）。
4. **最小权限执行**：DB 用只读/白名单账号、文件限制工作区、Shell 进沙箱。
5. **审计完整**：call_id / args / result 摘要 / 决策链（权限、审批、熔断）全量记录。

## 4.9 统一抽象（与 MCP/HTTP/Function 的关系）

```
上层（Agent Runtime）只认识 ToolCallRequest / ToolCallResult
                    │
            ToolProvider（统一接口）
        resolve() / execute() / health()
          │         │         │
   FunctionProvider  HttpProvider  McpProvider  ...（每种 kind 一个）
```

- Agent 层**不感知**底层是 MCP 还是 HTTP 还是本地函数。
- MCP 通过 `McpProvider`（MCP Client）接入：每个 MCP Server 映射为一组 `ToolDefinition`，工具白名单 + 参数透传校验在 Provider 内完成。**MCP ≠ Function Calling**：MCP 是"工具发现与传输协议"，Function Calling 是"LLM 结构化出参 → 执行"的编排层；两者在 `ToolProvider` 处汇合（§8 后续详述）。

## 4.10 测试策略

1. **契约测试**：每个 kind 至少一个冒烟工具，断言 ToolCallRequest/Result 契约稳定。
2. **熔断/限流/幂等测试**：注入故障，断言熔断开门、限流拒绝、幂等重放。
3. **沙箱逃逸测试**：CODE/SHELL 工具喂路径穿越、命令注入、资源耗尽样本。
4. **SSRF 测试**：HTTP 工具喂内网地址，断言被拦截。
5. **审计完整性测试**：CI 断言每个工具调用产生完整 audit + trace。

---

---

# 第五部分：Context Engine

## 5.1 为什么存在

Context 是"模型看到什么"。它同时决定**生成质量**（好上下文 → 好答案）、**成本**（token 预算）和**安全**（注入防护、数据隔离）。Context Engine 把"拼 prompt"从业务代码里抽出来，变成一条有预算、有信任分级、可审计的管线。

## 5.2 Context 类型与信任分级

| Context 类型 | 来源 | 信任级 | 默认预算占比 |
|---|---|---|---|
| system | 平台/Agent 作者配置 | **TRUSTED** | 低，但优先 |
| user | 用户本轮输入 | **TRUSTED**（本会话） | 中 |
| task | 任务目标/工具可用清单 | TRUSTED | 中 |
| history | 会话历史 | TRUSTED（会话内，但需注入检测） | 中 |
| memory | Memory 服务召回 | **UNTRUSTED**（可能被污染） | 低 |
| knowledge | RAG / Graph / 检索结果 | **UNTRUSTED**（文档可能被投毒） | 高 |
| tool | 工具结果 | **UNTRUSTED**（返回值可能含注入/敏感数据） | 中 |
| observation | 工具结果注入检测后的观察摘要 | TRUSTED（由检测层生成） | 低 |

**核心安全原则：UNTRUSTED 数据永远是"数据"，绝不与指令混排。** 这是防止 Prompt Injection / RAG Poisoning / Memory Poisoning 的第一道也是最重要的一道墙（§6 详述多层防御）。

## 5.3 ContextBlock 结构

```python
class TrustLevel(Enum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"


class ContextBlock(BaseModel):
    block_id: str
    ctx_type: ContextType  # SYSTEM/USER/TASK/HISTORY/MEMORY/KNOWLEDGE/TOOL/OBSERVATION
    trust: TrustLevel
    source: str  # 块来源标识（如 "kb:doc123#chunk456"），用于引用/审计
    priority: int  # 预算裁剪时保留优先级
    tokens: int  # 预估 token 数
    text: str
    meta: dict  # provenance / 权限 / 时间
```

## 5.4 Builder 管线（伪代码）

```
def build_context(request, agent_config, runtime_state) -> Context:
    blocks: list[ContextBlock] = []
    blocks += system_blocks(agent_config)                # 指令、工具清单、输出格式
    blocks += task_blocks(request)                       # 任务目标
    blocks += history_blocks(session, request)           # 会话历史（裁剪+摘要）
    blocks += memory_blocks(request)                     # 记忆召回（UNTRUSTED，单独分区）
    blocks += retrieval_blocks(request)                  # 检索结果（UNTRUSTED，<context> 分区）
    blocks += observation_blocks(request)                # 工具结果检测后的摘要

    blocks = filter_by_policy(blocks, subject)           # 权限过滤（在组装前！）
    blocks = dedupe(blocks)                              # 按 block_id 去重
    blocks = rank(blocks)                                # 预算内排序（分数/优先级）
    blocks = budget_truncate(blocks, token_budget)       # 溢出裁剪，绝不半块截断
    blocks = inject_detection(blocks)                    # 对 UNTRUSTED 做注入检测标注
    return assemble(blocks)                              # 按 trust 分区组装 + 引用编号
```

## 5.5 预算管理

- **总预算**：`max_context_tokens`（来自 Config，默认按模型窗口的 60%）。
- **按类型上限**：`{memory: 5%, knowledge: 40%, tool: 20%, history: 20%, system/task: 15%}`，可配。
- **溢出策略**：按 `priority` 从低到高整块丢弃（**绝不半块截断**），knowledge/tool 块按重排分数排序后取高分者。
- **稳定性**：同输入同配置 → 同顺序（可复现、可缓存、可对比）。

## 5.6 防污染 / 防注入 / 防泄漏 / 防 lost-in-middle

| 风险 | 对策 |
|---|---|
| 指令污染 | UNTRUSTED 与指令强制分区；模型被告知"只信指令区，<context> 是数据" |
| Prompt Injection（用户输入） | 输入检测 + 指令区前置 + 参数校验 + 输出校验（多层，见 §6.6） |
| RAG/Memory 投毒 | UNTRUSTED 分级 + 注入检测标注 + 引用必须可回源（provenance） |
| 数据泄漏（越权检索） | 权限过滤**在检索层**完成（§2.3 Enforcement Point），组装层只做脱敏兜底 |
| Context Overflow | 预算 + 整块裁剪 |
| Lost in Middle | 指令放首尾、证据按分数排序、控制块数（默认 ≤ 20） |
| 泄露敏感字段 | 组装层对 UNTRUSTED 块做 masking/redaction（§17） |

## 5.7 测试策略

1. **预算裁剪测试**：构造超预算输入，断言整块丢弃、顺序稳定、不半块截断。
2. **注入测试**：在用户/检索/工具结果里埋"忽略指令"样本，断言注入检测命中 + 分区隔离生效。
3. **权限过滤测试**：低权限主体请求含高权限块的上下文，断言组装前已被过滤。
4. **稳定可复现测试**：相同输入两次构建，断言 block 序列一致。

---

# 第六部分：Security / IAM

## 6.1 认证（Authentication）

- **边缘**：API Gateway 统一做认证 —— OIDC / JWT（面向用户）、mTLS + service token（面向服务间）。
- **身份传播**：请求上下文携带 `subject(tenant_id, user_id, roles, groups, attributes)` 贯穿全链路；任何模块都不得"以自身身份"冒充用户访问数据。
- **密钥**：所有 provider/工具凭据存 KMS/SecretManager，代码与配置里只出现 `credential_ref`。

## 6.2 授权模型（RBAC + ABAC）

- **RBAC**：`User → Group → Role → Permission`；角色给"身份"。
- **ABAC**：Policy 用属性条件给"场景"（如 `resource.tenant_id == subject.tenant_id && resource.owner_id == subject.user_id`）。
- **Policy 结构**：

```python
class Policy(BaseModel):
    policy_id: str
    effect: "ALLOW" | "DENY"  # 默认 DENY
    subject: SubjectSelector  # user/group/role/any
    action: ActionSelector  # "tool:execute" / "knowledge:search" / "memory:read" ...
    resource: ResourceSelector  # agent_id / tool_ref / kb_id / memory_scope / "resource.type:xxx"
    condition: ABACCondition | None  # 属性表达式
```

- **决策函数**：

```python
def is_allowed(subject, action, resource, ctx) -> bool:
    # 1) 硬性隔离（服务端强制，不可被 Policy 覆盖）
    assert_resource_in_tenant(resource, subject.tenant_id)
    # 2) 逐条评估（显式 DENY 优先）
    for p in policies_for(subject, action, resource):
        if not p.matches(subject, action, resource, ctx):
            continue
        if p.effect == DENY:
            return deny(reason=p.policy_id)
        allow = p
    # 3) 默认拒绝
    return allow if allow else deny("default-deny")
```

## 6.3 资源权限点（Enforcement Points）

| 资源类型 | 判定动作 | 说明 |
|---|---|---|
| Agent | `agent:use` / `agent:publish` / `agent:rollback` | 使用/发布/回滚 |
| Tool | `tool:execute` | 叠加工具自身的 risk_level |
| Knowledge | `knowledge:search` / `knowledge:ingest` | 按 KB 级过滤 |
| Memory | `memory:read` / `memory:write` | 严格主体绑定 |
| Run / Session | `run:view` / `session:view` | 仅 owner/被授权者 |
| Eval / Config | `eval:run` / `config:edit` | 控制面权限 |

## 6.4 隔离模型（服务端强制）

- 所有核心表带 `tenant_id`；关键资源再加 `owner_id / project_id / agent_id / session_id`（§8）。
- **隔离层级**：Tenant → User → Agent → Session → Memory → Knowledge → Tool Permission → Trace → File → Cache。每层在数据访问的 **SQL/API 层**注入过滤（如 Repository 统一 `where tenant_id=ctx.tenant_id`），**不做**前端隐藏式隔离。
- **跨租户访问是最高危事件**：检测到即告警 + 写审计（§37 Case 5）。

## 6.5 敏感数据保护

- **Secret Reference**：LLM 只见 `credential_ref=email-prod`，真实凭据由 Tool Runtime 在执行时注入（§4.8）。
- **PII / Secret 检测**：入口（用户输入）、出口（工具返回、检索内容、模型输出）都可插拔检测器。
- **Masking / Redaction**：检测命中后按策略替换/打码/阻断；模型输出兜底脱敏（防止模型复述泄露）。
- **KMS**：静态加密（文档原件、快照、审计日志中敏感字段）。

## 6.6 Prompt / Tool Injection 多层防御（Phase 1 摘要，详述后置）

| 层 | 防御 | 落地模块 |
|---|---|---|
| L1 输入检测 | 用户输入/文档/网页做注入特征检测 | Gateway / Ingest / Context |
| L2 Context 隔离 | UNTRUSTED 与指令强制分区 | Context Engine |
| L3 指令/数据分离 | 模型只信指令区 | Context Engine + Prompt |
| L4 Tool Permission | 工具调用先过权限 | Tool Runtime + Policy |
| L5 Tool 参数校验 | JSON Schema + 业务校验 | Tool Runtime |
| L6 Output Validation | 工具/模型输出脱敏 + 注入检测 | Tool Runtime + 生成层 |
| L7 敏感数据保护 | Secret reference / masking | SecretManager |
| L8 Sandbox | 高危执行隔离 | Sandbox |
| L9 Audit | 全量审计 + 异常告警 | Audit |
| L10 Runtime Policy | 预算/限流/频率/行为异常 | Runtime |

## 6.7 审计

- 强制审计事件：**权限决策、工具执行、数据访问（含拒绝）、审批动作、配置变更**。
- AuditLog 结构：`who/what/when/where/why/outcome`（§8 表结构）。
- 审计与 Trace 同源（复用 trace_id），保证"这条 trace 里为什么拒绝"可查。

## 6.8 测试策略

1. **默认拒绝测试**：无策略 → 所有访问拒绝。
2. **跨租户越权测试**：User A 访问 Tenant B 的任意资源，断言拒绝 + 审计记录。
3. **ABAC 条件测试**：owner-only 条件在不同 owner 下断言。
4. **Secret 泄漏测试**：全链路断言 LLM 输入输出不含真实凭据。
5. **注入样本集测试**：RAG/Memory/工具结果注入样本（§23 评测集分类复用）。

---

# 第七部分：Observability

## 7.1 三支柱

- **Logs**：结构化 JSON，带全局属性，业务事件与错误。
- **Metrics**：计数器/直方图/仪表盘（QPS、延迟、token、成本、错误率、检索命中、审批、限流）。
- **Traces**：全链路 span 树，Agent 语义打点，是排障的主干。

## 7.2 Agent Trace 结构

```
span: request                        (run_id)
 ├─ span: agent.run                  (run_id, step_id)
 │   ├─ span: context.build
 │   │   ├─ span: memory.recall
 │   │   ├─ span: retrieval.vector   / retrieval.bm25 / retrieval.graph
 │   │   └─ span: rerank
 │   ├─ span: llm.call               (model, prompt_hash, tokens, cost)
 │   ├─ span: tool.execute           (tool_ref, call_id) × N
 │   │   ├─ span: policy.check
 │   │   ├─ span: approval.gate      (若审批)
 │   │   └─ span: tool.run
 │   ├─ span: observation.validate   (注入检测/脱敏)
 │   └─ span: llm.call               (最终答案)
 └─ span: persist + events
```

## 7.3 全量属性（span 必带）

`trace_id, span_id, parent_span_id, tenant_id, user_id, session_id, agent_id, agent_version, run_id, step_id, model, prompt_version, tool_ref, call_id`

事件专属：`tool args(result)`, `retrieval chunks`, `used_knowledge`, `final_context_hash`, `llm_output`, `tokens`, `cost`, `error_code`。

## 7.4 "可回答清单"（每 Run 必答，对应 §1 硬性验收）

1. 用户是谁 / 租户是谁 / Agent 是谁 / 用了哪个版本 / 哪个 Model / 哪个 Prompt
2. 用了哪些 Skill、调用了哪个 Tool、参数是什么、返回什么
3. 检索了什么、命中哪些知识（chunk/provenance）
4. 最终上下文是什么（`final_context_hash` + 快照）
5. LLM 输出了什么、每一步耗时、花了多少钱
6. 哪一步失败、为什么（error_code + span）
7. 如何重放（`replay` 可直接消费 run 快照）

答不全 → 该 Run 视为不合格（CI/评审硬门禁）。

## 7.5 关键指标

| 类别 | 指标 |
|---|---|
| 流量 | runs/s、steps/run、tools/run |
| 延迟 | p50/p95/p99：llm、tool、retrieval、总耗时 |
| 成本 | token（in/out）、$ per run / per user / per tenant |
| 质量 | 检索命中率、空检索率、引用准确率、审批拒绝率 |
| 稳定性 | 错误率（按 error_code）、重试率、熔断开门率、超时率 |
| 安全 | 注入检测命中、越权拒绝、审计量 |

## 7.6 实现

- **OTel SDK**（Python）自动 + 手动打点；Logs 结构化 JSON → OpenSearch；Metrics → Prometheus；Traces → OTel Collector → 后端（Jaeger/Tempo/自建）。
- **Trace 采样策略**：**全量存 span 元数据**（ID、耗时、状态、属性）；`payload`（prompt/输出/参数）默认采样 10% 可配为 100%（成本可控、排障够用）。
- **Context 快照**：`final_context_hash` + 完整快照存 S3（Replay 的原材料）。

## 7.7 排障流程（从现象到根因）

```
用户报错/回答异常 → run_id
→ Trace 瀑布图：定位最慢/失败的 span
→ 看该 span 的 payload（prompt/参数/返回）
→ 看审计（权限/审批是否拦截）
→ 判定：检的错 / 用的错 / 工具的错 / 模型的错（对应 §37 Debug Case）
→ 用 Replay 复现 + 换参数对比 → 修复
```

## 7.8 测试策略

1. **Trace 完整性 CI**：每个集成测试断言 span 树 + 必带属性齐全。
2. **采样正确性**：属性全量、payload 按采样率——单元测试断言。
3. **指标正确性**：用已知输入断言 token/cost/延迟落盘正确。
4. **故障注入可观测**：注入 LLM/tool 故障，断言错误 span + error_code 齐全。

---

---

# 第八部分：数据模型

## 8.1 存储职责划分

| 存储 | 承载 | 理由 |
|---|---|---|
| PostgreSQL | 身份/Agent/会话/Run/Step/工具/文档/图事实/评测/审批/审计/配置 | 事务 + 关系，控制面与状态 |
| Redis | Cache、分布式锁（run 锁）、限流计数、Stream 队列 | 低延迟、原子操作 |
| pgvector（PG 扩展） | Chunk 向量索引 | MVP 少一个中间件（ADR-05） |
| OpenSearch/ES | 全文索引（BM25）、日志 | MVP 可后置（先用 PG tsvector + JSON 日志） |
| S3（MinIO） | 文档原件、Context 快照、Replay 制品 | 大文件、冷数据 |
| KMS/Secret | 密钥、凭据 | 静态加密 |

## 8.2 核心 ER（关系概要）

```
User ──< Member >── Tenant
User ──< UserRole >── Role ──< RolePermission >── Permission
Agent ──< AgentVersion
AgentVersion ──< Session ──< AgentRun ──< AgentStep ──< ToolCall
AgentRun ──< Approval
Agent ──< ToolBindings >── Tool ──< ToolVersion
Tenant ──< Document ──< DocumentVersion ──< Chunk ──< (向量, 全文)
Tenant ──< Entity ──< KnowledgeFact ──< Relation
Tenant ──< Memory
AgentRun ──< Span ──< Trace
Tenant ──< EvaluationDataset ──< EvaluationCase ──< EvaluationRun
Tenant ──< Configuration ──< FeatureFlag
```

## 8.3 核心表设计（PostgreSQL，Phase 1 关键表）

> 通用列约定：每表含 `id`（UUID PK）、`tenant_id`（NOT NULL）、`created_at/updated_at`（带 `ON UPDATE`）、`deleted_at`（软删，NULL=存活）、`version`（乐观锁/版本）。唯一约束一律 `(tenant_id, xxx)` 前缀，避免跨租户冲突。详细 DDL 随模块深挖补齐。

### 8.3.1 Identity

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
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, name TEXT NOT NULL,
  UNIQUE (tenant_id, name)
);
CREATE TABLE members (
  tenant_id UUID NOT NULL, user_id UUID NOT NULL, role_id UUID NOT NULL,
  PRIMARY KEY (tenant_id, user_id, role_id)
);
CREATE TABLE policies (          -- RBAC/ABAC 统一（见 §6.2）
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL,
  name TEXT NOT NULL, effect TEXT NOT NULL CHECK (effect IN ('ALLOW','DENY')),
  subject_json JSONB NOT NULL, action TEXT NOT NULL, resource TEXT NOT NULL,
  condition_json JSONB, priority INT NOT NULL DEFAULT 0, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  version INT NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(), deleted_at timestamptz
);
CREATE INDEX idx_policies_action ON policies (tenant_id, action);
```

### 8.3.2 Agent / Session / Run

```sql
CREATE TABLE agents (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, owner_id UUID NOT NULL,
  name TEXT NOT NULL, slug TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT',
  UNIQUE (tenant_id, slug), deleted_at timestamptz
);
CREATE TABLE agent_versions (   -- 快照：配置+提示词+工具绑定，运行不可变
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
  state TEXT NOT NULL,                                   -- 见 §3.2 AgentState
  budget_json JSONB NOT NULL, cost NUMERIC(12,4) NOT NULL DEFAULT 0,
  tokens_in INT NOT NULL DEFAULT 0, tokens_out INT NOT NULL DEFAULT 0,
  model_config JSONB, input_json JSONB NOT NULL, output_json JSONB,
  error_json JSONB, checkpoint_id TEXT,
  started_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_runs_tenant_state ON agent_runs (tenant_id, state, started_at);
CREATE INDEX idx_runs_session ON agent_runs (session_id, started_at);
CREATE INDEX idx_runs_user ON agent_runs (tenant_id, user_id, started_at);
CREATE TABLE agent_steps (
  id UUID PRIMARY KEY, run_id UUID NOT NULL REFERENCES agent_runs(run_id),
  seq INT NOT NULL, state TEXT NOT NULL,
  input_summary TEXT, llm_json JSONB, tool_calls_json JSONB, observations_json JSONB,
  decision TEXT, tokens_used INT NOT NULL DEFAULT 0, cost NUMERIC(12,4) NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, seq)
);
CREATE TABLE tool_calls (
  call_id TEXT PRIMARY KEY,          -- 幂等键
  run_id UUID NOT NULL, step_id UUID, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  tool_ref TEXT NOT NULL, tool_version INT, args_json JSONB NOT NULL,
  result_json JSONB, status TEXT NOT NULL, risk_level TEXT, approval_id UUID,
  error_code TEXT, latency_ms INT, cost NUMERIC(12,4),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_tool_calls_run ON tool_calls (run_id, created_at);
```

### 8.3.3 Knowledge（Phase 1 最小集）

```sql
CREATE TABLE documents (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, owner_id UUID NOT NULL,
  kb_id UUID NOT NULL, title TEXT NOT NULL, source_uri TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING',     -- PENDING/PARSING/READY/FAILED/DELETED
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
  permission TEXT,        -- 权限标签，检索时过滤
  vector vector(1024),    -- pgvector；维度随 embedding 模型
  meta_json JSONB,        -- owner/时间戳/语言等
  hash TEXT NOT NULL,
  UNIQUE (tenant_id, document_id, version, seq), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON chunks (tenant_id, document_id, version);
CREATE INDEX idx_chunks_text_gin ON chunks USING GIN (to_tsvector('simple', text)); -- 全文（MVP）
```

### 8.3.4 Memory / Eval / Ops

```sql
CREATE TABLE memories (
  id UUID PRIMARY KEY, tenant_id UUID NOT NULL, user_id UUID NOT NULL,
  agent_id UUID, scope TEXT NOT NULL,          -- USER/AGENT/TENANT
  memory_type TEXT NOT NULL,                   -- EPISODIC/SEMANTIC/PREFERENCE...
  content TEXT NOT NULL, source TEXT, confidence NUMERIC(3,2),
  ttl_at timestamptz,                          -- 过期时间（TTL）
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz
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
  outcome TEXT NOT NULL,                -- ALLOWED/DENIED/FAILED/...
  detail_json JSONB, ip TEXT, created_at timestamptz NOT NULL DEFAULT now()
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
  rules_json JSONB NOT NULL,                       -- 百分比/租户/用户规则
  version INT NOT NULL DEFAULT 1, enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE spans (                              -- Trace（Phase 1 简化，或用 OTel 后端）
  span_id TEXT PRIMARY KEY, trace_id TEXT NOT NULL, parent_span_id TEXT,
  tenant_id UUID NOT NULL, user_id UUID, run_id TEXT, step_id TEXT,
  name TEXT NOT NULL, kind TEXT, start_time timestamptz NOT NULL,
  duration_ms INT, attributes_json JSONB, status TEXT,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_spans_trace ON spans (trace_id);
CREATE INDEX idx_spans_run ON spans (run_id, start_time);
```

## 8.4 生命周期与 TTL

- **软删 + TTL**：会话/记忆/临时 Run 快照设 TTL（如 session 90d、memory 按 scope 30~365d）；过期的跑后台批量清理（delete 前先归档到 S3）。
- **版本不可变**：`agent_versions` / `document_versions` / `configurations` 只增不改；修改 = 新版本。这是灰度与回滚的数据基础。
- **数据保留策略**：审计 180d（合规可更长）、Trace 元数据 90d、payload 快照 30d、评测数据集长期。

## 8.5 索引要点

- 查询主路径均带 `tenant_id` 前缀索引，防止跨租户扫表。
- Run 列表/看板：`(tenant_id, state, started_at)`；历史查询：`(session_id, started_at)`。
- 检索过滤：`(tenant_id, kb_id, permission)` 复合索引。
- 全文：MVP 用 `to_tsvector('simple', text)` GIN（中文分词后置，换 OpenSearch/IK）。

---

# 第九部分：请求时序

## 9.1 一次对话请求（Agent Run）主时序

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

## 9.2 审批时序（高风险工具）

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

- 审批请求 `PENDING` → `APPROVED/REJECTED/TIMEOUT(24h)`；每次决策写审计。
- Run 在 `WAITING_APPROVAL` 可被用户取消；审批期间不消耗 LLM 预算。

## 9.3 崩溃恢复时序

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

## 9.4 检索时序（RAG，能力层示例）

```
Context Eng ─▶ RetrievalService
  ├─▶ (query rewrite) ─▶ embed ─▶ vector top-50
  ├─▶ BM25 top-50
  ├─▶ RRF fuse ─▶ policy filter ─▶ rerank top-5
  └─▶ RetrievalResult{chunks+provenance} ─▶ Context（UNTRUSTED 分区）
```

## 9.5 失败时序示例（Tool 超时 → 降级）

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

# 第十部分：MVP 实施计划

## 10.1 MVP 目标（P0 交付物）

> **一句话**：一个开发者能本地跑起来、能创建 Agent、发起一次对话、让它调 2~3 个工具、带检索、跑完能看到完整 Trace 和审计的单体平台。多租户从第一天起就在数据模型上成立（`tenant_id` 全模型），但 Phase 1 用单租户跑通。

**验收场景**：
1. 创建 Agent v1（含 system prompt + 绑定 3 个工具：`http.get`、`kb.search`、`calc.add`）。
2. 发起 Run：对话→调用 `kb.search` 检索一个文档→带引用回答。
3. Run 过程中：权限拒绝一次（低权限用户调 `http.get` 被拒）→ 审计里看得到。
4. 查看该 Run 的完整 Trace（每个 span 有 run_id/step_id/耗时/成本）。
5. 杀掉执行进程重启 → 正在执行的 Run 从检查点恢复。
6. 跑一遍评测集（10 条）→ 输出 Recall@k + Faithfulness 报告。

## 10.2 实施阶段拆解（MVP 内部）

### Phase 0 — 工程基础设施（1 周）
- 内容：repo 结构、`docker-compose`（PG/Redis/MinIO）、FastAPI 骨架、配置加载、结构化日志 + OTel 打点封装、CI、`Makefile`。
- **验收**：`make up && make test && make lint` 通过；CI 绿色。

### Phase 1 — 最小 Agent Runtime（2 周）
- 内容：`AgentState` 状态机（含 `transition()` 守卫）、`ExecutionBudget`、`agent_runs/agent_steps` 落库、Redis run 锁、`ModelGateway`（一个 provider）、最小 `ContextEngine`、崩溃恢复、runs API。
- **验收**：能对话；预算超限进 TIMEOUT；kill -9 后恢复；死循环桩在 N 步停止。

### Phase 2 — Function Calling + Tool Runtime（2 周）
- 内容：`ToolRegistry`、`ToolCallRequest/Result`、`PolicyEngine.is_allowed`（默认拒绝）、3 个工具（`calc.add`、`http.get`（SSRF 防护）、`kb.search`）、审计表、`POST /tools/{id}/execute`。
- **验收**：工具调用带完整 audit+trace；越权被拒；参数校验拒非法输入。

### Phase 3 — 检索 + 评测雏形（1~2 周）
- 内容：文档 ingest（markdown→分块→embedding→pgvector+`tsvector`）、混合检索 + RRF、`RetrievalResult` 进 Context（UNTRUSTED 分区）、10 条评测集 + `Recall@k/Faithfulness` 脚本、`GET /runs/{id}/trace`。
- **验收**：上传一篇文档→提问能带引用回答；评测脚本出报告。

**MVP 里程碑**：~6 周（3 人）。

## 10.3 MVP 范围裁剪（明确不做）

- 不做多租户界面，但**模型强制 `tenant_id`**。
- 不做 MCP / Knowledge Graph / Memory 服务（先留接口）。
- 不做审批流（`approvals` 表先建，逻辑后置）。
- 不做重排器（RRF 后直接 top-k；rerank 接口预留）。
- 不做沙箱（`code`/`shell` 工具禁用，只放白名单纯计算工具）。
- 不接专用向量库/ES（pgvector + tsvector 起步）。

## 10.4 项目结构（MVP 落地版）

```
agent-platform/
├── docker-compose.yml          # PG/Redis/MinIO
├── pyproject.toml
├── app/
│   ├── main.py                 # FastAPI 装配
│   ├── settings.py             # 版本化配置加载
│   ├── gateway/                # 认证/限流/路由中间件
│   ├── identity/               # 用户/租户/角色/策略 CRUD
│   ├── agent/
│   │   ├── runtime/            # 状态机/预算/编排/恢复
│   │   ├── model/              # ModelGateway（provider 抽象）
│   │   ├── context/            # ContextEngine
│   │   └── api/                # /agents /runs
│   ├── tool/
│   │   ├── registry/           # 注册/发现/版本
│   │   ├── executor/           # 执行管线 + 具体工具
│   │   ├── policy/             # 权限判定封装
│   │   └── api/                # /tools
│   ├── knowledge/
│   │   ├── ingest/             # parse→chunk→embed→index
│   │   ├── retrieval/          # hybrid + RRF（+rerank 接口）
│   │   └── api/                # /knowledge
│   ├── security/               # 注入检测/脱敏/审计封装
│   ├── observability/          # OTel/log/metrics 工具
│   ├── evaluation/             # 评测集/评测运行
│   ├── storage/                # PG/Redis/S3 访问层
│   └── common/                 # 错误码/事件/工具函数
├── tests/                      # 单测 + 集成 + 契约 + 架构
└── scripts/                    # eval / ingest / replay CLI
```

## 10.5 技术栈落地清单

FastAPI · Pydantic v2 · SQLAlchemy 2 + Alembic · asyncpg · Redis · pgvector · httpx · OpenTelemetry · pytest。

## 10.6 风险与缓解（MVP 阶段）

| 风险 | 缓解 |
|---|---|
| 状态机被业务绕过 | `transition()` 唯一入口 + CI 架构测试 |
| 崩溃恢复不可靠 | 故障注入测试（任意点 kill）+ 幂等键 |
| 死循环打爆成本 | 预算 + 指纹循环检测 + 单测 |
| 检索质量差 | 先建 10 条评测集，Recall@k 说话（ADR：不靠感觉） |
| 权限漏洞 | 默认拒绝 + 越权测试 + 审计全覆盖 |
| 爬坡工具失败 | 契约测试 + 熔断留接口 |

## 10.7 后续阶段（Phase 4+）

Phase 4 MCP+Skill → Phase 5 Memory → Phase 6 Knowledge Graph → Phase 7 IAM 深化 → Phase 8 Replay 平台 → Phase 9 Evaluation 平台 → Phase 10 灰度/AB/Rollback → Phase 11 Sandbox+Approval → Phase 12 Enterprise Hardening。

---

# 第十一部分：Function Calling（函数调用编排）

## 11.1 为什么 Function Calling ≠ 直接执行函数

LLM 输出的 `tool_calls` 是**意图（intent）**，不是**命令（command）**。中间隔着：解析、校验、权限、风险、编排、执行、观察。把"LLM 说调就调"变成"LLM 建议 → 平台裁决 → 平台执行"是安全与质量的关键边界：

```
LLM → Tool Call（结构化意图）
  → Agent Runtime（编排）
  → Tool Registry（解析 tool_ref + version）
  → Policy / Permission / Risk（裁决）
  → Validation（参数）
  → Executor（执行 + 超时/重试/幂等/沙箱）
  → 真实 Tool
```

## 11.2 数据契约

```python
class ToolCall(BaseModel):  # LLM 输出的原始意图
    id: str
    name: str  # 工具名，需解析为 tool_ref
    arguments: str | dict  # LLM 常给 JSON 字符串，需解析


class ToolExecution(BaseModel):  # 一次执行的完整记录（审计/重放主键）
    execution_id: str
    call_id: str  # 幂等键（§4.7）
    tool_ref: str
    tool_version: str
    state: ExecutionState  # PENDING/APPROVING/VALIDATING/EXECUTING/SUCCEEDED/FAILED/CANCELLED
    request: ToolCallRequest
    result: ToolCallResult | None
    retries: int
    started_at: datetime
    finished_at: datetime | None
    error_path: list[ErrorCode]  # 完整错误链（含被修正过的参数错误）
```

`ToolDefinition.input_schema`（JSON Schema，既是参数校验也是暴露给 LLM 的工具描述）：

```json
{
  "type": "object",
  "properties": {
    "recipient": {"type": "string", "format": "email"},
    "cc":        {"type": "array", "items": {"type": "string", "format": "email"}, "maxItems": 20},
    "subject":   {"type": "string", "maxLength": 200},
    "body":      {"type": "string", "maxLength": 20000}
  },
  "required": ["recipient", "subject", "body"]
}
```

## 11.3 完整管线

```
LLM 输出 messages[].tool_calls
  → parse arguments（JSON 字符串 → dict；解析失败 → 回喂 LLM 修正）
  → resolve name → tool_ref + version（找不到 → TOOL_NOT_FOUND，回喂 LLM 换工具）
  → validate 参数（JSON Schema + 业务校验；失败 → 回喂或拒绝，见 11.4）
  → policy / risk / approval（§4.4 第 3-5 步）
  → orchestrate（并行 / 串行 / 预算 / 依赖顺序）
  → execute（超时 / 重试 / 幂等 / 沙箱 / secret 注入）
  → validate output（脱敏 + 注入检测）
  → 回填 Context（UNTRUSTED 分区，§5）→ 下一轮 LLM
```

## 11.4 参数错误处理矩阵（编排层核心决策）

| 错误 | 错误码 | 动作 |
|---|---|---|
| 参数缺失 | `TOOL_INVALID_ARGUMENT_MISSING` | **回喂 LLM** 补全重发（每步上限 2 次） |
| 类型错误 | `TOOL_INVALID_ARGUMENT_TYPE` | **回喂 LLM** 修正 |
| 参数越界 | `TOOL_INVALID_ARGUMENT_RANGE` | 回喂或按工具策略截断（幂等工具可截断） |
| 非法参数 | `TOOL_INVALID_ARGUMENT` | **拒绝 + 审计**（可疑注入，不喂回） |
| 工具不存在 | `TOOL_NOT_FOUND` | 回喂 LLM 换工具 |
| 权限不足 | `TOOL_PERMISSION_DENIED` | **拒绝 + 审计，不回喂**（防 LLM 反复试探） |

> **关键决策**：参数类错误**回喂给 LLM 自我修正**（主流、体验好），但有上限（默认每步 2 次，超限即 FAILED）。权限 / 注入 / 风险类错误**不回喂**——修正窗口是给"诚实错误"的，不是给"试探性调用"的。

## 11.5 回滚与补偿

多数工具调用**不可逆**（邮件已发出）。回滚 = 三层：
1. **幂等键**：同一 `call_id` 不重复产生副作用（§4.7）。
2. **补偿动作（Compensation）**：`ToolDefinition.compensatable=true` 时，编排层可在后续提供"撤销/作废"对应工具（如 `crm.ticket.reopen` 补偿 `crm.ticket.close`）。
3. **审计可追溯**：副作用操作的执行记录 + 补偿记录成对，可完整重放"发生过什么"。

## 11.6 并行 / 串行编排

- 同一轮多个 `tool_calls` 默认**并行**（有界并发，默认 4）。
- `ToolDefinition.depends_on` 声明的工具**串行**执行（下游等上游结果）。
- 相互冲突的调用（写 + 删同一资源）按序执行，并记录执行顺序与依赖图，供 Replay 复现。

## 11.7 测试策略

1. LLM 桩输出各类错误 arguments → 断言按 11.4 矩阵处理（回喂/拒绝分界正确）。
2. 修正重试上限测试（2 次后 FAILED）。
3. 权限错误不回喂测试。
4. 幂等重放测试（同 call_id 不重复副作用）。
5. 并行/串行/依赖顺序测试 + 冲突调用顺序测试。

---

# 第十二部分：MCP（Model Context Protocol）

## 12.1 MCP ≠ Function Calling

- **Function Calling**：LLM 结构化出参 → 平台校验编排执行（**编排层**，调用方视角）。
- **MCP**：工具 / 资源 / 提示词的**发现与传输协议**（Server 如何暴露能力、Client 如何发现与调用）。

两者正交。MCP 解决"能力如何被描述与传输"，Function Calling 解决"意图如何被校验与编排"。在平台里，MCP Server 的能力经 `McpProvider` 包装成普通 `ToolDefinition`，**成为 Function Calling 编排的一员**。

## 12.2 架构

```
LLM → Agent Runtime → ToolProvider（统一抽象）
                          ├─ FunctionProvider（本地函数）
                          ├─ HttpProvider（HTTP API）
                          └─ McpProvider（MCP Client）→ MCP Server(s)
                                                              │
                                    stdio（子进程）/ SSE / HTTP(Streamable)
```

上层 Agent **不感知**底层是 MCP 还是 HTTP（§4.9 的兑现）。

## 12.3 MCP Client 连接管理

- **Transport**：stdio（本地子进程，每 server 一个进程）/ SSE / HTTP Streamable。
- **生命周期**：`connect → initialize(握手/能力协商) → tools/list(发现) → tools/call(调用) → close`。
- **健康**：McpProvider 对每个 server 维护连接 + 周期探活；失败标 `degraded`，`resolve()` 拒绝新调用（§4.5）。
- **重连**：连接断开指数退避重连；进行中的调用超时终止，重试按幂等策略。

## 12.4 能力映射

| MCP 能力 | 平台映射 | 说明 |
|---|---|---|
| `tools` | `ToolDefinition` | 白名单过滤后注册为平台工具 |
| `resources` | 知识/文件读取能力 | 受权限与检索管线控制 |
| `prompts` | Skill / Prompt 模板 | 受版本与权限控制 |

## 12.5 安全（第三方 MCP Server 默认不可信）

| 防线 | 手段 |
|---|---|
| 白名单 | `tools/list` 全量 → 过滤 → **只注册显式允许的子集** |
| 参数校验 | 复用平台 JSON Schema（§11.4） |
| 输出 | 脱敏 + 注入检测（UNTRUSTED，§5） |
| 网络隔离 | server 网络策略（禁止 SSRF/内网横向） |
| Secret | server 凭据经 SecretManager 注入，不落地 |
| 接入治理 | 高风险 server 需**审批**后方可接入；server 元数据（来源/签名/版本）留痕 |

## 12.6 与 Function Calling 的汇合

- 工具名冲突：MCP 工具用**命名空间前缀**避免冲突：`tool_ref = "mcp:{server_id}:{tool_name}"`。
- `McpProvider` 完成 `ToolDefinition` 转换后，Agent 层按普通工具编排，**不需要感知 MCP 协议**。

## 12.7 测试策略

1. mock MCP server（stdio + SSE 各一）做契约测试。
2. 白名单过滤测试（tools/list 返回多，只注册允许的子集）。
3. server 崩溃重连测试。
4. 恶意返回（注入/超大/敏感）检测与脱敏测试。

---

# 第十三部分：Skill（技能包）

## 13.1 什么是 Skill

Skill = 一组**行为知识**：指令（怎么做）+ 可选工具绑定（用哪些工具）+ 可选资源 + 元数据（触发条件、适用场景、作者/版本）。它是 Agent 的"技能包"，**按需加载，不常驻 Context**。

## 13.2 Skill Manifest

```yaml
name: customer-support-handbook
version: 3
description: 客服话术与售后流程
trigger: 用户咨询 售后/退款/物流
instructions: |
  （正文：步骤、边界、禁忌、话术要点）
tools:                     # 声明所需工具（执行时仍需过 Policy）
  - platform.search.web
  - platform.crm.ticket.create
resources:                 # 可选绑定知识
  - kb:customer-policies@v2
permission:                # skill 自身要求的最小权限
  - action: crm.ticket:create
author: ops-team
updated_at: 2026-08-19
```

## 13.3 生命周期与版本

```
DRAFT → REVIEW → ACTIVE → DEPRECATED → DISABLED
```

每版本不可变（灰度/回滚基础，§57）。Agent 绑定的是 `skill_ref@version`。

## 13.4 加载策略（关键：不要全量塞 Context）

**两级加载**，避免把全部 skill 正文塞进每轮上下文：

```
catalog（名称 + 描述 + 触发条件，轻量）
  → 命中（路由判定需要该 skill）
  → 加载 instructions 全文 → 注入 Context
```

Skill 是"该怎么做"的知识通道——按目录定位、按需取正文。

## 13.5 权限与信任

- **信任分级**：平台/租户自建并经 REVIEW 的 skill = 可信；**第三方/用户上传的 skill 必须先审查**（可能含注入）。
- Skill 声明工具权限，但**不能绕过 Policy**：执行 skill 内工具仍走 §4.4 全管线，且 skill 声明权限 ≤ 调用者权限，否则拒绝。
- skill 指令进入 Context 的 SYSTEM 分区（指令域），但引用资源（kb/网页）仍按 UNTRUSTED 处理（§5.2）。

## 13.6 Skill 与 MCP / 工具的关系

Skill 可以捆绑任意工具（含 MCP 工具）；Skill 声明工具，执行仍走 Tool Runtime 全管线（审批/沙箱/审计不豁免）。

## 13.7 测试策略

1. 触发命中测试（catalog 路由正确）。
2. 加载预算测试（skill 正文不超 Context 预算，§5.5）。
3. 权限降级测试（skill 声明权限 > 调用者权限 → 拒绝）。
4. 恶意 skill 审查测试（含注入样本 → 拦截）。
5. 版本切换测试（同 skill 换版本，Trace 可答"用了哪个版本"）。

---

---

# 第十四部分：Memory（记忆）

## 14.1 为什么存在

Memory 让 Agent **跨会话 / 跨任务**记住上下文与用户偏好，是 RAG（外部文档知识）之外的"个体经验"。但记忆同时是**最容易泄漏、最容易投毒**的数据：User A 的记忆被 User B 读到、攻击者通过"帮我记住 xxx"把恶意指令写进记忆再在后续会话被当作指令执行。因此 Memory 设计的核心是**隔离 + 信任分级 + 完整生命周期**，不是"存得越多越好"。

## 14.2 记忆分类与作用域

| 类型 | 作用域 | 生命周期 | 用途 | 是否进上下文 |
|---|---|---|---|---|
| Working Memory | Run | Run 内 | 当前任务的中间状态/步骤/观察 | 仅当轮 |
| Short-term / Conversation | Session | 会话（默认 90d） | 会话上下文 | 近轮原文 + 旧轮摘要 |
| Episodic | User | 短~中（默认 30d） | 过去发生的事件/交互 | 按需召回 |
| Semantic | User/Agent/Tenant | 长（默认 180d~1y） | 事实性知识（"用户是 DBA"） | 按需召回 |
| Preference | User | 长 | 用户偏好（"回答要简洁"） | 每轮注入（低预算） |

## 14.3 数据契约

```python
class MemoryEntry(BaseModel):
    memory_id: str
    tenant_id: str
    user_id: str
    agent_id: str | None  # None = 该用户跨 Agent 通用
    scope: MemoryScope  # SESSION / USER / AGENT / TENANT
    memory_type: MemoryType  # WORKING / SHORT_TERM / EPISODIC / SEMANTIC / PREFERENCE
    content: str
    source: str  # provenance：来自哪个 session / 工具 / 网页
    source_trust: TrustLevel  # 可信（用户明确表达）vs 不可信（网页自动提炼）
    confidence: Decimal
    embedding: list[float] | None  # 支持语义召回
    ttl_at: datetime | None
    created_at: datetime
    updated_at: datetime
```

## 14.4 能力层接口（都带主体与作用域）

```
MemoryService.write(subject, entry)     # 写：scope + TTL + 冲突处理
MemoryService.read(subject, scope, id)  # 精确读：id 校验归属
MemoryService.recall(subject, query, k) # 语义召回：scope 过滤 → embedding 相似
MemoryService.delete(subject, id | scope)
```

- **写**：注入检测 + 敏感数据检测（见 14.6）；冲突时按"时间 + 置信度 + 来源可信度"决策。
- **读/召回**：**先钉死 scope，再做相似度**（§53.3）。User A 的召回 SQL 从第一步就是 `WHERE tenant_id=A.tenant AND user_id=A.user`，User B 的记忆**即使 embedding 最相似也不返回**。
- **删**：软删 + 审计；按 scope 批量清理（用户注销/租户退租）。

## 14.5 隔离（服务端强制，硬要求）

- Repository 层统一注入 `tenant_id + user_id + scope` 过滤，**不是**排序后过滤。
- SESSION scope 只在同 session 可见；USER scope 只对本人；AGENT scope 限制 agent_id；TENANT scope 限制租户内。
- 跨租户/跨用户读 = 最高危事件，命中即告警 + 审计（§6.4）。

## 14.6 信任与注入防护（Memory Poisoning）

| 风险 | 对策 |
|---|---|
| 记忆投毒（恶意内容被写入再被当指令） | ① 写入入口做注入检测 + 敏感检测；② **recall 结果进 Context 的 UNTRUSTED 分区**（§5.2），模型只当数据不当指令 |
| 不可信源自动提炼 | `source_trust=UNTRUSTED`（网页/工具自动提炼）与 `TRUSTED`（用户明确表达）分开，可信度与 TTL 不同 |
| 越权写入 | 写操作过 Policy（`memory:write`）+ 服务端隔离 |
| 记忆过期/冲突 | TTL + 冲突合并规则（14.7） |

## 14.7 冲突与过期

- **冲突**：同一实体多来源冲突 → 排序 `confidence × source_trust × recency`，高分胜出，旧记录归档（保留 provenance 供审计）。
- **过期**：TTL 到期批量清理（先归档 S3）；episodic 短、semantic 长。
- **更新**：写新版本，旧版本归档——保证"记忆怎么变的"可追溯。

## 14.8 测试策略

1. 跨用户读隔离测试（User A 无法召回 User B 记忆，即使 embedding 相似）。
2. 注入写入拦截测试（"忽略指令"样本写入被拦截或标记）。
3. TTL 清理测试。
4. 冲突合并测试（多来源冲突，高分/新者胜出，provenance 完整）。
5. 越权写测试。

---

# 第十五部分：RAG（Knowledge Platform 的检索能力）

## 15.1 RAG 的定位

RAG 是 **Knowledge Platform 的一种检索能力，不是系统核心**（§ADR-03）。平台把 RAG 实现为：**文档 → 索引（离线）→ 混合检索 → 融合 → 重排 → 进 Context** 的可插拔管线。它与其他检索通道（Graph、结构化 DB、全文）在混合检索处汇合。

## 15.2 完整管线

```
索引期（离线，可批处理）：
Document → Parser → Cleaner → Structure Extraction → Chunking
        → Embedding → Vector Index（pgvector）+ Lexical Index（tsvector/ES）

查询期（在线）：
Query → Query Understanding（改写/指代消解）
     → 混合检索：Vector top-50 + BM25 top-50
     → RRF Fusion → 权限过滤 → Rerank（20~50 → 5~10）
     → RetrievalResult → Context（UNTRUSTED 分区，带引用编号）
```

## 15.3 数据契约

Chunk 元数据（呼应 §8 `chunks` 表，生产分水岭）：

```
chunk_id, document_id, tenant_id, owner_id, permission, version,
source（文件+标题+章节）, section, position,
created_at, updated_at, hash
```

```python
class RetrievalRequest(BaseModel):
    query: str
    tenant_id: str
    user_id: str
    kb_filter: list[str]  # 权限/范围过滤（先过滤后召回，§54.1）
    top_k: int = 50
    rerank_n: int = 5
    knowledge_version: str | None  # 缓存键与一致性用（§49.5）


class RetrievalResult(BaseModel):
    chunks: list[ChunkHit]  # chunk + 融合分数 + 命中的检索器
    provenance: list[str]  # 每块可回源（source/section/position）
    trace: dict  # 各检索器 top-k 与分数（Retrieval Trace）
```

## 15.4 索引期关键点

- **分块是质量上限**：结构感知 + 父子分块（检索小块、喂父块）是实用首选；块大小按语料 Benchmark。
- **增量更新**：按 `document_id + version` 整体替换，embedding 用文本 hash 缓存跳过未变块；删除按来源 id。
- **权限**：块带 `permission` 标签，检索过滤在**索引查询层**完成。

## 15.5 查询期关键点

- **混合检索**：向量 + BM25（词面命中强于语义的场景：代码符号/专有名词/条款号）→ RRF 融合（`score=Σ 1/(k+rank)`，k=60）。
- **Rerank 漏斗**：`top-50 → RRF 50 → rerank 20~50 → top 5~10`。
- **进 Context 必须带来源编号**，模型据此 cite `[n]`，答案可核查（§5.4）。

## 15.6 权限与隔离

- 检索级过滤（先过滤后召回），**不做"召回后踢掉无权内容"**——否则越权内容已在计算中出现。
- 与 Memory 同规则：查询先钉死 tenant/kb/权限 scope。

## 15.7 Citation 与 provenance（可审计）

每块带 `source + section + position + version`。答案引用必须映射回块，支持"这条回答依据哪份文档哪一节"的核查。引用准确率是生成评测的核心指标之一（§21）。

## 15.8 Retrieval Trace 与评测

- 每次检索落 `retrieval` span：各检索器 top-k、融合分数、重排前后列表。
- **Recall 评测独立于生成**：gold_chunks 标注 + Recall@k / MRR / NDCG——"检得对不对"和"用得对不对"分开测。

## 15.9 测试策略

1. 召回率评测（gold_chunks → Recall@k 阈值门禁）。
2. 权限过滤测试（无权限内容不进入候选集，更不进上下文）。
3. 注入文档测试（文档内含"忽略指令"→ 进 Context 为 UNTRUSTED 且注入检测命中）。
4. 增量/版本测试（更新文档后旧块消失、检索用新版本）。
5. Citation 可回源测试（cite 的块 id 能定位到原始文档）。

---

# 第十六部分：Knowledge Graph

## 16.1 Knowledge Graph 不是 Entity + Relation

知识图谱如果不能回答"**这条事实哪来的、谁抽的、多大把握、什么时候有效**"，就不能审计，也就不能上生产。Graph 的核心是 **Source Provenance（来源可溯）+ 时间有效性 + 置信度**，而非"画了个图"。

## 16.2 Pipeline

```
Document → Parser → Chunk
  → Entity Extraction → Entity Normalization（别名→规范名）
  → Entity Resolution（消歧/合并同指）→ Relation Extraction
  → Entity Linking（链接到规范实体）→ Graph Validation
  → Graph Storage（facts 表）→ Graph Retrieval（子图/多跳/社区）
  → Context Construction（与向量 RAG 融合）
```

## 16.3 数据契约（一切以事实为单元）

```python
class KnowledgeFact(BaseModel):  # 最小可审计单元
    fact_id: str
    tenant_id: str
    subject_entity: str  # 规范化实体名
    predicate: str  # 关系类型（CEO/位于/属于...）
    object: str
    confidence: Decimal  # 抽取置信度
    source_doc: str  # document_id
    source_chunk: str  # chunk_id
    source_version: str  # 文档版本
    extracted_by: str  # 抽取模型/管线版本
    valid_from: datetime  # 时间有效性（CEO 会换届）
    valid_to: datetime | None
    status: ACTIVE / SUPERSEDED / CONFLICTING
```

## 16.4 实体归一化与消歧

- **别名 → 规范名**：`Tesla / Tesla Inc. / 特斯拉` → canonical entity。
- **Entity Resolution**：同指合并（"马斯克" 与 "Elon Musk"）；合并时保留别名集合与 provenance。
- 无法确定时**标记为待仲裁**，不静默合并（避免错误合并比不合并更糟）。

## 16.5 冲突处理

同 subject+predicate 多条来源冲突：

```
排序键 = confidence × source_trust × recency × 来源文档数
胜出 → ACTIVE；其余 → SUPERSEDED（保留，供审计/回滚）
无法自动判定 → CONFLICTING，进人工仲裁队列
```

## 16.6 版本、时间与回滚

- 每批抽取 = 一次版本；`source_version` 入事实。
- `valid_from/valid_to`：时间敏感事实（任职、价格）查询时按当前时间过滤。
- 回滚：按版本/来源整体撤销（`status=SUPERSEDED`），**不物理删**，保证审计链完整。

## 16.7 权限与租户隔离

- facts/entities 全带 `tenant_id`，图查询先钉 scope。
- 块级权限沿 provenance 传导：来源块无权限 → 该事实对查询者不可见（**过滤在查询层**）。

## 16.8 图检索与混合

- 查询：实体直达 → 子图/多跳遍历 → 社区摘要（全局问题）。
- **与向量 RAG 融合**：Router 决定走向量 / 图 / 双路——图擅长"跨实体的全局性问题"，向量擅长"相似段落"。融合后统一进 Context（UNTRUSTED 分区）。

## 16.9 增量与删除

- 增量：按来源文档版本重抽取受影响子图。
- 删除：按来源整体标记失效（`valid_to=now` / `status=SUPERSEDED`）。
- 冲突回滚复用同一机制。

## 16.10 测试策略

1. Provenance 测试：每条事实可回溯 `doc/chunk/version/extracted_by/confidence`。
2. 消歧测试：别名合并正确、不确定不静默合并。
3. 冲突仲裁测试：排序键正确、CONFLICTING 进人工队列。
4. 时间有效性测试：过期事实查询不返回。
5. 越权测试：无权限来源的事实不可见。
6. 混合检索测试：Router 双路结果融合正确。

---

---

# 第四十九部分：数据缓存治理（Cache Governance）

## 49.1 为什么存在

缓存能显著降低延迟与成本，但在 Agent 平台里**一个没想清楚的缓存就是一条数据泄露通道**：User A 的回答被缓存命中给 User B、知识版本更新后旧检索结果还在、权限变更后越权内容仍被命中。因此缓存不是"能缓存就缓存"，而是先回答五个问题：

> 什么能缓存？给谁缓存？缓存多久？如何失效？命中后是否造成越权？

## 49.2 缓存分类（12 类）

| # | Cache | Scope | 默认 TTL | 失效机制 | 安全要求 |
|---|---|---|---|---|---|
| 1 | Public Cache | 全局/租户 | 长（可达 30d） | 定时/事件 | 内容必须公开、非敏感 |
| 2 | Tenant Cache | tenant | 中 | 事件/版本 | 严格 tenant 隔离 |
| 3 | User Cache | user | 短~中 | 事件/会话结束 | 严格 user 隔离 |
| 4 | Session Cache | session | 会话级 | 会话结束 | 仅会话内可见 |
| 5 | Agent Cache | agent+version | 中 | Agent 版本变更 | 绑定 agent_version |
| 6 | Query Cache | tenant+user | 短 | 数据版本/权限变更 | query_hash + scope |
| 7 | Retrieval Cache | tenant+kb | 短（如 5min） | kb_version 升级 | 权限 scope 入 key |
| 8 | Embedding Cache | 全局 | 长 | embed 模型版本变更 | 内容本身安全 |
| 9 | LLM Response Cache | tenant+user+session | 会话级 | 会话结束/prompt 变更 | 仅会话内，脱敏 |
| 10 | Tool Result Cache | tenant+agent | 短（幂等窗口） | 工具版本/参数 | 脱敏后缓存 |
| 11 | Configuration Cache | tenant | 长 | 配置版本变更 | 无敏感 |
| 12 | Permission Cache | tenant+user | 极短（如 30s） | 角色/策略变更 | 决策结果，非数据 |

**原则：Scope 越大，TTL 越短、内容越不敏感。** 拿"敏感度 × 受众广度"两个维度判断，两个维度都低才允许长 TTL。

## 49.3 可以缓存 vs 必须谨慎

**可以缓存（幂等、版本可定、不涉密）**：embedding（`text_hash + embed_model_version`）、检索结果（短 TTL）、静态配置与 Prompt/Tool/Skill 元数据、模型能力/价格/Provider 健康（短 TTL）、公开知识。

**禁止直接缓存**：

- 用户私有数据、Access Token、Credential、Secret
- 权限相关数据（缓存的是"决策结果"，且决策本身必须短 TTL 并可被策略变更推翻）
- 实时业务状态、强一致性数据、高敏感数据
- 会话中的临时状态（可缓存但要绑定 session 且不可跨会话复用）
- 未经隔离/脱敏的 Tool Result

> **硬红线：禁止把 User A 的 Agent Response 直接缓存命中给 User B。** 任何响应缓存若与权限相关，权限 scope 必须入 key；无权限维度的响应不做跨用户缓存。

## 49.4 Cache Key 必须包含隔离维度

```
❌ cache[user_query]

✅ cache_key = f"{cache_type}:{tenant_id}:{scope}:{version_set}:{content_hash}"

   其中：
   - cache_type:  embedding / retrieval / llm_response / tool_result / ...
   - scope:       显式隔离维度（user_id / session_id / agent_id / kb_id）
   - version_set: 内容依赖的版本哈希（kb_version + embed_version + prompt_version + model_version）
   - content_hash: 输入内容哈希（query_hash / text_hash / args_hash / prompt_hash）
```

依赖权限的缓存，**必须把 permission scope 纳入 key**；否则"缓存结果 + 权限校验"两步分离时，一旦权限窄化，命中即越权。

## 49.5 失效（Invalidation）——推荐 Versioned Cache

要回答"数据更新后缓存何时失效"。**优先用版本化失效，而不是全局删除**：

```
Knowledge v1 → 用户更新文档 → Knowledge v2

key = tenant:123:kb:1024:query_hash     # v1 时期
key = tenant:123:kb:1025:query_hash     # v2 版本号自然产生新 key
```

| 缓存 | 失效触发 | 手段 |
|---|---|---|
| Embedding | embed 模型/维度变更 | 版本号入 key |
| Retrieval | kb_version / 文档更新 / 权限变更 | 版本入 key；权限变更时按 scope 清理 |
| LLM Response | prompt_version / model_version / 会话结束 | 版本入 key |
| Tool Result | tool_version / 参数变化 | 幂等窗口自然过期 |
| Config / Metadata | 配置版本变更 | 版本入 key |
| Permission | 角色/策略变更 | 主动失效 + 极短 TTL 兜底 |

**原则：能靠"版本号翻新 key"解决的，就不要写复杂的全局逐条删除逻辑。** 全局删除容易漏、慢、并发撕裂。

## 49.6 缓存一致性模式（何时用哪种）

| 模式 | 适用 | 注意 |
|---|---|---|
| Cache Aside | 读多写少、可容忍短窗口不一致 | 默认选择；写后主动失效 |
| Read Through | 统一缓存入口 | 封装在 Repository |
| Write Through | 强一致写路径（如配置） | 写放大 |
| Write Behind | 写密集异步落库 | 可能丢更新，慎用于权限/计费 |
| TTL | 弱一致兜底 | 必须有 |
| Versioned Cache | 版本驱动的内容（kb/prompt/model） | **优先推荐** |
| Pub/Sub Invalidation | 跨实例/跨租户主动失效 | 配合 Redis Pub/Sub / Stream |

> **红线：任何情况下不得为了缓存命中率牺牲权限正确性、数据正确性、安全性。**

## 49.7 Cache Stampede 防护

大量请求同时 Miss → 同时打 LLM/检索 → 成本瞬间暴涨。必须做 **Request Coalescing（Singleflight）**：

```python
async def with_singleflight(key, loader):
    # 1) 同一 key 并发请求共享一个 in-flight future（单飞）
    fut = inflight.get(key)
    if fut is not None:
        return await fut
    fut = asyncio.create_task(loader())
    inflight[key] = fut
    try:
        return await fut
    finally:
        inflight.pop(key, None)  # 2) 只有发起者真正加载


# 辅以：
# - TTL Jitter：expire_at = ttl * (0.7 + random*0.6)，防止缓存同时过期
# - 预热（Warmup）：热点 key 后台预加载
# - 分布式单飞：跨进程用 Redis 锁（SET NX + 带 TTL 锁），防多 Worker 同时 Miss
```

---

# 第五十部分：Agent Token 成本治理

## 50.1 成本必须可归因

"今天 LLM 花了 $500"没有价值；有价值的是"哪个 Agent、哪个 Run、哪一步为什么花了钱"。归因层级：

```
Tenant → User → Agent → Run → Step → LLM Call
           每个层级都能看到：estimated_cost / actual_cost / token 明细
```

```python
class CostBreakdown(BaseModel):  # 每个 LLM Call 落一条，随 Run 聚合
    input_tokens: int
    output_tokens: int
    cached_input_tokens: int  # prompt 缓存命中的输入
    reasoning_tokens: int  # 推理/思考 token
    tool_tokens: int  # 工具 schema + 工具结果折算
    rag_context_tokens: int  # 检索注入的 token
    prompt_tokens: int
    history_tokens: int
    estimated_cost: Decimal  # 用量 × 单价（下单前估算，用于预算预检）
    actual_cost: Decimal  # 账单口径（计费后校正）
```

> 预估成本在**预算预检**时用（§3.7：`max_cost` 超限即停）；实际成本在账单/对账时校正，二者分开字段，避免把"估算误差"当"成本异常"。

## 50.2 Token 持续增长排查

监控这些均值/分位，**按租户/用户/Agent 维度**：

| 指标 | 上涨通常意味着 |
|---|---|
| 平均 Context Token | 上下文膨胀，需压缩 |
| 平均 History Token | 历史未裁剪/未摘要 |
| 平均 Tool Result Token | 工具返回过大未压缩 |
| 平均 RAG Token | Top-K 过大 / 检索块过大 |
| 平均 Output Token | 输出上限/提示词引导过长 |
| 平均 Agent Steps | 循环没收敛 |
| 平均 LLM Calls / Run | 决策反复、无效重试 |
| 平均 Retry 次数 | 稳定性问题（429/超时） |

**报警策略**：`Token/Run` 相对基线持续上升（如连续 7 天日环比 > 5%）自动告警，而不是只看瞬时值。每个告警都带租户/Agent 归因，能直接下钻到 Run。

## 50.3 Token 优化优先级（从高到低）

1. Context Compression（§5 预算 + 整块取舍）
2. History Compression（旧轮转摘要，见 50.4）
3. Tool Result Compression（只留必要字段）
4. RAG Top-K（Recall 与成本平衡）
5. Prompt Compression（去冗余指令）
6. Duplicate Context Removal（检索/工具去重，§5 dedupe）
7. Tool Output Schema（返回 schema 只给必要字段）
8. Max Output Tokens（收紧）
9. Agent Step Limit（§3.7 收紧 max_steps）
10. Model Routing（§51/§52 该用小模型用小模型）

> **明确禁止：把完整历史每次原样全量发给 LLM。** 这既是成本黑洞也是 lost-in-middle 温床。

## 50.4 Context 生命周期分层

| 层 | 保留策略 | 载体 |
|---|---|---|
| System / Task Context | 每轮都在，压缩后固定 | 组装时生成 |
| Recent Conversation | **保留原文**（近 N 轮，默认 5） | Session |
| Old Conversation | **摘要**（每 M 轮折一条摘要，默认 M=10） | Session summary |
| Long-term Memory | 记忆库，按需检索 | Memory 服务（§14） |
| Retrieved Context | **按需检索**，不常驻 | RAG（§15） |
| Tool Observation | **只留必要结果**，可舍弃 | 当轮 observation |

---

# 第五十一部分：大模型 / 小模型成本平衡

## 51.1 任务分级（Model Tiering）

| 级 | 任务 | 模型档 | 理由 |
|---|---|---|---|
| L0 | 规则任务（关键词、模板） | **不调 LLM** | 纯代码，零成本零延迟 |
| L1 | 简单分类/抽取 | Small | 精度足够 |
| L2 | 简单问答 | Small | 不需要强推理 |
| L3 | 复杂 RAG | Medium | 检索 + 引用 |
| L4 | 复杂 Agent Planning | Large | 多步规划 |
| L5 | 高风险决策 | **Strong + Guardrail + Human Review** | 成本不是第一考量 |

## 51.2 Model Router

```
输入: TaskComplexity · ContextSize · ToolCount · RiskLevel
     · LatencyRequirement · TenantTier · Budget · ModelAvailability
     · Cost · QualityScore
输出: Model 选择 + 决策理由（写入 Trace，供 §59 回答"为什么选这个模型"）

                Model Router
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
     Small         Medium        Large
      $             $$             $$$
      │              │              │
   FAQ/分类       RAG/分析       Complex Agent
```

**决策必须落 Trace**：`routing.decision = {task_tier, model, reason, cost_estimate}`。否则线上无法回答"为什么用了贵模型"。

## 51.3 Dynamic Routing（不写死）

禁止"这个 Agent 永远用 GPT-X"。路由输入包含实时信号：

- **Latency**：当前模型 P95 恶化 → 换同档更快模型
- **Error Rate / 429 Rate**：命中率恶化 → 降流量（§52.3）
- **Quality**：在线质量分下滑 → 临时升级/告警
- **Cost / Quota / Budget**：配额将尽或超预算 → 降档或拒答
- **Provider Health**：Degraded/Unavailable → 切池内其他 Provider

## 51.4 Model Escalation（小模型先处理，必要时升级）

```
Small Model 处理
  │
  ├─ Confidence >= θ_small ──▶ 直接返回
  └─ Confidence <  θ_small ──▶ Medium Model
                                    │
                                    ├─ Confidence >= θ_medium ──▶ 返回
                                    └─ Confidence <  θ_medium ──▶ Large Model（或拒答/转人工）
```

- 置信度来自模型自报（logprob/显式输出）或旁路分类器。
- **Escalation 也写 Trace**：`escalation.chain = [small→medium→large]`，成本可归因、可复盘。
- 预算/延迟受限时，最下层可用"拒答 + 给用户可选项"替代硬升级。

---

# 第五十二部分：生产模型调度（Model Scheduling）

## 52.1 分层：LLM 调用抽象成调度问题

禁止 `Agent → Provider` 直连。统一为：

```
Agent → Model Gateway → Scheduler → Model Pool → Provider
                                  │
                             决策写入 Trace
```

Scheduler 输入：Tenant、Priority、TaskType、ModelCapability、Cost、Latency、Quota、Concurrency、ProviderHealth、Region、TokenBudget。

## 52.2 调度策略与推荐管线

支持策略：Round Robin / Weighted RR / Least Load / Latency-based / Cost-based / Capability-based / Priority-based / Adaptive。

**推荐组合管线（逐级过滤，最后做负载均衡）**：

```
Capability Filter（能力匹配任务分级 §51.1）
  → Health Filter（排除 Unavailable）
  → Quota Filter（配额内）
  → Cost Filter（预算内）
  → Latency Filter（SLA 内）
  → Load Balance（RR/Least Load 从剩余候选选一）
```

每级过滤掉一个维度，最后只剩可用的均衡选择——而不是凭单一维度做硬编码。

## 52.3 Provider Health

持续记录：`P50/P95/P99`、Error Rate、429 Rate、Timeout Rate、Token Throughput。

```
Provider 状态：
  Healthy     → 正常接流量
  Degraded    → 自动降低该 Provider 流量权重
  Unavailable → 从候选池剔除，触发告警
```

状态由滑动窗口指标驱动（如 60s 内 429 Rate > 5% → Degraded）。**降级必须可观测**：`routing.provider_health = degraded(reason)` 写 Trace。

## 52.4 数据与测试

- 决策落 `routing` span 属性（model / provider / 各级 filter 命中的原因 / cost_estimate）。
- **测试**：注入 provider 故障，断言调度自动剔除并降流量、不产生额外错误；配额耗尽断言拒绝而非硬编。

---

---

# 第五十三部分：避免 Agent 串会话（Session Isolation）

## 53.1 会话身份必须全程携带

Session 相关结构至少含：`tenant_id, user_id, session_id, agent_id, conversation_id, run_id`。任何 Context / Memory / Retrieval / Cache / Tool 调用**必须带上主体与作用域**，由调用链透传（不是靠"读全局变量"）。

## 53.2 禁止全局 Context 与全局 Session 状态

- 禁止 `global_history / global_memory / global_agent_state` 这类全局可变状态承载会话。
- 禁止用进程内全局变量保存 Session。
- 禁止把 Worker 本地状态当作唯一 Session State —— **Worker 会处理不同用户**，本地缓存/单例一旦漏键即串会话。

> 会话状态只允许放在**显式作用域**：DB / Redis（带 session key）/ 请求上下文对象（显式传入，非线程/进程全局）。

## 53.3 Memory 隔离（服务端强制）

Memory 查询必须同时带 `tenant + user + agent + scope` 过滤，由 Repository 层强制注入：

```
User A 的查询 → WHERE tenant_id=A.tenant AND user_id=A.user ...
即使 User B 的 embedding 与查询"语义相似"，也绝不返回。
```

隔离不是"相似度排序后过滤"，而是**查询第一步就把 scope 钉死**（§6.4 同源）。

## 53.4 Cache 隔离

所有缓存 key 必须含 Tenant / User / Session 维度（§49.4）。命中任何缓存都必须先过权限校验，防止"缓存内容 + 已过期的权限"造成越权。

## 53.5 Async Job 隔离

Queue Message 必须携带完整身份：`tenant_id, user_id, session_id, agent_id, run_id, trace_id`。**Worker 取到消息后重新验证权限，不能只信任 Queue Payload**——消息可能被伪造/过期/来自已变更权限的主体。

## 53.6 测试

- **串会话注入测试**：并发两个不同用户的 Run，断言所有查询/缓存/记忆互不可见。
- **Worker 复用测试**：同一 Worker 进程依次处理不同用户任务，断言无状态泄漏。
- **Async 越权测试**：篡改 Queue Payload 身份字段，断言 Worker 拒绝。

---

# 第五十四部分：百万级知识库性能治理

## 54.1 Metadata Filtering 优先

检索**先过滤、后召回**，禁止"先全库检索、再过滤权限"：

```
过滤维度（按命中率排序）：tenant → department → permission → document_type → kb_version → time_range
```

过滤放在向量查询的 `filter` 条件里（pgvector/专用库原生支持），而不是召回后逐条剔除。否则 100 万块里可能召回一堆无权查看的内容，既浪费又泄密。

## 54.2 Partition 与分层索引

```
Tenant → Knowledge Base → Partition（domain/region）→ Vector Index
查询流程：先确定"去哪搜"（路由到分区/索引），再"搜什么"。
```

分层索引：

```
Global Index → Domain Index → KB Index → Local Index
```

命中路径越窄，召回集越小、越准、越快。

## 54.3 Hybrid Retrieval

百万级**不要单纯依赖向量相似度**。向量 + BM25 + Metadata Filter 三路，RRF 融合，重排兜底。纯向量对代码符号/专有名词/条款号等精确命中弱。

## 54.4 HNSW / IVF 参数治理——用 Benchmark 决定

| 索引 | 参数 | 含义 | 调优方向 |
|---|---|---|---|
| HNSW | M | 每层邻居数 | 大→召回高/内存高/插入慢 |
| HNSW | efConstruction | 建图搜索宽度 | 大→图更优/建索引慢 |
| HNSW | efSearch | 查询搜索宽度 | **查询期唯一召回旋钮** |
| IVF | nlist | 聚类数 | 大→更细/建索引慢 |
| IVF | nprobe | 查询探测聚类数 | 大→准/慢 |

**必须按数据量/召回/QPS/延迟/内存做 Benchmark 表格选参，不能凭经验拍**。基准样本用真实语料子集 + 标注过的 gold 结果。

## 54.5 Sharding（规模再增长）

按 `tenant_hash / kb / domain` 分片。**Cross-Shard 检索必须显式解决**，推荐：

```
Parallel Search（各分片并发）
  → Top-K Merge（归并取全局 top）
  → Fusion（RRF）→ Rerank → Top 5~10
```

## 54.6 Rerank 漏斗（不能"百万 → Rerank"）

```
百万块
  ↓ Metadata Filter + 向量/BM25 召回
Recall 100
  ↓ RRF Fusion
Fuse 50
  ↓ Rerank
20~50
  ↓
Top 5~10（进 Context）
```

Reranker 只精排**已收窄**的候选，成本与延迟可控。

## 54.7 Retrieval Cache

热点 Query 直接命中缓存返回检索结果。**Cache Key 必须含**：`kb_version + permission scope + embed_model_version + query_hash`（§49.4）。权限窄化时必须能按 scope 失效，否则命中即越权。

## 54.8 性能测试

- 用百万级合成语料做 Benchmark：召回率（Recall@k）、QPS、P95 延迟、内存，输出参数选型表。
- 分片场景：跨分片查询的正确性与延迟。
- 过滤场景：权限过滤前置后的召回正确性（不泄密）。

---

# 第五十五部分：Agent 异步任务治理

## 55.1 把 Job 当真正的生产任务系统

Agent 的异步工作（ingest、重排、评测、replay、长任务）不能靠"起个线程"。架构：

```
Producer → Message Queue → Scheduler → Worker Pool → Result Store
                 │
        ┌────────┴─────────┐
   Retry Queue   Dead Letter Queue   Delay Queue（定时/退避）
```

## 55.2 Queue 必须有容量上限（Admission Control）

禁止无限堆积。按水位逐级限流：

| Queue 水位 | 动作 |
|---|---|
| < 50% | 正常 |
| 50~70% | 正常，预警告警 |
| 70~85% | 限流（低优先级拒入） |
| 85~95% | 只接受高优先级（P0/P1） |
| > 95% | 拒绝低优先级，触发扩容/熔断 |

## 55.3 Worker Pool 按任务类型隔离

```
Agent Worker   Embedding Worker   RAG Worker   Graph Worker   Evaluation Worker
```

不要所有任务共用一个 Pool——否则一次 ingest 洪峰会饿死在线 Agent 任务。

## 55.4 优先级

```
P0 用户同步请求  >  P1 普通 Agent Job  >  P2 文档索引  >  P3 Evaluation  >  P4 Analytics
```

## 55.5 Fairness 与 Anti-Starvation

- **Per-Tenant Queue + 配额**：防止 Tenant A 提交 10 万任务占满所有 Worker。
- **Weighted Scheduling**：按租户权重分配，保证最小服务保障。
- **Queue Aging**：低优先级任务随等待时间提升优先级（`priority += f(age)`），避免永远饿死。

## 55.6 Job State Machine（禁止用 boolean）

```
CREATED → QUEUED → RUNNING → SUCCEEDED
              │        │  ↘ RETRYING → RUNNING（重试）
              │        │  ↘ WAITING（等待依赖/审批）
              │        ▼
              │      FAILED → DEAD_LETTER（重试耗尽）
              ▼
            CANCELLED / EXPIRED
```

状态必须持久化、可查询、可审计。**禁止 `completed=true` 单字段代替状态机**。

## 55.7 Zombie Job（Lease / Heartbeat / Visibility Timeout）

```
Worker 获取 Job → Lease 30s → 周期性 Heartbeat 续租 → Worker 崩溃
  → Lease 过期（无 Heartbeat） → Job Requeued（交给其他 Worker）
```

- 心跳丢失即视为崩溃，任务重新入队。
- 配合 §3.6 的工具幂等键，重放不产生重复副作用。

## 55.8 测试

- 水位限流测试、租户公平性测试（大租户不饿死小租户）、Aging 测试、Zombie 恢复测试、DLQ 兜底测试。

---

# 第五十六部分：Agent Service 起停设计

## 56.1 生命周期操作

支持：`Start / Stop / Restart / Drain / Pause / Resume`。

## 56.2 Graceful Shutdown（不能直接 kill）

```
Stop Accept New Request
  → Stop New Agent Run
  → 等待正在执行的 Run（限时）
  → Cancel 超时任务（状态转 CANCELLED，交给恢复/Queue）
  → Drain Queue（消费完已领取任务）
  → Close Connection（HTTP/SSE/WebSocket/DB/Redis）
  → Shutdown
```

## 56.3 Shutdown Timeout

不能无限等待：`Grace Period`（如 30s/60s/120s，可配）。超时后**剩余任务交给 Queue / Recovery**（§3.6 崩溃恢复），而不是强杀丢数据。

## 56.4 Startup 与 Readiness Gate

```
Load Config → Init Dependency → Check DB → Check Redis → Check Queue
  → Check Model Gateway → Warmup（连接池/缓存预热） → Ready
```

只有 Readiness 通过才接流量。**Liveness ≠ Readiness**：

- **Liveness**：进程活着（`/health/live`）——挂了才重启。
- **Readiness**：能否接请求（`/health/ready`）——依赖不可用（如 LLM 挂了）时返回失败，**流量暂停到依赖恢复**。

> 防止：LLM 挂了 → Liveness 判定失败 → K8s 不断重启整个 Agent。LLM 是外部依赖，它挂了应该 Readiness 置否、让负载均衡摘流量，而不是杀进程。

## 56.5 Rolling Deployment

```
Old → New → Health Check 通过 → 1% → 5% → 20% → 50% → 100%
任何指标恶化（error/latency/cost）→ 自动停止发布并回滚
```

---

# 第五十七部分：发布期间用户体验保护

## 57.1 Stateless Runtime

Agent Runtime **尽可能无状态**，会话/运行状态放 DB/Redis/Durable Store，**不放进程内存**（§ADR-02）。这是发布期不丢 Session、不中断 Run 的前提。

## 57.2 Connection Draining

旧实例停止接收新请求，但**继续处理已有连接**（HTTP/SSE/WebSocket/进行中的 Run），处理完成后才退出。

## 57.3 版本兼容

新旧 Worker 必须能共同消费同一队列 → **Message Schema 必须向后兼容**（新增字段加默认值，不删字段，不改变义）。

## 57.4 Schema Migration（Expand → Migrate → Contract）

禁止"先改 DB Schema，立刻发布新代码"。三步走：

```
1. Expand：加新列/新表，双写
2. Migrate：后台迁移数据，校验
3. Contract：删除旧列，清理双写

保证 Old 与 New 版本短时间共存时都正确。
```

## 57.5 Feature Flag 灰度高风险功能

高风险功能不走全量发布：按 `tenant → agent → user → percentage` 逐步放量。开关状态本身版本化（§30）。

## 57.6 Canary 指标与自动停止

灰度期看：Error Rate、Latency、Token Cost、LLM 429、Agent Success、Tool Success、RAG Recall、User Feedback。任一关键指标恶化（如 Error Rate ↑ / Latency ↑ / Cost ↑ 超阈值）→ **立即停止灰度并回滚**。

## 57.7 Rollback（不只回代码）

Rollback 必须快速、可验证、自动化，且**不止回滚代码**，要回滚到一致版本集：

```
Code + Prompt Version + Model Version + Agent Config + Tool Version + Knowledge Version + Schema Version
```

（知识版本建议不回滚内容，而是通过 §49.5 版本化缓存切换检索版本。）

---

---

# 第五十八部分：Agent Release Contract

任何 Agent / Skill / Tool / 平台版本发布前，**必须通过 10 项兼容性检查**（CI + 人工 checklist 双保险）：

| # | 检查项 | 内容 | 失败动作 |
|---|---|---|---|
| 1 | API Compatibility | 新旧版本对外 API 请求/响应兼容（schema 快照比对） | 阻断发布 |
| 2 | Queue Compatibility | Message Schema 向后兼容（§57.3） | 阻断发布 |
| 3 | DB Compatibility | Schema 符合 Expand→Migrate→Contract（§57.4）；无破坏性 DDL 混入 | 阻断发布 |
| 4 | Prompt Compatibility | 新 Prompt 在旧 Traces/评测集上无质量回退 | 阻断或降级为灰度 |
| 5 | Tool Compatibility | 工具 ref/参数/返回 schema 兼容；无工具意外下架 | 阻断发布 |
| 6 | Model Compatibility | 模型能力/价格/健康满足路由约束（§51/§52） | 阻断发布 |
| 7 | Config Compatibility | 配置版本可回滚、无缺键 | 阻断发布 |
| 8 | Memory Compatibility | 记忆读写格式兼容，不破坏存量记忆 | 阻断发布 |
| 9 | Trace Compatibility | 新版本 Trace/属性向后兼容，可观测不被破坏 | 阻断发布 |
| 10 | Rollback Compatibility | 可一键回滚到旧版本集（§57.7），回滚后数据可读 | 阻断发布 |

---

# 第五十九部分：生产问题定位能力

## 59.1 从 trace_id 到根因

用户反馈"刚才 Agent 回答错了"，开发者凭 `trace_id` 必须能沿这条链走到底：

```
trace_id → Request → Agent Run → Step → Model Call
  → Prompt Version → Model Version → Retrieval → Tool Call → Tool Result → Final Answer
```

## 59.2 必须能回答的 20 问（§7.4 呼应，完整清单）

1. 当时用哪个 Agent Version？ → `agent_version`
2. 用了哪个 Prompt？ → `prompt_version`
3. 用了哪个 Model？ → `routing.model`
4. 为什么选这个 Model？ → `routing.reason / escalation.chain`（§51.2 落 Trace）
5. 检索到了什么？ → `retrieval.chunks + provenance`
6. 使用了哪些 Context？ → `final_context_hash + 快照（S3）`
7. 调用了哪些 Tool？ → `tool_calls[]`
8. Tool 返回了什么？ → `tool_calls[].result_json`
9. LLM 花了多少 Token？ → `cost breakdown`（§50.1）
10. 花了多少钱？ → `estimated_cost / actual_cost`
11. 哪一步最慢？ → span 瀑布的 `duration_ms`
12. 哪一步失败？ → `error_code + status`（span/step）
13. 是否发生 Retry？ → `retries` 字段 + span 事件
14. 是否发生降级？ → `degradation` 事件（fallback 链）
15. 是否触发 Circuit Breaker？ → `breaker` 事件
16. 用户拥有怎样的权限？ → `policy.decision`（含 DENY 原因）
17. 是否存在 Cache Hit？ → `cache.hit/cache.key`（含版本集）
18. Cache 用的是什么 Version？ → `cache.key` 中的 version_set（§49.4）
19. 是否发生跨 Session 污染？ → §53 隔离断言 + audit（防串会话）
20. 是否可以 Replay？ → §60 Replay 材料齐全性检查

> 能回答这 20 问 = 可观测合格；答不全 = 设计/实现不合格（§1.3 硬门禁）。

## 59.3 定位方法与工具

1. **Trace 瀑布**：最慢/失败 span 一眼定位（§7.7）。
2. **对比 Replay**：同一 run 换 prompt/model/检索重放，AB 对比找变量（§60）。
3. **审计交叉验证**：权限拒绝/审批/越权事件与 Trace 关联。
4. **成本下钻**：从"租户→Agent→Run→LLM Call"逐层定位成本异常（§50）。

---

# 第六十部分：Replay / Debug

## 60.1 Replay 是排障的"时间机器"

生产问题不能只靠日志。每个 Run 保存**完整快照**（可重放的原材料）：

```
Input / AgentVersion / PromptVersion / ModelVersion / ToolVersion / KnowledgeVersion
RetrievedContext / ToolInput / ToolOutput / ModelOutput / RuntimeConfig
```

## 60.2 Replay 能力

- **原样 Replay**：复现问题（确定性优先：固定 model、temperature、随机种子）。
- **换参 Replay**：换 Prompt / Model / Retrieval / Reranker / Tool，对比找"变量在哪"。
- **分步 Replay**：从任意 step 断点续放，观察决策分叉点。
- **Diff**：两次 Replay 的上下文/输出差异，支撑回归测试（§24 数据飞轮）。

## 60.3 敏感数据脱敏（硬约束）

**禁止把 Password / Token / Secret / PII 直接进 Debug Log 或 Replay 快照。** 落盘前：

```
Ingress/Recorder 层统一脱敏：SecretReference 只存 ref（§17）
  · Masking：PII/密钥替换为占位
  · 规则：白名单字段原样，其余脱敏
  · 快照与日志同规则，避免"日志脱敏了快照没脱"的缝隙
```

## 60.4 Replay 与安全

- Replay 只允许 **owner / 被授权者**触发（`run:view` + 数据隔离）。
- Replay 执行仍走完整 Policy/审批，不因"排障"豁免安全。
- Replay 结果也写审计与成本。

---

# 第六十一部分：最终生产工程原则

| 原则 | 落地锚点 | 反例（不合格） |
|---|---|---|
| 可靠性优先于功能数量 | 每功能带预算/降级/恢复 | 功能上线无失败路径 |
| 性能必须可测量 | §54 Benchmark、P95 指标 | 凭感觉说"快" |
| 成本必须可归因 | §50 Tenant→LLM Call 层级 | "今天花了 $500" |
| 权限必须可验证 | §6 Policy + 审计 | 前端隐藏当隔离 |
| 缓存必须有 Scope | §49 key 含隔离维度 | `cache[query]` 全局桶 |
| 任务必须可治理 | §55 状态机 + 优先级 + 公平 | boolean 状态字段 |
| 模型必须可调度 | §51/§52 路由 + 决策落 Trace | 写死"永远用 GPT-X" |
| 请求必须可取消 | §3 CANCELLED + 幂等 | 取消=杀进程 |
| 服务必须可优雅停止 | §56 Drain/Readiness | 直接 kill |
| 发布必须可灰度 | §57 Canary + Flag | 全量一把梭 |
| 版本必须可回滚 | §57.7 版本集回滚 | 只能改 prompt 救火 |
| 生产问题必须可 Replay | §59/§60 20 问 + 快照 | 只能加日志重跑 |

> **最终目标不是"Agent 能运行"，而是"Agent 可以长期稳定运行，并且开发团队知道它为什么这样运行"。** 可观测是底线，可归因是纪律，可隔离是合规，可回滚是勇气，可 Replay 是效率——这五条贯穿整个平台的设计与实现。








