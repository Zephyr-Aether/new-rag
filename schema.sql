-- Agent Platform 完整表结构（由 ORM 模型生成，与 alembic 迁移链 head 一致）


-- 运行：一次 Agent 执行，含成本/Token/错误与状态机。
CREATE TABLE agent_runs (
	run_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	agent_version INTEGER NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	budget_json TEXT NOT NULL, 
	cost FLOAT NOT NULL, 
	tokens_in INTEGER NOT NULL, 
	tokens_out INTEGER NOT NULL, 
	model_config TEXT NOT NULL, 
	input_json TEXT NOT NULL, 
	output_json TEXT, 
	error_json TEXT, 
	checkpoint_json TEXT, 
	replay_of VARCHAR(64), 
	version INTEGER NOT NULL, 
	lock_expires_at DATETIME, 
	started_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	finished_at DATETIME, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (run_id), 
	CONSTRAINT uq_run_scope UNIQUE (tenant_id, agent_id, run_id)
);
CREATE INDEX ix_agent_runs_state ON agent_runs (state);
CREATE INDEX ix_agent_runs_tenant_id ON agent_runs (tenant_id);
CREATE INDEX ix_agent_runs_user_id ON agent_runs (user_id);
CREATE INDEX ix_agent_runs_session_id ON agent_runs (session_id);


