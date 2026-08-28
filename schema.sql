-- Agent Platform 完整表结构（由 ORM 模型生成，与 alembic 迁移链 head 一致）


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


CREATE TABLE entities (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	aliases_json TEXT NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_entities_tenant_id ON entities (tenant_id);


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


CREATE TABLE evaluation_datasets (
	id VARCHAR(64) NOT NULL, 
	tenant_id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	kind VARCHAR(32) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);
CREATE INDEX ix_evaluation_datasets_tenant_id ON evaluation_datasets (tenant_id);


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


CREATE TABLE tenants (
	id VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL, 
	PRIMARY KEY (id)
);


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

-- ===== 多知识库（§15.5） =====
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

-- ===== 队列深度采样（§11 监控） =====
CREATE TABLE queue_samples (
	id VARCHAR(64) NOT NULL,
	tenant_id VARCHAR(64) DEFAULT '',
	sampled_at DATETIME,
	by_state TEXT DEFAULT '{}',
	total INTEGER DEFAULT 0,
	PRIMARY KEY (id)
);
CREATE INDEX ix_queue_samples_sampled_at ON queue_samples (sampled_at);

-- ===== 知识库分片上传（§15.7） =====
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
CREATE TABLE upload_parts (
	id VARCHAR(32) NOT NULL,
	upload_id VARCHAR(32),
	seq INTEGER,
	data BLOB,
	PRIMARY KEY (id),
	CONSTRAINT uq_upload_part UNIQUE (upload_id, seq)
);
CREATE INDEX ix_upload_parts_upload_id ON upload_parts (upload_id);
