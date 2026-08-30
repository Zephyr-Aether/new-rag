import { get, post } from './http'

import type { CanaryCheck, ContractCheck, Regression, ReleaseMetrics, ReleaseOrder, ReleaseOrderDetail, SecurityEval, Version } from '../api/types'
export const releaseApi = {
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
  releaseFlowHistory: (agentId: string, step?: string) =>
    get<{ agent_id: string; records: { id: string; version: number; step: string; operator: string; summary: string; ok: boolean; detail?: string | null; created_at?: string }[] }>(
      `/agents/${agentId}/flow-history${step ? `?step=${encodeURIComponent(step)}` : ''}`,
    ),
  releaseFlowRecord: (agentId: string, body: { version: number; step: string; summary: string; ok: boolean; detail?: string }) =>
    post<{ ok: boolean }>(`/agents/${agentId}/flow-history`, body),
  releaseFlow: (agentId: string) =>
    get<{ agent_id: string; status: string; terminated: boolean; current_step: number; nodes: { code: string; name: string; config: Record<string, unknown>; status: string }[] }>(
      `/agents/${agentId}/release-flow`,
    ),
  releaseFlowNode: (agentId: string, nodeCode: string, config: Record<string, unknown>, status?: string) =>
    post<{ ok: boolean }>(`/agents/${agentId}/release-flow/${nodeCode}`, { config, status }),
  releaseFlowTerminate: (agentId: string) =>
    post<{ ok: boolean; terminated: boolean }>(`/agents/${agentId}/release-flow/terminate`),
  releaseFlowStart: (agentId: string) =>
    post<{ agent_id: string; status: string; terminated: boolean; current_step: number; nodes: { code: string; name: string; config: Record<string, unknown>; status: string }[] }>(
      `/agents/${agentId}/release-flow/start`,
    ),
  releaseOrderCreate: (agentId: string) =>
    post<ReleaseOrder & { flow: { status: string; terminated: boolean; nodes: { code: string; name: string; config: Record<string, unknown> }[] } }>(
      `/agents/${agentId}/release-orders`,
    ),
  releaseOrderList: (agentId: string) =>
    get<{ agent_id: string; orders: ReleaseOrder[] }>(`/agents/${agentId}/release-orders`),
  releaseOrderGet: (agentId: string, orderId: string) =>
    get<ReleaseOrderDetail>(`/agents/${agentId}/release-orders/${orderId}`),
}