-- 审批（§19）：PENDING → APPROVED / REJECTED / TIMEOUT(24h)。
CREATE TABLE approvals (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	requester_id VARCHAR(64) NOT NULL, 
	approver_id VARCHAR(64), 
	tool_ref VARCHAR(255) NOT NULL, 
	call_id VARCHAR(64) NOT NULL, 
	risk_level VARCHAR(32) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	reason TEXT NOT NULL, 
	decided_at DATETIME, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_approvals_tenant_id ON approvals (tenant_id);


-- 审计日志（§6.7）：权限决策 / 工具执行 / 数据访问 / 审批，全量强制。
CREATE TABLE audit_logs (
	id INTEGER NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	actor_id VARCHAR(64) NOT NULL, 
	trace_id VARCHAR(64) NOT NULL, 
	action VARCHAR(128) NOT NULL, 
	resource VARCHAR(255) NOT NULL, 
	resource_id VARCHAR(128) NOT NULL, 
	outcome VARCHAR(32) NOT NULL, 
	detail_json TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_audit_logs_trace_id ON audit_logs (trace_id);
CREATE INDEX ix_audit_logs_action ON audit_logs (action);
CREATE INDEX ix_audit_logs_tenant_id ON audit_logs (tenant_id);


-- 块 = 检索最小单元（§15.3）。embedding 以 JSON 存 Text（MVP，生产切 pgvector）。
CREATE TABLE chunks (
	chunk_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	document_id VARCHAR(64) NOT NULL, 
	seq INTEGER NOT NULL, 
	section VARCHAR(255) NOT NULL, 
	source VARCHAR(512) NOT NULL, 
	text TEXT NOT NULL, 
	token_count INTEGER NOT NULL, 
	embedding TEXT NOT NULL, 
	permission VARCHAR(64) NOT NULL, 
	meta_json TEXT NOT NULL, 
	hash VARCHAR(64) NOT NULL, 
	shard INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (chunk_id), 
	CONSTRAINT uq_chunk_seq UNIQUE (tenant_id, document_id, seq)
);
CREATE INDEX ix_chunks_shard ON chunks (shard);
CREATE INDEX ix_chunks_tenant_id ON chunks (tenant_id);
CREATE INDEX ix_chunks_document_id ON chunks (document_id);


-- 配置中心（§30）：版本化配置（只增不改，回滚=切换版本）。
CREATE TABLE configurations (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	scope VARCHAR(32) NOT NULL, 
	scope_id VARCHAR(64) NOT NULL, 
	"key" VARCHAR(255) NOT NULL, 
	value_json TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_config_ver UNIQUE (tenant_id, scope, scope_id, "key", version)
);
CREATE INDEX ix_configurations_tenant_id ON configurations (tenant_id);


-- 文档：入库文档元数据，含清洗/分块状态。
CREATE TABLE documents (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	owner_id VARCHAR(64) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	source_uri VARCHAR(512) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	hash VARCHAR(64) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_documents_tenant_id ON documents (tenant_id);


-- 图谱实体（§16）：规范化名 + 别名集合。
CREATE TABLE entities (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	aliases_json TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_entities_tenant_id ON entities (tenant_id);


-- 评测样例（§20）：query + 期望 + 分类/风险。
CREATE TABLE evaluation_cases (
	id VARCHAR(64) NOT NULL, 
	dataset_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	"query" TEXT NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	expected_json TEXT NOT NULL, 
	category VARCHAR(64) NOT NULL, 
	reason TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_cases_tenant_id ON evaluation_cases (tenant_id);
CREATE INDEX ix_evaluation_cases_dataset_id ON evaluation_cases (dataset_id);


-- 评测集（§20）：Golden/Adversarial/Regression/BadCases。
CREATE TABLE evaluation_datasets (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_datasets_tenant_id ON evaluation_datasets (tenant_id);


-- 事件 Outbox（§28.2）：幂等发布 / 可追踪 / 可重放。
CREATE TABLE events (
	id VARCHAR(64) NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	aggregate_id VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	dedupe_key VARCHAR(128), 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (dedupe_key)
);
CREATE INDEX ix_events_tenant_id ON events (tenant_id);
CREATE INDEX ix_events_event_type ON events (event_type);


-- Feature Flag（§30）：按 tenant/user/percentage 放量，版本化。
CREATE TABLE feature_flags (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	"key" VARCHAR(255) NOT NULL, 
	rules_json TEXT NOT NULL, 
	version INTEGER NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_feature_flags_key ON feature_flags ("key");
CREATE INDEX ix_feature_flags_tenant_id ON feature_flags (tenant_id);


-- 异步任务（§9/§11）：状态机 + 优先级 + 重试 + DLQ。
CREATE TABLE jobs (
	job_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	job_type VARCHAR(64) NOT NULL, 
	payload_json TEXT NOT NULL, 
	priority INTEGER NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	attempts INTEGER NOT NULL, 
	max_attempts INTEGER NOT NULL, 
	error TEXT, 
	dedupe_key VARCHAR(255), 
	lease_until DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	PRIMARY KEY (job_id)
);
CREATE INDEX ix_jobs_tenant_id ON jobs (tenant_id);
CREATE INDEX ix_jobs_dedupe_key ON jobs (dedupe_key);
CREATE INDEX ix_jobs_job_type ON jobs (job_type);


-- 图谱事实（§16）：最小可审计单元，含 provenance + 时间有效性。
CREATE TABLE knowledge_facts (
	fact_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	subject_entity VARCHAR(255) NOT NULL, 
	predicate VARCHAR(255) NOT NULL, 
	object VARCHAR(255) NOT NULL, 
	confidence FLOAT NOT NULL, 
	source_doc VARCHAR(255) NOT NULL, 
	source_chunk VARCHAR(64) NOT NULL, 
	source_version VARCHAR(64) NOT NULL, 
	extracted_by VARCHAR(255) NOT NULL, 
	sources_json TEXT NOT NULL, 
	valid_from DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	valid_to DATETIME, 
	status VARCHAR(16) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (fact_id)
);
CREATE INDEX ix_knowledge_facts_subject_entity ON knowledge_facts (subject_entity);
CREATE INDEX ix_knowledge_facts_tenant_id ON knowledge_facts (tenant_id);


-- LLM 调用成本记录（§50.1）：每次调用一条，随 Run 聚合归因。
CREATE TABLE llm_calls (
	id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	step_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	agent_version INTEGER NOT NULL, 
	model VARCHAR(255) NOT NULL, 
	tokens_in INTEGER NOT NULL, 
	tokens_out INTEGER NOT NULL, 
	cached_input_tokens INTEGER NOT NULL, 
	reasoning_tokens INTEGER NOT NULL, 
	prompt_tokens INTEGER NOT NULL, 
	history_tokens INTEGER NOT NULL, 
	tool_tokens INTEGER NOT NULL, 
	rag_tokens INTEGER NOT NULL, 
	estimated_cost FLOAT NOT NULL, 
	actual_cost FLOAT, 
	latency_ms INTEGER NOT NULL, 
	scheduler_reason TEXT, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_llm_calls_tenant_id ON llm_calls (tenant_id);
CREATE INDEX ix_llm_calls_run_id ON llm_calls (run_id);


-- 记忆（§12）：严格作用域隔离 + TTL + source_trust 分级。
CREATE TABLE memories (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64), 
	scope VARCHAR(32) NOT NULL, 
	memory_type VARCHAR(32) NOT NULL, 
	content TEXT NOT NULL, 
	source VARCHAR(255) NOT NULL, 
	source_trust VARCHAR(16) NOT NULL, 
	confidence FLOAT NOT NULL, 
	ttl_at DATETIME, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	deleted_at DATETIME, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_memories_user_id ON memories (user_id);
CREATE INDEX ix_memories_tenant_id ON memories (tenant_id);


-- 评测回归（§20 飞轮）：每个 Agent 版本对评测集的 pass_rate，供发布门禁对比。
CREATE TABLE regression_runs (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	agent_version INTEGER NOT NULL, 
	dataset_id VARCHAR(64) NOT NULL, 
	total INTEGER NOT NULL, 
	passed INTEGER NOT NULL, 
	completed INTEGER NOT NULL, 
	pass_rate FLOAT NOT NULL, 
	regressed BOOLEAN NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_regression_runs_tenant_id ON regression_runs (tenant_id);
CREATE INDEX ix_regression_runs_agent_id ON regression_runs (agent_id);


-- 会话：多轮对话容器，保留上下文与消息。
CREATE TABLE sessions (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	agent_version INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_sessions_tenant_id ON sessions (tenant_id);


-- 租户：多租户隔离的顶层实体，独立用户/策略/数据。
CREATE TABLE tenants (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);


-- 工具调用：审批与执行记录，含决策、结果与耗时。
CREATE TABLE tool_calls (
	call_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	tool_ref VARCHAR(255) NOT NULL, 
	args_json TEXT NOT NULL, 
	result_json TEXT, 
	status VARCHAR(32) NOT NULL, 
	error_code VARCHAR(64), 
	latency_ms INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (call_id)
);
CREATE INDEX ix_tool_calls_run_id ON tool_calls (run_id);
CREATE INDEX ix_tool_calls_tenant_id ON tool_calls (tenant_id);


-- Trace payload 采样（§17.3）：属性全量、payload 按采样率存储（默认 10%）。
CREATE TABLE trace_payloads (
	id VARCHAR(64) NOT NULL, 
	trace_id VARCHAR(64) NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	span_name VARCHAR(64) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	payload_json TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_trace_payloads_trace_id ON trace_payloads (trace_id);
CREATE INDEX ix_trace_payloads_run_id ON trace_payloads (run_id);


-- 运行步骤：LLM/工具调用轨迹，按 seq 重建执行报告。
CREATE TABLE agent_steps (
	id INTEGER NOT NULL, 
	run_id VARCHAR(64) NOT NULL, 
	seq INTEGER NOT NULL, 
	state VARCHAR(32) NOT NULL, 
	llm_json TEXT NOT NULL, 
	tool_calls_json TEXT NOT NULL, 
	observations_json TEXT NOT NULL, 
	decision VARCHAR(32) NOT NULL, 
	tokens_used INTEGER NOT NULL, 
	cost FLOAT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_step_seq UNIQUE (run_id, seq), 
	FOREIGN KEY(run_id) REFERENCES agent_runs (run_id)
);
CREATE INDEX ix_agent_steps_run_id ON agent_steps (run_id);


-- Agent：租户下的 Agent 实例，版本化发布的载体。
CREATE TABLE agents (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	owner_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	slug VARCHAR(255) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
CREATE INDEX ix_agents_tenant_id ON agents (tenant_id);


-- RBAC/ABAC 策略（§6.2）：effect + action + resource + condition，默认 DENY。
CREATE TABLE policies (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	effect VARCHAR(16) NOT NULL, 
	action VARCHAR(128) NOT NULL, 
	resource VARCHAR(255) NOT NULL, 
	condition_json TEXT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
CREATE INDEX ix_policies_tenant_id ON policies (tenant_id);


-- 用户：登录与多租户归属，密码哈希落库，支持软删除与强制改密。
CREATE TABLE users (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	email VARCHAR(255) NOT NULL,
	display_name VARCHAR(255) NOT NULL,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
	password_hash VARCHAR(255),
	enabled BOOLEAN NOT NULL DEFAULT 1,
	must_change_password BOOLEAN NOT NULL DEFAULT 0,
	isDelete BOOLEAN NOT NULL DEFAULT 0,
	PRIMARY KEY (id),
	CONSTRAINT uq_users_tenant_email UNIQUE (tenant_id, email),
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
CREATE INDEX ix_users_tenant_id ON users (tenant_id);


-- 版本：只增不改，DRAFT→GRAY→ACTIVE，含系统提示词与配置。
CREATE TABLE agent_versions (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	agent_id VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	system_prompt TEXT NOT NULL, 
	model VARCHAR(255) NOT NULL, 
	config_json TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_agent_version UNIQUE (tenant_id, agent_id, version), 
	FOREIGN KEY(agent_id) REFERENCES agents (id)
);
CREATE INDEX ix_agent_versions_agent_id ON agent_versions (agent_id);

-- 知识库（§15.5 多库隔离）：tenant 下可建多个命名知识库，文档/chunk 按 kb_id 归属。
CREATE TABLE knowledge_bases (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64),
	name VARCHAR(128),
	description VARCHAR(512) DEFAULT '',
	retrieval_config TEXT DEFAULT '{}',
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
	updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id)
);
CREATE INDEX ix_knowledge_bases_tenant_id ON knowledge_bases (tenant_id);
-- 文档/分块归属知识库
ALTER TABLE documents ADD COLUMN kb_id VARCHAR(64) DEFAULT 'default';
CREATE INDEX ix_documents_kb_id ON documents (kb_id);
ALTER TABLE chunks ADD COLUMN kb_id VARCHAR(64) DEFAULT 'default';
CREATE INDEX ix_chunks_kb_id ON chunks (kb_id);

-- ===== 记忆语义召回（§12） =====
ALTER TABLE memories ADD COLUMN embedding TEXT DEFAULT '[]';

-- 队列深度采样（§11 监控）：后台定时落库，供"队列深度随时间"趋势。
CREATE TABLE queue_samples (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) DEFAULT '',
	sampled_at DATETIME,
	by_state TEXT DEFAULT '{}',
	total INTEGER DEFAULT 0,
	PRIMARY KEY (id)
);
CREATE INDEX ix_queue_samples_sampled_at ON queue_samples (sampled_at);

-- 分片上传会话（§15.7）：元数据，分片存 upload_parts。
CREATE TABLE upload_sessions (
	id VARCHAR(32) NOT NULL,
	filename VARCHAR(255),
	title VARCHAR(255) DEFAULT '',
	kb_id VARCHAR(64) DEFAULT 'default',
	size INTEGER DEFAULT 0,
	chunk_size INTEGER DEFAULT 1048576,
	total_chunks INTEGER DEFAULT 0,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
	PRIMARY KEY (id)
);
-- 分片上传的分片数据（§15.7）：断点续传按 (upload_id, seq) 去重。
CREATE TABLE upload_parts (
	id VARCHAR(32) NOT NULL,
	upload_id VARCHAR(32),
	seq INTEGER,
	data BLOB,
	PRIMARY KEY (id),
	CONSTRAINT uq_upload_part UNIQUE (upload_id, seq)
);
CREATE INDEX ix_upload_parts_upload_id ON upload_parts (upload_id);


-- 角色（§6.2 RBAC）：角色是一组策略的命名集合，用户通过 user_roles 挂到角色。
CREATE TABLE roles (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	description VARCHAR(512) NOT NULL DEFAULT '', 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(tenant_id) REFERENCES tenants (id)
);
CREATE INDEX ix_roles_tenant_id ON roles (tenant_id);


-- 用户-角色关联（§6.2 RBAC）。
CREATE TABLE user_roles (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	user_id VARCHAR(64) NOT NULL, 
	role_id VARCHAR(64) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_user_role UNIQUE (tenant_id, user_id, role_id)
);
CREATE INDEX ix_user_roles_tenant_id ON user_roles (tenant_id);
CREATE INDEX ix_user_roles_user_id ON user_roles (user_id);
CREATE INDEX ix_user_roles_role_id ON user_roles (role_id);


-- 密钥（§6.5 Secret Reference）：加密落库，ref 唯一；值只以密文持久化。
CREATE TABLE secrets (
	ref VARCHAR(128) NOT NULL, 
	value_encrypted TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (ref)
);


-- API 级幂等（Idempotency-Key）：method:key -> 缓存响应，重放去重（24h TTL）。
CREATE TABLE idempotency (
	key VARCHAR(255) NOT NULL, 
	status_code INTEGER NOT NULL DEFAULT 200, 
	body TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (key)
);


-- 会话消息（§10 对话持久化）：user/assistant + 工具摘要 + 引用来源，按 seq 排序重建多轮上下文。
CREATE TABLE messages (
	id VARCHAR(64) NOT NULL, 
	session_id VARCHAR(64) NOT NULL, 
	role VARCHAR(16) NOT NULL, 
	content TEXT NOT NULL, 
	tools_json TEXT NOT NULL DEFAULT '[]', 
	docs_json TEXT NOT NULL DEFAULT '[]', 
	seq INTEGER NOT NULL DEFAULT 0, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_messages_session_id ON messages (session_id);


-- 发布流程执行历史（留痕）：发布页每步一次执行记录，供复盘。
CREATE TABLE release_flow_history (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	agent_id VARCHAR(64) NOT NULL,
	order_id VARCHAR(64),
	version INTEGER NOT NULL DEFAULT 0,
	step VARCHAR(32) NOT NULL,
	operator VARCHAR(64) NOT NULL DEFAULT '',
	summary VARCHAR(255) NOT NULL DEFAULT '',
	ok BOOLEAN NOT NULL DEFAULT 1,
	detail TEXT,
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
	PRIMARY KEY (id)
);
CREATE INDEX ix_release_flow_history_tenant_id ON release_flow_history (tenant_id);
CREATE INDEX ix_release_flow_history_agent_id ON release_flow_history (agent_id);
CREATE INDEX ix_release_flow_history_order_id ON release_flow_history (order_id);


-- 发布单（§21.5）：一次发布周期的正式记录（单号/状态/创建人/时间/涉及版本 + 节点快照）。
CREATE TABLE release_order (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) NOT NULL,
	agent_id VARCHAR(64) NOT NULL,
	order_no INTEGER NOT NULL DEFAULT 1,
	status VARCHAR(16) NOT NULL DEFAULT 'open',
	created_by VARCHAR(64) NOT NULL DEFAULT '',
	summary VARCHAR(255) NOT NULL DEFAULT '',
	snapshot_json TEXT NOT NULL DEFAULT '{}',
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
	ended_at DATETIME,
	PRIMARY KEY (id),
	CONSTRAINT uq_release_order_no UNIQUE (tenant_id, agent_id, order_no)
);
CREATE INDEX ix_release_order_tenant_id ON release_order (tenant_id);
CREATE INDEX ix_release_order_agent_id ON release_order (agent_id);
