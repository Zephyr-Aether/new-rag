import { get, post, put, del } from './http'

import type { CustomTool, McpServer, ToolDef, ToolExec } from '../api/types'
export const toolsApi = {
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
}
