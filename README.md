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
| 存储 | PostgreSQL + pgvector（开发/生产统一，docker-compose 提供）· alembic 迁移 |
| 其他 | Redis（可选，空则进程内锁）· OpenTelemetry 可观测 |

## 快速开始

```bash
# 1. 初始化虚拟环境并安装
make install

# 2. 启动依赖数据库（Postgres+pgvector，本机 5433）
docker compose up -d pgvector

# 3. 启动后端（FastAPI，端口 8000；连接 Postgres，mock LLM Provider 无需 API key）
make run

# 4. 前端开发服务器（Vite，代理 /api 到 8000）
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

# 数据库连接由 .env 的 APP_DATABASE_URL 控制（默认本地 Postgres:5433，即 compose 的 pgvector）
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

### 首页
<!-- 首页：平台总览与快捷入口 -->
![首页](/docs/screenshots/EB331470-B103-4987-B3E3-5E5A840919CF.png)

### 发布

按发布流主线操作：总览 → 创建发布单 → 详情（走流程）→ 列表。

<!-- 发布总览：当前 Agent / 当前版本 / 发布状态 / 主流程步骤条 / 主按钮（创建发布单 或 继续当前发布） -->
![发布总览](/docs/screenshots/94AD073E-3017-4EAB-9B71-1A5AABC063FB.png)


### 工作区

<!-- 知识库：文档 / 切片 / 检索验证 -->
![知识库](/docs/screenshots/18981D47-ACB3-4966-9EA9-F51E35E00457.png)

<!-- 对话：Agent 对话与工具调用 -->
![对话](/docs/screenshots/E8756D92-F190-4D63-A025-2D5E2D164E31.png)

<!-- 评测：基准集 / 回归 / 安全评测 -->
![评测](/docs/screenshots/37A2479D-3979-4EAF-BDDB-33FFB4285CB0.png)

<!-- 任务记录：Agent Run 列表与详情 -->
![任务记录](/docs/screenshots/075D96D1-63A1-49B1-856F-E727DDE7FAE4.png)

### 治理与管理

<!-- 用户管理：用户与角色分配 -->
![用户管理](/docs/screenshots/D39071E8-4590-4CE9-AA23-B48BC437A1C4.png)

<!-- 权限策略：角色 / 策略 -->
![权限策略](/docs/screenshots/90749DE7-7884-425A-8CB7-6A60638B211E.png)

<!-- 操作记录：审计日志 -->
![操作记录](/docs/screenshots/3ECF64CB-974A-4BB7-ABD9-4309AE540BD1.png)

<!-- 任务队列：队列运维 -->
![任务队列](/docs/screenshots/32BB8C30-698D-49A3-AE87-5441EEA35DAE.png)

<!-- 事件：事件流 -->
![事件](/docs/screenshots/FA7F906B-34D1-4AE5-BBDB-DCC5DBC527CA.png)

<!-- 数据生命周期：数据保留与清理 -->
![数据生命周期](/docs/screenshots/1FB0BB81-55E1-4F66-9CCC-657E9D562C61.png)

<!-- 配置中心：运行时配置 -->
![配置中心](/docs/screenshots/401F7F49-97AE-4A9D-A418-45340CA03805.png)

<!-- 成本：成本统计与趋势 -->
![成本](/docs/screenshots/E45F88F5-0617-4931-A632-E4802E692B8F.png)

<!-- 工具：工具注册与管理 -->
![工具](/docs/screenshots/9F4BF39F-8BD7-47E1-8760-879F12F2EE54.png)

<!-- 审批：待审批事项 -->
![审批](/docs/screenshots/C0BEE9D8-D6D4-435B-AC7B-A7429A173762.png)

<!-- 历史记忆：Agent 记忆回放 -->
![历史记忆](/docs/screenshots/14FFEFF5-8869-4A9F-9723-1357897A5B95.png)

<!-- 关系图谱：实体与关系 -->
![关系图谱](/docs/screenshots/986387A3-2401-498D-9053-E02EF8B98F69.png)

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
