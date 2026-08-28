# 部署手册

> 目标：**一套官方推荐拓扑**，其余能力（gVisor 沙箱、外部 Secret Manager、OTLP 导出等）均为可选增强。运维动作按"升级 / 备份 / 恢复 / 回滚"逐条给标准操作。

## 1. 官方推荐拓扑

`docker compose`（根目录 [`docker-compose.yml`](../../docker-compose.yml)）是唯一官方路径，5 个服务组成一个部署单元：

| 服务 | 镜像 | 职责 | 说明 |
|---|---|---|---|
| `pgvector` | pgvector/pgvector:pg16 | PostgreSQL + pgvector 扩展 | **唯一数据库**，承载业务/审计/评测 + 知识向量 |
| `redis` | redis:7 | 限流 / 队列租约 / 分布式锁 | 多实例 HA 需要（单实例可不配） |
| `minio` | minio/minio | 对象存储 | 大文件/上传暂存 |
| `app` | 本仓库构建 | 应用服务（FastAPI + 前端） | 内置 prod 安全门禁 |
| `caddy` | caddy:2 | 反向代理 + 自动 TLS（Let's Encrypt） | 无域名为本地 HTTP |

- 端口：应用 `8000`；前端由后端托管在 `/`（React SPA，HashRouter）。
- **数据库只用一个 pgvector 实例即可**，不要额外再起 postgres（旧版本已收敛，见 Git 记录）。

### 生产启动清单

| 项 | 必须 | 说明 |
|---|---|---|
| `APP_ENVIRONMENT=prod` | ✅ | 触发安全门禁：强制 JWT、拒绝默认签名密钥 |
| `APP_AUTH_JWT_SECRET` | ✅ | 强随机；`openssl rand -hex 32`；泄露可伪造任意用户 |
| `APP_SECRET_ENCRYPTION_KEY` | 推荐 | 密钥加密主密钥；为空则从 JWT secret 派生 |
| `APP_LLM_*` | ✅ | 真实 LLM：provider / base_url / api_key / model |
| `APP_DATABASE_URL` | ✅ | `postgresql+asyncpg://…@pgvector:5432/agent` |
| `APP_REDIS_URL` | ✅ | `redis://redis:6379/0`（多实例必需） |
| `DOMAIN` | 按需 | 绑定域名后 Caddy 自动 Let's Encrypt |
| gVisor / OTLP / MCP | 可选 | 见下文高级配置 |

`docker compose up -d --build` 直接按 `.env` 与 compose 环境注入。**迁移在应用启动时自动执行**（数据库为 alembic 管理时 `upgrade head`），无需手动迁移。

## 2. 升级

```bash
git pull && docker compose build && docker compose up -d
# 检查健康
curl -sf http://$DOMAIN/health/ready
```

- 数据库 schema 由启动自动迁移（alembic），先起一个副本验证再滚到生产。
- 大版本升级务必先 `备份`（下节）。

## 3. 备份

```bash
# SQLite（开发）与 PostgreSQL（生产）通用：
.venv/bin/python scripts/backup.py backup
# PG 走 pg_dump；SQLite 做 copy + WAL checkpoint，输出到 backups/ 并打印路径
```

- 建议定时备份并异地保存（备份文件含审计/用户/配置等敏感数据，注意加密与访问控制）。
- 对象存储（MinIO）与数据库分开备份，应用内对象路径见数据来源。

## 4. 恢复

```bash
.venv/bin/python scripts/backup.py restore <备份文件>
# 恢复后重启应用加载（compose：docker compose restart app）
```

- PostgreSQL 恢复建议先 drop/recreate 目标库，再 `psql -f` 导入。
- 恢复会覆盖当前数据，谨慎操作；恢复前先对当前库再做一次备份。

## 5. 回滚（两层面）

| 层面 | 场景 | 操作 |
|---|---|---|
| **应用内版本回滚** | Agent 行为漂移 / 质量回退 | 「发布」页对 GRAY/ACTIVE 版本一键回滚/停用；Canary 指标恶化时系统建议回滚 |
| **宿主/镜像回滚** | 部署缺陷 | 切回上一 tag：`docker compose up -d <上一镜像tag>`；配合恢复上一备份 |

> 应用内回滚 ≠ 宿主回滚：前者只换 Agent 版本，后者连代码一起换。

## 6. TLS / 域名

- 在 DNS 把 `agent.example.com` 的 **A 记录**指向服务器公网 IP，开放 80/443。
- `.env` 设置 `DOMAIN=agent.example.com`。
- 重启 compose：Caddy 自动申请/续期 Let's Encrypt。
- 不设 `DOMAIN` 则走 `http://localhost`（本地/内网 HTTP）。

## 7. 密钥管理

- `APP_AUTH_JWT_SECRET`：JWT 签名（HS256），生产必须强随机独立。
- `APP_SECRET_ENCRYPTION_KEY`：SecretManager 的 Fernet 主密钥；应用内「密钥管理」存的第三方凭据会用它加密落库，**不會以明文落盘/日志**。
- 生产建议从 KMS/外部 Secret Manager 注入这两个环境变量，不在 `.env` 里明文版本控制。
- 轮换：改主密钥会影响已存的密文数据，跟随产品发布节奏做。

## 8. 高级/可选能力（不阻塞主路径）

| 能力 | 打开方式 |
|---|---|
| 沙箱容器化（gVisor） | `APP_SANDBOX_DOCKER=true` + `APP_SANDBOX_DOCKER_RUNTIME=runsc`（见 `../productization-plan.md` 部署指南） |
| 可观测导出 | `APP_OTLP_ENDPOINT=`（OTLP HTTP） |
| MCP 服务接入 | `APP_MCP_SERVERS` JSON + `APP_MCP_TOOL_ALLOWLIST` |
| OIDC SSO | `APP_OIDC_ENABLED=true` + jwks/issuer/audience（见集成指南） |
| 多区域 HA | `APP_REGION` / `APP_INSTANCE_ID`（MVP 切片：实例身份与就绪） |
| 备份治理/容量规划 | 定时任务 + `scripts/bench_load.py` 压测模型估算 |

## 9. 健康检查

- `/health/live`：存活
- `/health/ready`：就绪（数据库可达）
- `/health/ha`：实例身份 / region / 队列水位
- `/meta`：agent_id / tenant / 版本信息