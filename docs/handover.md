# Agent 平台交接文档

企业级 Agent 平台：FastAPI 单体后端 + React/shadcn 前端控制台。运行时的可靠性内核（状态机/预算/取消/恢复）、发布治理（契约/灰度/回滚）、知识层、成本、安全、可观测均已落地；前端覆盖全部后端模块的可视化操作。

> 设计规范见 [enterprise-agent-design.md](enterprise-agent-design.md)。本文件只列**已实现功能点**与**已知生产形态边界**，供接手人快速上手。

---

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.12 / FastAPI / SQLAlchemy 异步 / Pydantic v2 |
| 存储 | SQLite（开发/测试默认，`sqlite+aiosqlite`）/ PostgreSQL + pgvector（生产，docker-compose 提供）/ 可选 Redis |
| LLM | OpenAI 兼容网关；默认 MockProvider（离线跑通全链路） |
| 前端 | React 18 + TypeScript + Vite + Tailwind v4 + **shadcn/ui** + react-router |
| 可观测 | OpenTelemetry（OTel）Trace + 采样 payload 存储 |
| 测试 | pytest（239 个）+ ruff + 混沌/压测脚本 |

---

## 快速开始

```bash
# 后端（无需外部依赖：dev.db + mock provider）
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
# 打开控制台 http://localhost:8000/  （前端构建产物由后端托管；dev 热更：cd frontend && npm run dev → :5173）

# 测试 / 质量
.venv/bin/pytest -q        # 239 tests
.venv/bin/ruff check app tests

# 常用脚本
.venv/bin/python scripts/smoke.py      # 端到端冒烟
.venv/bin/python scripts/chaos.py      # 混沌注入报告
.venv/bin/python scripts/demo.py       # 演示（工具+RAG+Trace+审计）
.venv/bin/python scripts/eval.py       # 评测 Recall@k/MRR
.venv/bin/python scripts/bench_load.py # QPS/延迟压测
.venv/bin/python scripts/bench_shard.py# 分区检索压测
```

接真实 LLM：`.env` 设 `APP_LLM_PROVIDER=openai` + `APP_LLM_BASE_URL`/`APP_LLM_API_KEY`。

---

## 功能点清单

### 1. Agent Runtime 内核（`app/agent/`）

| 功能 | 说明 | 位置 |
|---|---|---|
| 状态机 | 12 态 + 守卫 + 历史审计（`AgentState`） | [runtime/state.py](app/agent/runtime/state.py) |
| 执行引擎 | 循环 + 预算 + 死循环指纹 + 模型退避重试 | [runtime/runtime.py](app/agent/runtime/runtime.py) |
| 执行预算 | 步数/Token/成本/工具调用/时长上限 | [runtime/budget.py](app/agent/runtime/budget.py) |
| 取消 | 协作式取消（进程内/Redis 锁），在途中断 | [runtime/cancel.py](app/agent/runtime/cancel.py) |
| 检查点/续跑 | 每步落 checkpoint，崩溃后 resume（工具按幂等键至多一次） | [runtime/store.py](app/agent/runtime/store.py) |
| 僵尸回收 | 锁过期 run 标 FAILED / 有检查点自动续跑 | [runtime/recovery.py](app/agent/runtime/recovery.py) |
| Replay | 原始 input/版本集重放，可换 model/prompt/检索 top_k，diff 对比 | [agent/api/runs.py](app/agent/api/runs.py) |
| 上下文压缩 | 历史轮次压缩为摘要 | [agent/context/summary.py](app/agent/context/summary.py) |

### 2. 模型网关 / 路由（`app/agent/model/`）

| 功能 | 说明 |
|---|---|
| Provider 抽象 | `BaseProvider`：Mock（离线确定性）/ OpenAI 兼容 |
| 健康与路由 | 滑动窗口错误率/429/延迟 → Healthy/Degraded/Unavailable + 降权 |
| 调度 | 分级模型过滤管线（`ModelScheduler`），决策落 LLMCallRow 供 Replay 对比 |
| 限流/熔断 | 滑动窗口限流 + CircuitBreaker |

### 3. 工具全管线（`app/tool/`）

| 功能 | 说明 | 位置 |
|---|---|---|
| 注册表 | JSON Schema 定义 + LLM schema 暴露 | [tool/registry.py](app/tool/registry.py) |
| 编排管线 | resolve → 权限 → 限流 → 风险闸(审批) → 幂等 → 校验 → 执行 → 审计 | [tool/runtime.py](app/tool/runtime.py) |
| 内置工具 | `calc.add` / `echo` / `http.get`（SSRF 防护） / `kb.search` / `graph.query` | [tool/registry.py](app/tool/registry.py) |
| Secret 引用 | 工具声明 credential_ref，执行时注入真实凭据（LLM 不可见） | [security/secrets.py](app/security/secrets.py) |

### 4. 发布治理（`app/release/`）★ 旗舰能力

