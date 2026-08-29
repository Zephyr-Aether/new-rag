// 类型化 API 客户端：覆盖全部后端模块（底层走 axios 拦截器，见 request.ts）
import { getToken, handleUnauthorized, http, setToken, clearToken } from './request'

export { getToken, setToken, clearToken }

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024 // 与后端 APP_MAX_UPLOAD_BYTES 默认一致（可调大）

const request = <T>(path: string, method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'GET', data?: unknown) =>
  http.request<T>({ url: path, method, data }).then((r) => r.data)

const get = <T>(path: string) => request<T>(path)
const post = <T>(path: string, body?: unknown) => request<T>(path, 'POST', body)
const put = <T>(path: string, body?: unknown) => request<T>(path, 'PUT', body)
const patch = <T>(path: string, body?: unknown) => request<T>(path, 'PATCH', body)
const del = <T>(path: string) => request<T>(path, 'DELETE')

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

async function sha256Hex(s: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('')
}

const api = {
  // 认证（§27 JWT）：密码先 SHA-256 再提交，避免明文传输
  login: async (tenantId: string, userId: string, password = '') => {
    const pwd = password ? await sha256Hex(password) : ''
    const r = await post<AuthToken>('/auth/token', { tenant_id: tenantId, user_id: userId, password: pwd })
    setToken(r.access_token)
    return r
  },
  logout: () => clearToken(),
  authMe: () => get<{ user_id: string; tenant_id: string; roles: string[]; allowed: string[]; denied: string[] }>('/auth/me'),
  changePassword: async (oldRaw: string, newRaw: string) => {
    const r = await post<{ ok: boolean }>('/auth/password', {
      old_password: oldRaw ? await sha256Hex(oldRaw) : '',
      new_password: await sha256Hex(newRaw),
    })
    return r
  },
  users: () => get<{ users: UserRow[] }>('/users'),
  userCreate: async (body: { user_id: string; email?: string; display_name?: string; password?: string; role_ids?: string[] }) =>
    post<{ ok: boolean; id: string }>('/users', {
      ...body,
      password: body.password ? await sha256Hex(body.password) : '',
    }),
  userUpdate: async (id: string, body: { display_name?: string; email?: string; enabled?: boolean; password?: string; role_ids?: string[] }) =>
    put<{ ok: boolean; id: string }>(`/users/${encodeURIComponent(id)}`, {
      ...body,
      password: body.password ? await sha256Hex(body.password) : '',
    }),
  userDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/users/${encodeURIComponent(id)}`),
  tenants: () => get<{ tenants: { id: string; name: string }[] }>('/tenants'),
  tenantCreate: async (body: { tenant_id?: string; name: string; admin_user_id: string; admin_email?: string; admin_password?: string }) =>
    post<{ ok: boolean; tenant_id: string; admin_user_id: string }>('/tenants', {
      ...body,
      admin_password: body.admin_password ? await sha256Hex(body.admin_password) : '',
    }),
  secrets: () => get<{ secrets: { ref: string }[] }>('/secrets'),
  secretSet: (ref: string, value: string) => post<{ ok: boolean; ref: string }>('/secrets', { ref, value }),
  secretDelete: (ref: string) => del<{ ok: boolean; deleted: string }>(`/secrets/${encodeURIComponent(ref)}`),
  roles: () =>
    get<{ roles: { id: string; name: string; description: string; users: string[] }[] }>('/roles'),
  roleCreate: (body: { name: string; description?: string }) => post<{ id: string; name: string }>('/roles', body),
  roleUpdate: (id: string, body: { name?: string; description?: string }) =>
    put<{ ok: boolean; id: string }>(`/roles/${encodeURIComponent(id)}`, body),
  roleDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/roles/${encodeURIComponent(id)}`),
  roleAddUser: (roleId: string, userId: string) =>
    post<{ ok: boolean; role_id: string; user_id: string }>(`/roles/${encodeURIComponent(roleId)}/users`, { user_id: userId }),
  roleRemoveUser: (roleId: string, userId: string) =>
    del<{ ok: boolean }>(`/roles/${encodeURIComponent(roleId)}/users/${encodeURIComponent(userId)}`),
  // 健康 / 元数据
  health: () => get<HealthHA>('/health/ha'),
  meta: () => get<Meta>('/meta'),
  // Runs
  listRuns: (limit = 50, offset = 0, state = '') =>
    get<{ runs: Run[]; total: number }>(`/agents/runs?limit=${limit}&offset=${offset}${state ? `&state=${encodeURIComponent(state)}` : ''}`),
  createRun: (input: string, awaitResult = true, opts: { sessionId?: string; history?: { role: string; content: string }[] } = {}) =>
    post<Run>('/agents/runs', {
      input,
      await_result: awaitResult,
      session_id: opts.sessionId,
      history: opts.history,
    }),
  streamRun: async (
    input: string,
    opts: { sessionId?: string; history?: { role: string; content: string }[] } = {},
    onEvent: (e: StreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<{ run_id: string; state: string }> => {
    // SSE 流式：边执行边推 tool_call / tool_result / answer / done 事件
    const res = await fetch('/agents/runs/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ input, session_id: opts.sessionId, history: opts.history }),
      signal,
    })
    if (!res.ok || !res.body) {
      // 流式走原生 fetch，绕过 axios 拦截器：401 也要触发统一的「登录失效」处理
      if (res.status === 401) handleUnauthorized()
      throw new Error(`流式接口失败: ${res.status}`)
    }
    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let runId = ''
    let state = ''
    try {
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split('\n\n')
        buffer = parts.pop() ?? ''
        for (const chunk of parts) {
          const line = chunk.split('\n').find((l) => l.startsWith('data: '))
          if (!line) continue
          const data = JSON.parse(line.slice(6)) as StreamEvent
          onEvent(data)
          if (data.type === 'done') {
            runId = data.run_id
            state = data.state
          }
        }
      }
    } catch (err) {
      // 用户点停止后 abort：不抛错，静默返回
      if ((err as Error).name === 'AbortError') return { run_id: runId, state }
      throw err
    }
    return { run_id: runId, state }
  },
  sessions: () =>
    get<{ sessions: { id: string; title: string; status: string; message_count: number; last_content: string; created_at?: string }[] }>(
      '/agents/sessions',
    ),
  sessionMessages: (id: string) =>
    get<{ session_id: string; messages: { id: string; role: string; content: string; tools: { tool_ref: string; ok: boolean }[]; docs: string[] }[] }>(
      `/agents/sessions/${encodeURIComponent(id)}/messages`,
    ),
  sessionMessageDelete: (sid: string, mid: string) =>
    del<{ ok: boolean; deleted: string }>(`/agents/sessions/${encodeURIComponent(sid)}/messages/${encodeURIComponent(mid)}`),
  sessionPatch: (id: string, body: { title?: string; status?: string }) =>
    patch<{ ok: boolean; id: string }>(`/agents/sessions/${encodeURIComponent(id)}`, body),
  sessionDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/agents/sessions/${encodeURIComponent(id)}`),
  runDetail: (id: string) => get<RunDetail>(`/agents/runs/${id}`),
  runCost: (id: string) => get<RunCost>(`/agents/runs/${id}/cost`),
  pauseRun: (id: string) => post<{ run_id: string; paused: boolean }>(`/agents/runs/${id}/pause`, {}),
  resumeRun: (id: string) => post<Run>(`/agents/runs/${id}/resume`, {}),
  cancelRun: (id: string) => post<{ run_id: string; cancelled: boolean; message?: string }>(`/agents/runs/${id}/cancel`, {}),
  replayRun: (id: string, overrides: ReplayOverrides = {}) => post<Run>(`/agents/runs/${id}/replay`, overrides),
  compareRun: (id: string, overrides: ReplayOverrides = {}) => post<CompareResult>(`/agents/runs/${id}/compare`, overrides),
  runSchedule: (id: string) => get<{ run_id: string; decisions: ScheduleDecision[] }>(`/agents/runs/${id}/schedule`),
  scheduleCompare: (id: string, overrides: ReplayOverrides = {}) =>
    post<ScheduleCompare>(`/agents/runs/${id}/schedule/compare`, overrides),
  runPayloads: (id: string) =>
    get<{ run_id: string; payloads: TracePayload[]; total: number }>(`/agents/runs/${id}/trace/payloads`),
  runFeedback: (id: string, feedback: 'good' | 'bad', reason = '') =>
    post<FeedbackResult>(`/agents/runs/${id}/feedback`, { feedback, reason }),
  // Model
  modelHealth: () => get<ModelHealth>('/model/health'),
  modelConfig: () => get<ModelConfig>('/model/config'),
  modelConfigSet: (body: { provider: string; model: string; base_url: string; api_key?: string }) =>
    post<{ ok: boolean; provider: string; model: string; base_url: string; is_mock: boolean }>('/model/config', body),
  // Release
  versions: (agentId: string) => get<{ agent_id: string; versions: Version[] }>(`/agents/${agentId}/versions`),
  createVersion: (agentId: string, body: { system_prompt: string; model?: string; config?: Record<string, unknown> }) =>
    post<Version>(`/agents/${agentId}/versions`, body),
  publish: (agentId: string, version: number, force = false, evaluate = false) =>
    post<Record<string, unknown>>(`/agents/${agentId}/versions/${version}/publish`, { force, evaluate }),
  gray: (agentId: string, version: number, percentage: number) =>
    post<Record<string, unknown>>(`/agents/${agentId}/versions/${version}/gray`, { percentage }),
  rollback: (agentId: string, toVersion?: number) =>
    post<Record<string, unknown>>(`/agents/${agentId}/rollback`, { to_version: toVersion ?? null }),
  halt: (agentId: string, version: number) =>
    post<Record<string, unknown>>(`/agents/${agentId}/versions/${version}/halt`),
  contractCheck: (agentId: string, version: number) =>
    post<ContractCheck>(`/agents/${agentId}/versions/${version}/contract-check`),
  regression: (agentId: string, version: number, kind = 'BADCASES') =>
    post<Regression>(`/agents/${agentId}/versions/${version}/regression?kind=${kind}`),
  securityEval: (agentId: string, version: number) =>
    post<SecurityEval>(`/agents/${agentId}/versions/${version}/security-eval`),
  releaseMetrics: (agentId: string) => get<{ agent_id: string; metrics: ReleaseMetrics[] }>(`/agents/${agentId}/release-metrics`),
  canaryCheck: (agentId: string) => post<CanaryCheck>(`/agents/${agentId}/canary/check`, {}),
  canaryEvaluate: (agentId: string) => post<CanaryCheck>(`/agents/${agentId}/canary/evaluate`, {}),
  // Knowledge
  kbBases: () => get<{ bases: KbBase[] }>('/knowledge/bases'),  kbCreate: (name: string, description = '') => post<{ kb_id: string; name: string }>('/knowledge/bases', { name, description }),
  kbRename: (id: string, name: string) => put<{ kb_id: string; name: string }>(`/knowledge/bases/${encodeURIComponent(id)}`, { name }),
  kbConfig: (id: string, config: { top_k?: number; bm25_top_k?: number; rerank_n?: number }) =>
    put<{ kb_id: string; retrieval_config: { top_k?: number; bm25_top_k?: number; rerank_n?: number } }>(
      `/knowledge/bases/${encodeURIComponent(id)}/config`,
      config,
    ),
  kbDelete: (id: string) => del<{ kb_id: string; deleted: boolean }>(`/knowledge/bases/${encodeURIComponent(id)}`),
  ingest: (body: { document_id: string; title: string; text: string; kb_id?: string }) =>
    post<{ document_id: string; chunks: number; status: string }>('/knowledge/documents', body),
  previewClean: (text: string) => post<{ cleaned: string; chunks: number; characters: number }>('/knowledge/preview', { text }),
  uploadInit: (body: { filename: string; size: number; chunk_size?: number; title?: string; kb_id?: string }) =>
    post<{ upload_id: string; chunk_size: number; total_chunks: number }>('/knowledge/upload/init', body),
  uploadChunk: (uploadId: string, index: number, blob: Blob) => {
    const fd = new FormData()
    fd.append('file', blob)
    return http.request<{ upload_id: string; received: number }>({ url: `/knowledge/upload/${uploadId}/chunks/${index}`, method: 'POST', data: fd }).then((r) => r.data)
  },
  uploadStatus: (uploadId: string) =>
    get<{ upload_id: string; uploaded: number[]; total_chunks: number }>(`/knowledge/upload/${uploadId}/status`),
  uploadComplete: (uploadId: string) =>
    post<{ document_id: string; title: string; chunks: number; status: string; kb_id?: string }>(`/knowledge/upload/${uploadId}/complete`),
  uploadDocument: (file: File, title?: string, kbId?: string) => {    const fd = new FormData()
    fd.append('file', file)
    if (title) fd.append('title', title)
    if (kbId) fd.append('kb_id', kbId)
    return http
      .request<{ document_id: string; title: string; chunks: number; status: string; kb_id: string }>({
        url: '/knowledge/documents/upload',
        method: 'POST',
        data: fd,
      })
      .then((r) => r.data)
  },
  search: (query: string, kbId?: string) =>
    post<KBSearch>('/knowledge/search', { query, rerank_n: 5, kb_id: kbId ?? undefined }),
  documents: (kbId?: string) =>
    get<{ rows: { document_id: string; title: string; source_uri: string; status: string; created_at?: string; chunk_count?: number }[]; total: number }>(
      `/knowledge/documents${kbId ? `?kb_id=${encodeURIComponent(kbId)}` : ''}`,
    ),
  documentDetail: (id: string) =>
    get<{ document_id: string; title: string; source_uri: string; status: string; created_at?: string; chunks: { chunk_id: string; seq: number; section: string; text: string; token_count: number }[] }>(
      `/knowledge/documents/${encodeURIComponent(id)}`,
    ),
  deleteDocument: (id: string) => del<{ document_id: string; deleted: boolean }>(`/knowledge/documents/${encodeURIComponent(id)}`),
  // Cost
  costOverview: () => get<{ rows: CostRow[] }>('/cost/overview'),
  costGrowth: () => get<{ rows: GrowthRow[] }>('/cost/growth'),
  costUsage: (days = 30) => get<{ rows: { tenant_id: string; day: string; runs: number; tokens: number; cost: number }[]; days: number }>(`/cost/usage?days=${days}`),
  reconcile: () => post<{ reconciled: number; runs_updated: number; total_estimated: number; total_actual: number; diff: number }>('/cost/reconcile'),
  // Tools
  tools: () => get<{ tools: ToolDef[] }>('/tools'),
  execTool: (ref: string, args: Record<string, unknown>) =>
    post<ToolExec>(`/tools/${ref}/execute`, { args }),
  // MCP 服务器（页面接入）
  mcpServers: () => get<{ servers: McpServer[] }>('/mcp/servers'),
  mcpServersSet: (servers: { name: string; base_url: string; allow?: string[]; enabled?: boolean }[]) =>
    put<{ ok: boolean; count: number; results: Record<string, string> }>('/mcp/servers', { servers }),
  mcpServerDelete: (name: string) => del<{ ok: boolean; deleted: string }>(`/mcp/servers/${encodeURIComponent(name)}`),
  // 自定义工具（沙箱代码）
  customTools: () => get<{ tools: CustomTool[] }>('/custom-tools'),
  customToolsSet: (tools: { ref: string; description?: string; input_schema?: Record<string, unknown>; code: string; timeout_s?: number; risk_level?: string }[]) =>
    put<{ ok: boolean; count: number; results: Record<string, string> }>('/custom-tools', { tools }),
  customToolDelete: (ref: string) => del<{ ok: boolean; deleted: string }>(`/custom-tools/${encodeURIComponent(ref)}`),
  // Events
  events: (limit = 50) => get<{ rows: EventRow[]; total: number }>(`/events?limit=${limit}`),
  eventsStats: () => get<EventStats>('/events/stats'),
  publishEvent: (body: { event_type: string; aggregate_id: string; dedupe_key: string; payload?: Record<string, unknown> }) =>
    post<EventPublish>('/events/publish', body),
  replayEvents: (aggregateId: string) =>
    post<{ aggregate_id: string; events: EventRow[]; total: number }>(
      `/events/replay/${encodeURIComponent(aggregateId)}`,
      {},
    ),
  // Queue
  jobs: (state = '') => get<{ rows: JobRow[]; total: number }>(`/queue/jobs${state ? `?state=${state}` : ''}`),
  queueStats: () => get<QueueStats>('/queue/stats'),
  queueJob: (id: string) => get<Record<string, unknown>>(`/queue/jobs/${encodeURIComponent(id)}`),
  requeue: (jobId: string) => post<{ job_id: string; state: string }>(`/queue/jobs/${jobId}/requeue`, {}),
  cancelJob: (jobId: string) => post<{ job_id: string; state: string }>(`/queue/jobs/${jobId}/cancel`, {}),
  expireJobs: () => post<{ expired: string[]; count: number }>('/queue/jobs/expire', {}),
  queueSample: () => post<{ ok: boolean; total: number }>('/queue/sample', {}),
  // Approvals
  approvals: (status = '') =>
    get<{ rows: ApprovalRow[]; total: number }>(`/approvals${status ? `?status=${status}` : ''}`),
  approval: (id: string) => get<ApprovalRow>(`/approvals/${encodeURIComponent(id)}`),
  approve: (id: string) => post<Record<string, unknown>>(`/approvals/${id}/approve`, {}),
  reject: (id: string) => post<Record<string, unknown>>(`/approvals/${id}/reject`, {}),
  // 权限策略（§6.2 AOP）
  policies: () =>
    get<{ policies: { id: string; user_id: string | null; role_id: string | null; name: string; effect: string; action: string; resource: string; enabled: boolean }[] }>('/policies'),
  policyMeta: () =>
    get<{ actions: { action: string; name: string }[]; resources: { resource: string; name: string | null }[] }>(
      '/policies/meta',
    ),
  policyCreate: (body: { action: string; resource?: string; effect?: string; user_id?: string; role_id?: string; name?: string }) =>
    post<{ ok: boolean }>('/policies', body),
  policyUpdate: (id: string, body: { action: string; resource?: string; effect?: string; user_id?: string; role_id?: string; name?: string }) =>
    put<{ ok: boolean; id: string }>(`/policies/${encodeURIComponent(id)}`, body),
  policyDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/policies/${encodeURIComponent(id)}`),
  // Audit
  audit: (limit = 100) => get<{ rows: AuditRow[]; total: number }>(`/audit?limit=${limit}`),
  // Data lifecycle
  dataSweep: (retention = 30, auditDays?: number, payloadDays?: number) =>
    post<DataSweep>(`/data/sweep?retention_days=${retention}${auditDays ? `&audit_days=${auditDays}` : ''}${payloadDays ? `&payload_days=${payloadDays}` : ''}`, {}),
  purgeTenant: (tenantId: string) => post<Record<string, unknown>>(`/data/tenant/${tenantId}/purge`, {}),
  // Evaluation cases
  evalCases: (kind = 'BADCASES') => get<{ rows: EvalCase[]; total: number }>(`/evaluations/cases?kind=${kind}`),
  addEvalCase: (body: { query: string; kind: string; reason?: string; category?: string; expected?: string[]; expected_tool_calls?: string[]; must_not_call?: string[]; judge_type?: string }) =>
    post<{ case_id: string; dataset_id: string }>('/evaluations/cases', body),
  evalSeed: () => post<{ added: number; updated: number; skipped: number }>('/evaluations/cases/seed'),
  evalSeedConfig: () => get<{ cases: Record<string, unknown>[]; source: string }>('/evaluations/seed-config'),
  evalSeedConfigSet: (cases: Record<string, unknown>[]) =>
    put<{ ok: boolean; count: number }>('/evaluations/seed-config', { cases }),
  // Graph
  graphQuery: (query: string) => post<{ facts: { subject: string; predicate: string; object: string; confidence?: number; status?: string }[] }>('/graph/query', { query }),
  graphEntity: (name: string) =>
    get<{ entity: string; canonical: string | null; facts: { subject: string; predicate: string; object: string; confidence?: number; status?: string }[] }>(
      `/graph/entity/${encodeURIComponent(name)}`,
    ),
  addGraphFact: (body: { subject: string; predicate: string; object: string }) =>
    post<{ fact_id: string }>('/graph/facts', body),
  graphExtract: (body: { document_id: string; text: string }) =>
    post<{ document_id: string; added: number; facts: unknown[] }>('/graph/extract', body),
  graphMerge: (name: string, into: string) =>
    post<Record<string, unknown>>(`/graph/entities/${encodeURIComponent(name)}/merge`, { into }),
  // Memory
  writeMemory: (body: {
    content: string
    scope?: string
    memory_type?: string
    source?: string
    source_trust?: string
    ttl_days?: number
  }) => post<{ memory_id: string }>('/memory', body),
  recallMemory: (query = '', k = 20) => post<{ entries: MemoryEntry[] }>('/memory/recall', { query, k }),
  deleteMemory: (id: string) => del<{ memory_id: string; deleted: boolean }>(`/memory/${id}`),
  // Events 聚合重放（§28.2）
  replayAggregate: (aggregateId: string) => post<EventReplayResult>(`/events/replay/${encodeURIComponent(aggregateId)}`, {}),
  // Config center / Feature flags
  configGet: (key: string) => get<{ key: string; value: unknown; version: number | null }>(`/config?key=${encodeURIComponent(key)}`),
  configSet: (body: { key: string; value: unknown }) => post<{ key: string; version: number }>('/config', body),
  configVersionGet: (key: string, version: number) =>
    get<{ key: string; value: unknown; version: number | null }>(
      `/config/${encodeURIComponent(key)}/versions/${version}`,
    ),
  flagSet: (body: { key: string; rules?: Record<string, unknown>; enabled?: boolean }) =>
    post<Record<string, unknown>>('/flags', body),
  flagGet: (key: string) => get<{ key: string; enabled: boolean }>(`/flags/${encodeURIComponent(key)}`),
}

export { api }
