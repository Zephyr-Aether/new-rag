export interface HealthHA {
  instance_id: string
  region: string
  role: string
  ready: boolean
  queue_watermark: number
  queue_drain_ok: boolean
}

export interface Meta {
  ready: boolean
  agent_id: string
  agent_version: number
  tenant_id: string
}

export interface Run {
  run_id: string
  tenant_id: string
  user_id: string
  agent_id: string
  agent_version: number
  session_id: string
  state: string
  answer?: string | null
  input?: string
  started_at?: string
  steps: number
  tokens_in: number
  tokens_out: number
  cost: number
  error?: { code?: string; message?: string } | null
}

export type StreamEvent =
  | { type: 'start'; run_id: string; session_id?: string }
  | { type: 'tool_call'; tool: string; args?: string }
  | { type: 'tool_result'; tool: string; ok: boolean; docs?: string[] }
  | { type: 'token'; text: string }
  | { type: 'answer'; answer: string }
  | { type: 'done'; run_id: string; session_id?: string; state: string; answer?: string }
  | { type: 'error'; message: string }

export interface Step {
  seq: number
  state: string
  created_at?: string
  llm?: {
    model?: string
    tokens_in?: number
    tokens_out?: number
    tool_calls?: { id?: string; name?: string; arguments?: string }[]
  } | null
  tool_calls?: { tool_ref: string; ok?: boolean; latency_ms?: number; data?: unknown }[]
}

export interface RunDetail {
  run: {
    run_id: string
    state: string
    agent_version: number
    cost: number
    tokens_in: number
    tokens_out: number
    output_json?: string | null
    error_json?: string | null
  }
  steps: Step[]
}

export interface CostRow {
  agent_id: string
  agent_version: number
  runs: number
  tokens_in: number
  tokens_out: number
  cost: number
}

export interface GrowthRow {
  tenant_id: string
  current_tokens_per_run: number
  previous_tokens_per_run: number
  ratio?: number | null
  alert: boolean
}

export interface LLMCall {
  model: string
  step_id: string
  tokens_in: number
  tokens_out: number
  cached_input_tokens?: number
  reasoning_tokens?: number
  prompt_tokens?: number
  history_tokens?: number
  tool_tokens?: number
  rag_tokens?: number
  estimated_cost: number
  latency_ms: number
  scheduler_reason?: string
}

export interface RunCost {
  llm_calls: LLMCall[]
  totals: { estimated_cost: number; tokens_in: number; tokens_out: number }
}

export interface Version {
  version: number
  status: string
  system_prompt: string
  model: string
  config: Record<string, unknown>
  release?: Record<string, unknown>
  created_at?: string
}

export interface ReleaseOrder {
  id: string
  order_no: number
  status: 'open' | 'done' | 'terminated'
  created_by: string
  summary: string
  created_at?: string
  ended_at?: string | null
}

export interface ReleaseOrderDetail extends ReleaseOrder {
  records: {
    version: number
    step: string
    operator: string
    summary: string
    ok: boolean
    detail?: string | null
    created_at?: string
  }[]
  snapshot: {
    status: string
    terminated: boolean
    nodes: { code: string; name: string; status: string; config?: Record<string, unknown> }[]
  }
}

export interface ContractCheck {
  agent_id: string
  version: number
  status: 'pass' | 'warn' | 'fail'
  blocked: boolean
  checks: { id: string; name: string; status: string; reason: string }[]
  needs_manual: string[]
}

export interface RegressionCase {
  query: string
  state: string
  ok: boolean
  judge_type?: string
  judge_note?: string
  tool_calls?: string[]
  expected_tool_calls?: string[]
  must_not_call?: string[]
  forbidden_calls?: string[]
}

export interface Regression {
  agent_id: string
  agent_version: number
  total: number
  passed: number
  completed: number
  pass_rate: number
  regressed: boolean
  previous_pass_rate?: number | null
  cases?: RegressionCase[]
}

export interface SecurityEval {
  agent_id: string
  agent_version: number
  total: number
  passed: number
  pass_rate: number
  cases: { query: string; state: string; forbidden_tool_calls: string[]; secret_leaked: boolean; ok: boolean }[]
}

export interface ReleaseMetrics {
  version: number
  release_status: string
  runs: number
  tokens_in: number
  tokens_out: number
  cost: number
  error_rate: number
}

export interface KBHit {
  document_id: string
  section: string
  text: string
  score: number
}

export interface KBSearch {
  hits: KBHit[]
  provenance: string[]
}

export interface KbBase {
  kb_id: string
  name: string
  description: string
  retrieval_config?: { top_k?: number; bm25_top_k?: number; rerank_n?: number }
  doc_count?: number
  created_at?: string
}

export interface ToolDef {
  ref: string
  description: string
  risk_level: string
  permission: string
  input_schema: Record<string, unknown>
}

