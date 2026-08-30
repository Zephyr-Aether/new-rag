# Agent 发布与治理平台

基于 **FastAPI + React** 的企业级 Agent 平台，聚焦「Agent 发布与治理」：

- **发布流程**：草稿 → 契约检查 → 回归评测 → 灰度放量 → 全量上线/回滚，按「发布单」全程留痕、可复盘
- **治理**：RBAC 权限策略、发布权限门禁、审批、审计、模型健康与成本监控
- **Agent 运行时**：对话 / Run 执行、工具调用、记忆、知识库检索、Trace 追踪

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | Python 3.12 · FastAPI · SQLAlchemy 2.0 (async) · Pydantic v2 |
| 前端 | React · TypeScript · Vite · antd / shadcn 风格组件 |
| 存储 | SQLite（开发默认）· PostgreSQL + asyncpg（生产）· alembic 迁移 |
| 其他 | Redis（可选，空则进程内锁）· OpenTelemetry 可观测 |

## 快速开始

```bash
# 1. 初始化虚拟环境并安装
make install

# 2. 启动后端（FastAPI，端口 8000；默认 SQLite dev.db，mock LLM Provider，无需外部依赖）
make run

# 3. 前端开发服务器（Vite，代理 /api 到 8000）
cd frontend && npm install && npm run dev
```

访问 `http://localhost:8000`（后端直接托管 `frontend/dist` 产物，含 SPA 回退）或 Vite 开发端口。

### 生产构建前端

```bash
cd frontend && npm run build
# 产物写入 frontend/dist，后端启动时自动托管
```

## 数据库与迁移

```bash
# 应用全部迁移
make migrate

# 生成新迁移（模型加列后执行，见 CLAUDE.md 约定）
make migrate-gen

# 数据库连接由 .env 的 APP_DATABASE_URL 控制（默认 SQLite，生产用 PostgreSQL）
```

- 全量参考 schema 见 `schema.sql`
- 启动时：alembic 管理的库自动 `upgrade head`（先于 create_all，避免重复建表冲突）

## 目录结构

```
app/                后端
  main.py           FastAPI 入口 / 路由装配
  release/          发布流程 + 发布单（核心域）
  agent/            Agent 运行时（runs / sessions / model）
  knowledge/        知识库
  memory/           记忆
  evaluation/       评测（回归 / 安全 / canary）
  cost/             成本
  security/         权限策略 / 用户 / 审计
  storage/          SQLAlchemy 模型
alembic/            DB 迁移
frontend/           前端（React + TS）
  src/pages/Release/  发布总览 / 创建 / 详情 / 列表
docs/               设计文档
scripts/            冒烟 / 演示 / 评测脚本
schema.sql          全量表结构参考
```

## 主要功能

- **发布流**：`创建草稿 → 契约检查 → 回归评测 → 灰度放量 → 全量上线/回滚`，每步门禁、留痕入库
- **发布单**：一次发布周期的正式记录（单号 / 快照 / 留痕 / 回滚 / 终止），详情页可复盘创建时填写的参数与各步执行结果
- **版本治理**：版本只增不改（§22），可回退；契约检查（§58）含 10 项兼容性门禁
- **灰度与 Canary**（§57）：百分比 + 用户哈希放量，指标恶化自动停 / 回滚
- **RBAC 权限**：角色 / 策略 / 用户，管理能力看「管理员」角色

## 测试与检查

```bash
make test     # pytest
make lint     # ruff
make ci       # lint + test + chaos + smoke-auth
```

## 相关文档

- `CLAUDE.md` — 项目协作约定（写代码前先对照）
- `docs/productization-plan.md` — 产品化计划
- `docs/enterprise-agent-design.md` — 架构设计
