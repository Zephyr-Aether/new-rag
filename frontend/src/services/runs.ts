import { get, post, patch, del, getToken, handleUnauthorized } from './http'

import type { CompareResult, FeedbackResult, ModelConfig, ModelHealth, ReplayOverrides, Run, RunCost, RunDetail, ScheduleCompare, ScheduleDecision, StreamEvent, TracePayload } from '../api/types'
export const runsApi = {
// Runs
  listRuns: (limit = 50, offset = 0, state = '') =>
    get<{ runs: Run[]; total: number }>(`/agents/runs?limit=${limit}&offset=${offset}${state ? `&state=${encodeURIComponent(state)}` : ''}`),
  createRun: (input: string, awaitResult = true, opts: { sessionId?: string; history?: { role: string; content: string }[]; clientRunId?: string } = {}) =>
    post<Run>('/agents/runs', {
      input,
      await_result: awaitResult,
      session_id: opts.sessionId,
      history: opts.history,
      client_run_id: opts.clientRunId,
    }),
  streamRun: async (
    input: string,
    opts: { sessionId?: string; history?: { role: string; content: string }[]; clientRunId?: string } = {},
    onEvent: (e: StreamEvent) => void,
    signal?: AbortSignal,
  ): Promise<{ run_id: string; state: string }> => {
    // SSE 流式：边执行边推 tool_call / tool_result / answer / done 事件
    const res = await fetch('/agents/runs/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${getToken()}` },
      body: JSON.stringify({ input, session_id: opts.sessionId, history: opts.history, client_run_id: opts.clientRunId }),
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
          let data: StreamEvent
          try {
            data = JSON.parse(line.slice(6)) as StreamEvent
          } catch {
            continue // 忽略脏数据行，不让单条坏 JSON 中断整条流
          }
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
    get<{ session_id: string; messages: { id: string; role: string; content: string; state?: string; tools: { tool_ref: string; ok: boolean }[]; docs: string[] }[] }>(
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
}