| 功能 | 说明 | API |
|---|---|---|
| 版本管理 | 版本只增不改，DRAFT→ACTIVE；列表/创建 | `GET/POST /agents/{id}/versions` |
| §58 发布契约 | 发布前 10 项兼容性检查（fail 阻断 / warn 人工签核），publish 门禁 | `POST /agents/{id}/versions/{v}/contract-check` |
| §20 回归门禁 | 对 BADCASES 评测集回归，pass_rate 对比上一版本，回退阻断 | `POST /agents/{id}/versions/{v}/regression` |
| 灰度 | 百分比 + 用户哈希命中，需 ACTIVE 基底 | `POST .../gray` |
| 回滚/停用 | 一键回滚到指定版本；canary 自动 halt | `POST /agents/{id}/rollback` |
| §57.6 Canary 指标 | 错误率/成本/**延迟/Tool Success/RAG Recall** 任一恶化即停 | `POST /agents/{id}/canary/check` |
| §22.1 版本冻结 | run 创建时冻结 agent/prompt/model/tool/knowledge 版本，运行中不漂移 | 落 `model_config.frozen_versions` + Trace |
| 发布指标 | 按 release_version/status 聚合运行量/成本/错误率 | `GET /agents/{id}/release-metrics` |

### 5. 知识层（`app/knowledge/`）

| 功能 | 说明 |
|---|---|
| 入库 | 结构感知分块（Markdown），整体替换按文档 id |
| 混合检索 | 向量(HashEmbedding/pgvector HNSW) + BM25 → RRF → rerank，provenance 回源 |
| §22.1 版本冻结 | run 级 `knowledge_version` 透传，入版本化缓存键（升级自然失效） |
| §24 分区 | tenant 分片 + 文档哈希分桶，索引按分区隔离 |
| 检索缓存 | 版本化缓存（tenant/permission/kb_version/embed_version/query） |

### 6. 图 / 记忆

| 功能 | 说明 | 位置 |
|---|---|---|
| Knowledge Graph | 实体 + 事实，provenance / 时间有效性（valid_from/to）/ 冲突（旧值 SUPERSEDED） | [graph/](app/graph/) |
| 记忆 | 写读 + 软删 + TTL，source_trust 分级 | [memory/](app/memory/) |

### 7. 成本（`app/cost/`）

| 功能 | 说明 | API |
|---|---|---|
| 归因 | 按 tenant/user/agent/version 聚合 tokens/cost | `GET /cost/overview` |
| 增长告警 | Token/Run 环比，超阈值告警 | `GET /cost/growth` |
| §50.1 对账 | 估算 cost 按权威价/账单记录重算 `actual_cost` 并校正 run.cost | `POST /cost/reconcile` |

### 8. 安全（`app/security/`）

| 功能 | 说明 |
|---|---|
| PolicyEngine | 默认拒绝 + DENY 优先，policies 表 |
| 审计 | 全量落库 audit_logs（决策链可见） |
| 认证 | JWT（HS256 MVP）+ OIDC/JWKS 外部身份验证 |
| 脱敏 | 观测/排障 API 返回掩码视图（`mask_object`） |
| SSRF | http.get 内网地址拦截 |
| Secret 管理 | 工具凭据引用注入 |

### 9. 队列 / 事件 / 数据（`app/queue/` `app/events/` `app/data/`）

| 功能 | 说明 | API |
|---|---|---|
| 队列 | 按任务类型分 Worker Pool + 优先级 + 水位限流/背压 | `GET /queue/jobs` |
| §11 单飞 | 并发重复任务按 dedupe_key 合并（同键只执行一次） | |
| §55 租约 | claim/heartbeat/recover_zombies（崩溃任务回收） | |
| DLQ | DEAD_LETTER 状态 + 重放 | `POST /queue/jobs/{id}/requeue` |
| §28.2 事件 | Outbox 幂等发布（同 dedupe_key 返回既有事件） | `POST /events/publish`, `GET /events` |
| §26.2 数据生命周期 | 保留期清扫 + 租户 purge（软删） | `POST /data/sweep` |

### 10. 配置中心 / 可观测 / 混沌（`app/configcenter/` `app/observability/` `app/chaos/`）

| 功能 | 说明 |
|---|---|
| 版本化配置 | 配置只增不改，set 产生新版本，回滚=读指定版本 |
| Feature Flag | 按 percentage/tenant/user 放量，规则版本化 |
| OTel Trace | agent.run / tool.execute / llm.call span，属性含灰度状态/冻结版本 |
| Payload 采样 | 按采样率存 prompt/输出（脱敏），`GET /runs/{id}/trace/payloads` |
| §80 混沌 | LLM 慢/失败/429、工具失败、取消、DB 慢/故障（`ChaosProvider`/`ChaosSessions`） | [chaos/](app/chaos/) |

### 11. 前端控制台（`frontend/`，React + shadcn）

| 页面 | 功能 |
|---|---|
| 仪表盘 | 总 run/成本/token/队列水位 + 环比 + 最近 run |
| Run 运行/详情 | 发起对话（同步/异步）、Timeline、LLM 调用明细、replay/compare |
| 发布/版本 | 版本表 + 创建/发布/灰度/回滚/停用 + **契约报告弹窗** + 回归 + 指标 + **发布全流程引导向导** |
| 知识库 | 入库 + 检索（命中/provenance） |
| 成本 | 归因 + 环比 + 对账按钮 |
| 工具 | 工具表 + JSON 参数调用 |
| 事件/队列/审批 | Outbox 发布、DLQ 重放、审批批准/拒绝 |

---

## 生产形态边界（已做地基，需真实环境验证）

| 项 | 现状 |
|---|---|
| 百万级分片 | 分区地基 + pgvector HNSW 就绪，无 1M 行真实验证 |
| 多区域 HA | 仅 `/health/ha` 身份切片 + 队列排空；复制/故障转移未做 |
| Sandbox | 仅工具输出上限 + SSRF 端口防护；子进程隔离未做 |
| MCP 网关 | HTTP JSON-RPC 最小集；SSE 流式/stdio/notifications 未做 |
| Redis 故障/网络抖动混沌 | 测试环境无 Redis、网络为真实外网 |
| 账单对账上游 | 有账单记录摄入格式；真实 provider 账单 API 适配器未做 |

---

## 主要 API 前缀

`/agents`（runs+release）`/tools` `/knowledge` `/graph` `/memory` `/approvals` `/auth` `/audit` `/cost` `/model` `/queue` `/events` `/data` `/evaluations` `/health/*` `/meta`。完整 OpenAPI 见 `/docs`。
