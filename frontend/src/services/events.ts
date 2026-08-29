import { get, post } from './http'

import type { ApprovalRow, EventPublish, EventRow, EventStats, JobRow, QueueStats } from '../api/types'
export const eventsApi = {
// Events
  events: (limit = 50) => get<{ rows: EventRow[]; total: number }>(`/events?limit=${limit}`),
  eventsStats: () => get<EventStats>('/events/stats'),
  aggregateState: (aggregateId: string) =>
    get<{ aggregate_id: string; count: number; by_type: Record<string, number>; last_event: { event_id: string; event_type: string; created_at?: string } | null }>(
      `/events/aggregate/${encodeURIComponent(aggregateId)}/state`,
    ),
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
}
