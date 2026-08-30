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

## 界面预览

> 截图放在 `docs/screenshots/`，markdown 里用相对路径引用即可，GitHub 会自动渲染。
> 占位文件名已固定，把截图重命名成对应名字覆盖进去即可显示。

### 发布

按发布流主线操作：总览 → 创建发布单 → 详情（走流程）→ 列表。

<!-- 发布总览：当前 Agent / 当前版本 / 发布状态 / 主流程步骤条 / 主按钮（创建发布单 或 继续当前发布） -->
![发布总览](docs/screenshots/release-overview.png)

<!-- 创建发布单：目标版本选择 + 发布方式 + 自动执行 + 右侧发布预览 -->
![创建发布单](docs/screenshots/order-create.png)

<!-- 发布单详情：步骤流转 / 每步执行结果 / 节点快照（含创建时填写的参数）/ 留痕 / 回滚 / 终止 -->
![发布单详情](docs/screenshots/order-detail.png)

<!-- 发布单列表：全部发布单（进行中 / 已完成 / 已终止） -->
![发布单列表](docs/screenshots/order-list.png)

### 工作区

<!-- 首页：平台总览与快捷入口 -->
![首页](docs/screenshots/home.png)

<!-- 知识库：文档 / 切片 / 检索验证 -->
![知识库](docs/screenshots/knowledge.png)

<!-- 对话：Agent 对话与工具调用 -->
![对话](docs/screenshots/chat.png)

<!-- 评测：基准集 / 回归 / 安全评测 -->
![评测](docs/screenshots/evaluation.png)

<!-- 任务记录：Agent Run 列表与详情 -->
![任务记录](docs/screenshots/runs.png)

### 治理与管理

<!-- 用户管理：用户与角色分配 -->
![用户管理](docs/screenshots/users.png)

<!-- 权限策略：角色 / 策略 -->
![权限策略](docs/screenshots/policies.png)

<!-- 操作记录：审计日志 -->
![操作记录](docs/screenshots/audit.png)

<!-- 任务队列：队列运维 -->
![任务队列](docs/screenshots/queue.png)

<!-- 事件：事件流 -->
![事件](docs/screenshots/events.png)

<!-- 数据生命周期：数据保留与清理 -->
![数据生命周期](docs/screenshots/data.png)

<!-- 配置中心：运行时配置 -->
![配置中心](docs/screenshots/settings.png)

<!-- 模型健康：模型状态与限流 -->
![模型健康](docs/screenshots/model.png)

<!-- 成本：成本统计与趋势 -->
![成本](docs/screenshots/cost.png)

<!-- 工具：工具注册与管理 -->
![工具](docs/screenshots/tools.png)

<!-- 审批：待审批事项 -->
![审批](docs/screenshots/approvals.png)

<!-- 历史记忆：Agent 记忆回放 -->
![历史记忆](docs/screenshots/memory.png)

<!-- 关系图谱：实体与关系 -->
![关系图谱](docs/screenshots/graph.png)

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
