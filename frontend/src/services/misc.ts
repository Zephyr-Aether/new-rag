import { get, post, put, del } from './http'

import type { AuditRow, CostRow, DataSweep, EventReplayResult, GrowthRow, MemoryEntry } from '../api/types'
export const miscApi = {
// Cost
  costOverview: () => get<{ rows: CostRow[] }>('/cost/overview'),
  costGrowth: () => get<{ rows: GrowthRow[] }>('/cost/growth'),
  costUsage: (days = 30) => get<{ rows: { tenant_id: string; day: string; runs: number; tokens: number; cost: number }[]; days: number }>(`/cost/usage?days=${days}`),
  costQuotas: () =>
    get<{ tenant_id: string; quotas: { key: string; label: string; used: number; limit: number | null; percent: number | null; over: boolean }[] }>('/cost/quotas'),
  reconcile: () => post<{ reconciled: number; runs_updated: number; total_estimated: number; total_actual: number; diff: number }>('/cost/reconcile'),
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
  configVersions: (key: string) =>
    get<{ key: string; versions: { key: string; value: unknown; version: number; created_at?: string }[] }>(
      `/config/${encodeURIComponent(key)}/versions`,
    ),
  flagSet: (body: { key: string; rules?: Record<string, unknown>; enabled?: boolean }) =>
    post<Record<string, unknown>>('/flags', body),
  flagGet: (key: string) => get<{ key: string; enabled: boolean }>(`/flags/${encodeURIComponent(key)}`),
}

