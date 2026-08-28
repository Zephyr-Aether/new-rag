# 数据安全与权限说明

> 面向客户的安全/合规评估。**目标是让"安全与治理"成为可验收的能力，而不是藏在代码里的开关。** 每条都标注现状与落地配置。

## 1. 认证

| 能力 | 现状 | 说明 |
|---|---|---|
| 密码存储 | ✅ | pbkdf2_hmac(100k 迭代)；**传输非明文**（客户端先 SHA-256 再传） |
| 首登强制改密 | ✅ | 管理员下发的密码标记 `must_change_password`，登录后强制改 |
| 会话 | ✅ | JWT(HS256)，默认 3600s 过期；`/auth/me` 返回生效权限供前端显隐 |
| 外部身份源 | ✅ OIDC / 🚧 SAML | OIDC/JWKS 可接入；SAML 为路线图（见[集成指南](integration-guide.md#6)） |

## 2. 授权（RBAC，默认拒绝）

- **默认拒绝**：无匹配策略即拒绝；**DENY 优先于 ALLOW**；策略可落在用户级 / 角色级 / 租户级。
- 粒度：`action × resource`。resource 级策略可做细粒度数据授权。
- 前端导航/按钮按 `/auth/me` 的生效权限显隐（管理员区对无治理权限用户隐藏）。
- 权限动作示例：`run:create`、`tool:execute`、`kb:ingest`、`release:publish`、`queue:ops`、`data:purge`、`policy:manage`、`config:write`。

## 3. 数据保护

| 项 | 现状 | 说明 |
|---|---|---|
| 密钥加密 | ✅ | SecretManager 用 Fernet **加密落库**；主密钥来自 `APP_SECRET_ENCRYPTION_KEY`（或从 JWT secret 派生），支持 KMS/外部 Secret Manager 注入 |
| 明文不落盘/不落日志 | ✅ | 第三方凭据只存密文；日志不打印密钥 |
| Trace 脱敏 | ✅ | Trace payload 落库前脱敏，且按采样率（`APP_TRACE_PAYLOAD_RATE`）存储 |
| Token 成本分项 | ✅ | P/H/T/R（prompt/history/tool/rag）分项记录，便于成本归属审计 |
| 对象/上传 | ✅ | 上传入 MinIO/库，来源可追溯 |

## 4. 隔离与执行安全

- **多租户隔离**：所有 API 按 `tenant_id` 作用域；上传会话有租户归属校验（曾修复跨租户 IDOR，含迁移 0010）。
- **沙箱**：
  - 开发：子进程 + rlimit；
  - 生产：Docker `--network none`（`APP_SANDBOX_DOCKER=true`），可升级 gVisor（`runsc`）；
  - 封禁：`os.system / subprocess / os.spawn* / os.open` 等，不泄漏宿主 env，出站端口受控。
- **SSRF 防护**：`http.get` 单次解析并固定已验证 IP（http.client + SNI 用原域名），防内网扫描与 TOCTOU。

## 5. 审计与合规

| 能力 | 现状 | 说明 |
|---|---|---|
| 审计日志 | ✅ | 关键操作全量记录，可按租户查 |
| 审计导出 | ✅ | `GET /audit/export` CSV，直接对接合规取证 |
| 幂等 | ✅ | `Idempotency-Key`（24h TTL）防自动化重试造成重复写入 |
| 审批门禁 | ✅ | 高风险工具执行前审批；webhook/邮件/log 通知 + HMAC 验签 |
| 发布门禁 | ✅ | 契约检查 + 基准回归回退阻断 + 灰度 Canary 决策，全程可回滚 |
| 数据生命周期 | ✅ | 租户数据清除 / 全局清扫（`/data/.../purge`、`/data/sweep`）满足删除权 |

## 6. 生产安全基线（交付即合规的最低要求）

1. `APP_ENVIRONMENT=prod`（强制认证、拒绝默认 JWT secret）。
2. 强随机 `APP_AUTH_JWT_SECRET`（独立、KMS 注入）。
3. 独立 `APP_SECRET_ENCRYPTION_KEY`。
4. 最小权限建号，不用通配。
5. 沙箱容器化（有 Docker 时 `APP_SANDBOX_DOCKER=true`）。
6. 定期备份 + 异地加密留存（`scripts/backup.py`）。
7. 审计导出归档策略与套餐「审计保留期」对齐（见[套餐定义](../commercial/pricing.md)）。

## 7. 已知边界（如实告知，便于评估）

- **SAML** 未实现（OIDC 已有）。
- 沙箱为进程/容器级；**非机密虚拟机级**（gVisor 是可选增强，未开则不保证内核级隔离）。
- 审批通知 webhook 验签需要你在接收端按[集成指南](integration-guide.md#3)实现。
- 密钥轮换会重加密既有密文，需随发布节奏做。