export interface ToolExec {
  ok: boolean
  data?: unknown
  error?: unknown
  latency_ms: number
  decision?: Record<string, unknown>
}

export interface McpServer {
  name: string
  base_url: string
  allow: string[]
  enabled: boolean
  registered: boolean
  tools: string[]
}

export interface CustomTool {
  ref: string
  description: string
  input_schema: Record<string, unknown>
  code: string
  timeout_s: number
  risk_level: string
  registered: boolean
}

export interface EventRow {
  event_id: string
  event_type: string
  aggregate_id: string
  payload: Record<string, unknown>
  created_at?: string
}

export interface EventPublish {
  event_id: string
  duplicated: boolean
}

export interface JobRow {
  job_id: string
  job_type: string
  state: string
  attempts: number
  max_attempts: number
  error?: string | null
  created_at?: string
}

export interface QueueStats {
  by_state: Record<string, number>
  by_type: Record<string, number>
  trend: { hours_ago: number; count: number }[]
  depth?: { hours_ago: number; count: number }[]
  total: number
}

export interface EventStats {
  by_type: Record<string, number>
  trend: { hours_ago: number; count: number }[]
  total: number
  dedupe_hits: number
  dedupe_events: number
  replay_total: number
  replay_ok: number
  replay_events: number
}
export interface ApprovalRow {
  approval_id: string
  tool_ref: string
  risk_level: string
  requester_id: string
  status: string
  reason?: string
  approver_id?: string | null
  expires_at?: string
  created_at?: string
}

export interface CanaryMetrics {
  runs: number
  error_rate: number
  avg_cost: number
  avg_latency_s: number
  p95_latency_s: number
  tokens_in: number
  tokens_out: number
  tool_success_rate: number | null
  rag_recall: number | null
  llm_429_rate: number
  negative_feedback: number
}

export interface CanaryCheck {
  action: 'stop' | 'continue'
  reasons: string[]
  metrics: CanaryMetrics
  halted: boolean
  rolled_back_to?: number | null
}

export interface AuditRow {
  id: number
  tenant_id: string
  actor_id: string
  action: string
  resource: string
  outcome: string
  created_at?: string
}

export interface EvalCase {
  case_id: string
  dataset_id: string
  query: string
  reason: string
  category: string
  created_at?: string
  expected?: string[]
  expected_tool_calls?: string[]
  must_not_call?: string[]
  answer?: string
  contexts?: string[]
  metadata?: Record<string, unknown>
  judge_type?: string
}

export interface DataSweep {
  deleted_runs: number
  retention_days: number
  audit_days: number
  payload_days: number
}

// ---- Run 高级操作（§60 Replay/Compare、§52 调度决策、§17.3 payload 采样、§20 反馈闭环）----

export interface ReplayOverrides {
  model?: string
  system_prompt?: string
  top_k?: number
}

export interface CompareResult {
  original_run: string
  replay_run: string
  original_answer?: string | null
  replay_answer?: string | null
  diff: { same: boolean; removed?: string; added?: string }
  retrieval: { original_top_k?: number | null; replay_top_k?: number | null; overridden: boolean }
  overrides: { model?: string | null; system_prompt?: string | null }
}

export interface ScheduleDecision {
  model: string
  step_id: string
  scheduler_reason?: string | null
}

export interface ScheduleCompare {
  original_run: string
  replay_run: string
  original_decisions: { model: string; scheduler_reason?: string | null }[]
  replay_decisions: { model: string; scheduler_reason?: string | null }[]
}

export interface TracePayload {
  id: number
  span_name: string
  kind: string
  payload: unknown
}

export interface FeedbackResult {
  feedback: string
  recorded: boolean
  case_id?: string
}

export interface ModelHealthEntry {
  model: string
  status: string
  error_rate: number
  rate_429: number
  latency_p95_ms: number
  traffic_weight: number
}

export interface ModelHealth {
  models: ModelHealthEntry[]
  breaker: string
}

// ---- Memory（§12）----

export interface MemoryEntry {
  memory_id: string
  scope: string
  memory_type: string
  content: string
  source: string
  source_trust: string
  confidence: number
  score?: number
  created_at?: string
}

// ---- Graph 抽取 / 实体合并（§16）----

export interface GraphExtractResult {
  document_id: string
  added: number
  deduped: number
}

export interface EventReplayResult {
  aggregate_id: string
  events: EventRow[]
  total: number
}

export interface AuthToken {
  access_token: string
  token_type: string
  expires_in: number
  tenant_id: string
  user_id: string
  must_change_password?: boolean
}

export interface UserRow {
  id: string
  email: string
  display_name: string
  enabled: boolean
  must_change_password: boolean
  role_ids: string[]
}

export interface ModelConfig {
  provider: string
  model: string
  base_url: string
  is_mock: boolean
  has_key: boolean
  models: { small: string; medium: string; large: string }
}

