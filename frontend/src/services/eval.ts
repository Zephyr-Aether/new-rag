import { get, post, put } from './http'

import type { EvalCase } from '../api/types'
export const evalApi = {
// Evaluation cases
  evalCases: (kind = 'BADCASES') => get<{ rows: EvalCase[]; total: number }>(`/evaluations/cases?kind=${kind}`),
  addEvalCase: (body: { query: string; kind: string; reason?: string; category?: string; expected?: string[]; expected_tool_calls?: string[]; must_not_call?: string[]; judge_type?: string }) =>
    post<{ case_id: string; dataset_id: string }>('/evaluations/cases', body),
  evalSeed: () => post<{ added: number; updated: number; skipped: number }>('/evaluations/cases/seed'),
  evalSeedConfig: () => get<{ cases: Record<string, unknown>[]; source: string }>('/evaluations/seed-config'),
  evalSeedConfigSet: (cases: Record<string, unknown>[]) =>
    put<{ ok: boolean; count: number }>('/evaluations/seed-config', { cases }),
  regressionRuns: (agentId: string) =>
    get<{ agent_id: string; runs: { id: string; agent_version: number; total: number; passed: number; pass_rate: number; regressed: boolean; delta: number | null; created_at?: string }[] }>(
      `/agents/${agentId}/regression-runs`,
    ),
}
