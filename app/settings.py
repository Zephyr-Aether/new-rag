import os
from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=os.getenv("APP_ENV_FILE", ".env"),
        extra="ignore",
    )

    app_name: str = "agent-platform"
    environment: str = "dev"  # dev / test / prod
    debug: bool = False

    # ---- storage ----
    # 默认本地 Postgres（docker compose up -d pgvector）；测试用 SQLite（conftest 覆盖）
    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5433/agent"
    redis_url: str = ""  # 空 => 进程内锁（单实例）

    # ---- LLM ----
    llm_provider: str = "mock"  # mock | openai
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "mock-model"
    llm_timeout_s: float = 30.0
    embedding_model: str = "text-embedding-3-small"
    # Model Router（§8）：分级模型，空则回落 llm_model
    llm_model_small: str = ""
    llm_model_medium: str = ""
    llm_model_large: str = ""
    # LLM 限流（§37）：每秒/分钟滑动窗口默认额度
    llm_rate_limit: int = 100
    llm_rate_limit_window_s: float = 60.0
    # LLM 熔断（§39）
    llm_breaker_threshold: int = 5
    # §17.3 Trace payload 采样率（属性全量，payload 按此率存储）
    trace_payload_rate: float = 0.1
    # 认证（§16/§27）：JWT（HS256 MVP；OIDC/JWKS 后置）
    auth_jwt_secret: str = "dev-secret-change-me"
    auth_jwt_issuer: str = "agent-platform"
    auth_jwt_algorithm: str = "HS256"
    auth_jwt_expires_s: int = 3600
    auth_require_jwt: bool = False  # True 时拒绝无有效 Bearer 的请求（生产）
    # §6.5 密钥加密主密钥：空则从 auth_jwt_secret 派生（dev 便利）；生产建议独立设置
    secret_encryption_key: str = ""
    # OIDC/JWKS 外部身份（§16 升级：RS256 校验外部 id_token）
    oidc_enabled: bool = False
    oidc_jwks_url: str = ""
    oidc_issuer: str = ""
    oidc_audience: str = ""
    # OIDC claim→tenant 映射（§16 租户映射）：claim 值 / email 域名 / 默认
    oidc_tenant_claim: str = "tenant_id"
    oidc_tenant_email_domains: str = "{}"  # JSON: {"example.com": "tenant-a"}
    oidc_default_tenant: str = ""
    # 审批通知 webhook（§19；空则不发送，仅结构化日志）
    approval_webhook_url: str = ""
    approval_webhook_secret: str = ""  # HMAC 签名（§19 出站防伪）
    # 审批通知通道（逗号分隔：log / email / webhook）
    approval_notify_channels: str = "log"
    approval_email_to: str = ""  # 审批人邮箱（逗号分隔）
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "agent-platform@local"
    # 成本估算单价（美元 / 百万 token），Mock/估算用，账单口径后续对账校正（§50.1）
    llm_price_input_per_mtok: float = 1.0
    llm_price_output_per_mtok: float = 3.0

    # ---- runtime 预算默认值 ----
    budget_max_steps: int = 30
    budget_max_tokens: int = 200_000
    budget_max_cost: float = 10.0
    budget_max_tool_calls: int = 50
    budget_max_runtime_s: int = 600
    budget_max_retries: int = 3
    budget_max_step_s: float = 120.0  # §9.1 分层超时：单步（LLM+工具）上限
    # §16.3 租户并发 run 上限（创建 run 时校验，超限拒绝）
    tenant_max_concurrent_runs: int = 20
    # Phase 1 配额可视化（§66）：超限前可见，Dashboard /quotas 对照展示
    tenant_max_users: int = 100  # 租户用户数上限
    tenant_max_agents: int = 50  # 租户 Agent 数上限
    tenant_max_runs_30d: int = 100_000  # 近 30 天 run 次数上限

    # ---- 队列（§11） ----
    # 队列深度监控采样间隔（秒）；后台定时落库供"队列深度随时间"趋势
    queue_sample_interval_s: int = 60

    # ---- 可观测性 ----
    queue_sample_interval_s: int = 60
    otlp_endpoint: str = ""  # 空 => 不导出（本地打印/日志）
    service_name: str = "agent-platform"

    # ---- 种子身份 ----
    seed_tenant: str = "tenant-default"
    seed_user: str = "user-default"

    # ---- 评测（§20） ----

    # ---- 知识库分区（§24 百万级） ----
    knowledge_shard_count: int = 1  # 租户分区数：hash(tenant)%N，1=不分片
    max_upload_bytes: int = 50 * 1024 * 1024  # §15.7 文件上传总上限（默认 50MB，可按需调大）

    # ---- MCP 网关（§7.3） ----
    mcp_servers: str = "{}"  # JSON: {"server_name": "base_url"}
    # §7.2 MCP 安全：每 server 的工具白名单（JSON {"server_name": ["tool1", ...]}）；缺省注册全部
    mcp_tool_allowlist: str = "{}"
    # §7.2 MCP 输出大小上限（字符，防大 payload 撑爆 Context）
    mcp_max_output_chars: int = 8000

    # ---- Sandbox（§23.4） ----
    sandbox_max_output_bytes: int = 100_000  # 工具输出序列化上限
    sandbox_allowed_ports: str = ""  # 逗号分隔出站端口；空=不限（SSRF 内网拦截仍在）
    sandbox_docker: bool = False  # True=自定义工具跑 Docker 容器（--network none）；False=子进程沙箱（dev）
    sandbox_docker_runtime: str = ""  # 空=Docker 默认 runtime；"runsc"=gVisor（需安装 runsc + daemon 注册）

    # ---- 多区域 HA（MVP 最小切片：实例身份/就绪；复制/容灾超出） ----
    region: str = "default"
    instance_id: str = ""  # 空则启动时生成 uuid

    @model_validator(mode="after")
    def _enforce_production_security(self) -> "Settings":
        """生产安全门禁：prod 环境强制 JWT、拒绝默认签名密钥（对外产品前提）。"""
        if self.environment == "prod":
            if self.auth_jwt_secret in ("", "dev-secret-change-me"):
                raise ValueError("prod 环境必须设置强随机 APP_AUTH_JWT_SECRET，不能使用默认值")
            self.auth_require_jwt = True  # 生产强制认证：关闭无 token 回落 seed 管理员
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
