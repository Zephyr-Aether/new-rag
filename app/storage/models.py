"""ORM 模型（对应 §8.3 核心表的 MVP 子集）。

MVP 取舍：cost 用 Float（账单口径对账后置）；JSON 用 Text + json.dumps 简化迁移；
生产切 PG 后逐步迁移到 JSONB / Numeric(12,4)（§8 已给出目标 DDL）。
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ---------------- Identity ----------------
class TenantRow(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), default="")
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)  # §27 pbkdf2(sha256(pwd))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # 禁用后拒绝签发 token
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)  # 首次登录/重置后强制改密
    isDelete: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")  # 软删除：1=已删除，删除写改此字段
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PolicyRow(Base):
    """RBAC/ABAC 策略（§6.2）：effect + action + resource + condition，默认 DENY。"""

    __tablename__ = "policies"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # NULL=租户/角色级
    role_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 非空=该角色下的策略
    name: Mapped[str] = mapped_column(String(255))
    effect: Mapped[str] = mapped_column(String(16))  # ALLOW / DENY
    action: Mapped[str] = mapped_column(String(128))  # 如 "tool:execute" / "*"
    resource: Mapped[str] = mapped_column(String(255))  # 如 "calc.add" / "*"
    condition_json: Mapped[str] = mapped_column(Text, default="{}")  # ABAC 条件（Phase 后启用）
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RoleRow(Base):
    """角色（§6.2 RBAC）：角色是一组策略的命名集合，用户通过 user_roles 挂到角色。"""

    __tablename__ = "roles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRoleRow(Base):
    """用户-角色关联（§6.2 RBAC）。"""

    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_role"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    role_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SecretRow(Base):
    """密钥（§6.5 Secret Reference）：加密落库，ref 唯一；值只以密文持久化。"""

    __tablename__ = "secrets"

    ref: Mapped[str] = mapped_column(String(128), primary_key=True)
    value_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IdempotencyRow(Base):
    """API 级幂等（Idempotency-Key）：method:key -> 缓存响应，重放去重（24h TTL）。"""

    __tablename__ = "idempotency"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    status_code: Mapped[int] = mapped_column(Integer, default=200)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLogRow(Base):
    """审计日志（§6.7）：权限决策 / 工具执行 / 数据访问 / 审批，全量强制。"""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    actor_id: Mapped[str] = mapped_column(String(64), default="")
    trace_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    resource: Mapped[str] = mapped_column(String(255), default="")
    resource_id: Mapped[str] = mapped_column(String(128), default="")
    outcome: Mapped[str] = mapped_column(String(32))  # ALLOWED/DENIED/SUCCEEDED/FAILED/RATE_LIMITED...
    detail_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Knowledge（§8.3.3 MVP 子集） ----------------
class KnowledgeBaseRow(Base):
    """知识库（§15.5 多库隔离）：tenant 下可建多个命名知识库，文档/chunk 按 kb_id 归属。"""

    __tablename__ = "knowledge_bases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    retrieval_config: Mapped[str] = mapped_column(
        Text, default="{}"
    )  # 库级检索参数（JSON：top_k/bm25_top_k/rerank_n）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DocumentRow(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    kb_id: Mapped[str] = mapped_column(String(64), default="default", index=True)  # §15.5 归属知识库
    owner_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(255))
    source_uri: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING/READY/FAILED
    hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChunkRow(Base):
    """块 = 检索最小单元（§15.3）。embedding 以 JSON 存 Text（MVP，生产切 pgvector）。"""

    __tablename__ = "chunks"
    __table_args__ = (UniqueConstraint("tenant_id", "document_id", "seq", name="uq_chunk_seq"),)

    chunk_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    kb_id: Mapped[str] = mapped_column(String(64), default="default", index=True)  # §15.5 归属知识库
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(255), default="")
    source: Mapped[str] = mapped_column(String(512), default="")
    text: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[float]
    permission: Mapped[str] = mapped_column(String(64), default="")
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    hash: Mapped[str] = mapped_column(String(64), default="")
    shard: Mapped[int] = mapped_column(Integer, default=0, index=True)  # §24 租户分区（hash(tenant)%N）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryRow(Base):
    """记忆（§12）：严格作用域隔离 + TTL + source_trust 分级。"""

    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=True)
    scope: Mapped[str] = mapped_column(String(32), default="USER")  # USER/AGENT/TENANT
    memory_type: Mapped[str] = mapped_column(String(32), default="SEMANTIC")
    content: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(255), default="")
    source_trust: Mapped[str] = mapped_column(String(16), default="trusted")  # trusted/untrusted（§12.3）
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    embedding: Mapped[str] = mapped_column(Text, default="[]")  # 语义召回向量（JSON list[float]，MVP）
    ttl_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class JobRow(Base):
    """异步任务（§9/§11）：状态机 + 优先级 + 重试 + DLQ。"""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    job_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 0=最高
    state: Mapped[str] = mapped_column(String(32), default="CREATED")  # §9.2 状态机
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # §11 单飞
    lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # §55 租约（Zombie 检测）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class QueueSampleRow(Base):
    """队列深度采样（§11 监控）：后台定时落库，供"队列深度随时间"趋势。"""

    __tablename__ = "queue_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="")
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    by_state: Mapped[str] = mapped_column(Text, default="{}")  # JSON: 各状态计数
    total: Mapped[int] = mapped_column(Integer, default=0)


class UploadSessionRow(Base):
    """分片上传会话（§15.7）：元数据，分片存 upload_parts。"""

    __tablename__ = "upload_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), default="")  # §15.7 跨租户隔离
    filename: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255), default="")
    kb_id: Mapped[str] = mapped_column(String(64), default="default")
    size: Mapped[int] = mapped_column(Integer, default=0)
    chunk_size: Mapped[int] = mapped_column(Integer, default=1024 * 1024)
    total_chunks: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UploadPartRow(Base):
    """分片上传的分片数据（§15.7）：断点续传按 (upload_id, seq) 去重。"""

    __tablename__ = "upload_parts"
    __table_args__ = (UniqueConstraint("upload_id", "seq", name="uq_upload_part"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    upload_id: Mapped[str] = mapped_column(String(32), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class ApprovalRow(Base):
    """审批（§19）：PENDING → APPROVED / REJECTED / TIMEOUT(24h)。"""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    requester_id: Mapped[str] = mapped_column(String(64), default="")
    approver_id: Mapped[str] = mapped_column(String(64), nullable=True)
    tool_ref: Mapped[str] = mapped_column(String(255), default="")
    call_id: Mapped[str] = mapped_column(String(64), default="")
    risk_level: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # PENDING/APPROVED/REJECTED/TIMEOUT
    reason: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityRow(Base):
    """图谱实体（§16）：规范化名 + 别名集合。"""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))  # 规范化实体名
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")  # JSON list[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeFactRow(Base):
    """图谱事实（§16）：最小可审计单元，含 provenance + 时间有效性。"""

    __tablename__ = "knowledge_facts"

    fact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    subject_entity: Mapped[str] = mapped_column(String(255), index=True)  # 规范化实体
    predicate: Mapped[str] = mapped_column(String(255))
    object: Mapped[str] = mapped_column(String(255))
    confidence: Mapped[float] = mapped_column(Float, default=0.9)
    source_doc: Mapped[str] = mapped_column(String(255), default="")
    source_chunk: Mapped[str] = mapped_column(String(64), default="")
    source_version: Mapped[str] = mapped_column(String(64), default="")
    extracted_by: Mapped[str] = mapped_column(String(255), default="")
    sources_json: Mapped[str] = mapped_column(Text, default="[]")  # §16 跨文档多源保留
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")  # ACTIVE/SUPERSEDED
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Agent ----------------
class AgentRow(Base):
    __tablename__ = "agents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), ForeignKey("tenants.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentVersionRow(Base):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_id", "version", name="uq_agent_version"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(64), ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT")  # DRAFT/ACTIVE/GRAY/DISABLED
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    config_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    agent_id: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    title: Mapped[str] = mapped_column(String(255), default="")  # 会话标题（首条用户消息截断）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MessageRow(Base):
    """会话消息（§10 对话持久化）：user/assistant + 工具摘要 + 引用来源，按 seq 排序重建多轮上下文。"""

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    tools_json: Mapped[str] = mapped_column(Text, default="[]")  # [{"tool_ref","ok"}]
    docs_json: Mapped[str] = mapped_column(Text, default="[]")  # 引用来源 document_id 列表
    seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ---------------- Run ----------------
class AgentRunRow(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (UniqueConstraint("tenant_id", "agent_id", "run_id", name="uq_run_scope"),)

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64))
    agent_version: Mapped[int] = mapped_column(Integer)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(32), index=True)
    budget_json: Mapped[str] = mapped_column(Text, default="{}")
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    model_config: Mapped[str] = mapped_column(Text, default="{}")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, nullable=True)
    error_json: Mapped[str] = mapped_column(Text, nullable=True)
    checkpoint_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # §8 检查点：messages + 预算快照
    replay_of: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )  # §60 Replay：此 run 是哪个 run 的重放
    version: Mapped[int] = mapped_column(Integer, default=1)  # §3.3 乐观锁 CAS 版本号
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AgentStepRow(Base):
    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="uq_step_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("agent_runs.run_id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(32))
    llm_json: Mapped[str] = mapped_column(Text, default="{}")
    tool_calls_json: Mapped[str] = mapped_column(Text, default="[]")
    observations_json: Mapped[str] = mapped_column(Text, default="[]")
    decision: Mapped[str] = mapped_column(String(32), default="")
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    call_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # 幂等键（§4.7）
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    tool_ref: Mapped[str] = mapped_column(String(255))
    args_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING")  # SUCCEEDED/FAILED/...
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LLMCallRow(Base):
    """LLM 调用成本记录（§50.1）：每次调用一条，随 Run 聚合归因。"""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    step_id: Mapped[str] = mapped_column(String(64), default="")
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64), default="")
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    agent_version: Mapped[int] = mapped_column(Integer, default=0)
    model: Mapped[str] = mapped_column(String(255), default="")
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, default=0)
    # §H.1 CostBreakdown 分项：prompt/system / history / tool / rag 各占输入 tokens
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    history_tokens: Mapped[int] = mapped_column(Integer, default=0)
    tool_tokens: Mapped[int] = mapped_column(Integer, default=0)
    rag_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)  # 账单口径（对账后补）
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    scheduler_reason: Mapped[str | None] = mapped_column(Text, nullable=True)  # §52 调度决策（Replay 对比）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfigurationRow(Base):
    """配置中心（§30）：版本化配置（只增不改，回滚=切换版本）。"""

    __tablename__ = "configurations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "scope_id", "key", "version", name="uq_config_ver"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(32), default="GLOBAL")  # GLOBAL/AGENT/TOOL
    scope_id: Mapped[str] = mapped_column(String(64), default="")
    key: Mapped[str] = mapped_column(String(255))
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeatureFlagRow(Base):
    """Feature Flag（§30）：按 tenant/user/percentage 放量，版本化。"""

    __tablename__ = "feature_flags"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    key: Mapped[str] = mapped_column(String(255), index=True)
    rules_json: Mapped[str] = mapped_column(Text, default="{}")  # {percentage, tenants[], users[]}
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EvaluationDatasetRow(Base):
    """评测集（§20）：Golden/Adversarial/Regression/BadCases。"""

    __tablename__ = "evaluation_datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32), default="GOLDEN")  # GOLDEN/ADVERSARIAL/REGRESSION/BADCASES
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvaluationCaseRow(Base):
    """评测样例（§20）：query + 期望 + 分类/风险。"""

    __tablename__ = "evaluation_cases"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    query: Mapped[str] = mapped_column(Text)
    run_id: Mapped[str] = mapped_column(String(64), default="")
    expected_json: Mapped[str] = mapped_column(Text, default="{}")
    category: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RegressionRunRow(Base):
    """评测回归（§20 飞轮）：每个 Agent 版本对评测集的 pass_rate，供发布门禁对比。"""

    __tablename__ = "regression_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    agent_version: Mapped[int] = mapped_column(Integer)
    dataset_id: Mapped[str] = mapped_column(String(64), default="")
    total: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    pass_rate: Mapped[float] = mapped_column(Float, default=0.0)
    regressed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TracePayloadRow(Base):
    """Trace payload 采样（§17.3）：属性全量、payload 按采样率存储（默认 10%）。"""

    __tablename__ = "trace_payloads"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    span_name: Mapped[str] = mapped_column(String(64), default="")
    kind: Mapped[str] = mapped_column(String(32), default="llm")  # llm/tool/output/retrieval
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventRow(Base):
    """事件 Outbox（§28.2）：幂等发布 / 可追踪 / 可重放。"""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(64), default="")  # 关联对象（run_id 等）
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    dedupe_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)  # 幂等
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
