import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { api, CustomTool, McpServer } from '@/services'
import { Badge, Button, Card, ErrorBox, Field, Stat, stateLabel, TableSkeleton } from '@/components'
import { EmptyState, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import ToolDetail, { ExecResult } from './components/ToolDetail'
import McpDrawer from './components/McpDrawer'
import CustomToolDrawer from './components/CustomToolDrawer'
import { toast } from '@/toast'

type CatalogSource = '内置' | 'MCP' | '自定义'

interface CatalogTool {
  ref: string
  description: string
  risk_level: string
  permission: string
  input_schema?: Record<string, unknown>
  source: CatalogSource
}

const RISK_FILTERS = [
  { value: '', label: '全部风险' },
  { value: 'READ', label: '只读' },
  { value: 'LOW_RISK_WRITE', label: '低风险写' },
  { value: 'HIGH_RISK_WRITE', label: '高风险写' },
  { value: 'CRITICAL', label: '关键' },
]
const SOURCE_FILTERS = [
  { value: '', label: '全部来源' },
  { value: '内置', label: '内置' },
  { value: 'MCP', label: 'MCP' },
  { value: '自定义', label: '自定义' },
]

function riskBadge(r: string) {
  return r === 'READ' ? 'PASS' : r === 'LOW_RISK_WRITE' ? 'WARN' : 'FAIL'
}

function defaultArgsFor(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema?.properties ?? {}) as Record<string, { type?: string; default?: unknown; enum?: unknown[] }>
  const required = (schema?.required ?? []) as string[]
  const args: Record<string, unknown> = {}
  for (const [k, p] of Object.entries(props)) {
    if (p && p.default !== undefined) args[k] = p.default
    else if (required.includes(k)) {
      if (p && Array.isArray(p.enum) && p.enum.length) args[k] = p.enum[0]
      else if (p?.type === 'integer' || p?.type === 'number') args[k] = 0
      else if (p?.type === 'boolean') args[k] = true
      else if (p?.type === 'array') args[k] = []
      else if (p?.type === 'object') args[k] = {}
      else args[k] = ''
    }
  }
  return args
}

function sampleArgsFor(schema: Record<string, unknown>): Record<string, unknown> {
  const props = (schema?.properties ?? {}) as Record<string, { type?: string; enum?: unknown[] }>
  const args: Record<string, unknown> = {}
  for (const [k, p] of Object.entries(props)) {
    if (p && Array.isArray(p.enum) && p.enum.length) args[k] = p.enum[0]
    else if (p?.type === 'integer' || p?.type === 'number') args[k] = 42
    else if (p?.type === 'boolean') args[k] = true
    else if (p?.type === 'array') args[k] = []
    else if (p?.type === 'object') args[k] = {}
    else args[k] = '示例'
  }
  return args
}

export default function Tools() {
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, error, refresh } = useRequest(() => Promise.all([api.tools(), api.mcpServers(), api.customTools()]))

  const builtIn = data?.[0].tools ?? []
  const mcpLoaded = data?.[1].servers ?? []
  const customLoaded = data?.[2].tools ?? []

  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [customTools, setCustomTools] = useState<CustomTool[] | null>(null)
  const [mcpBusy, setMcpBusy] = useState(false)
  const [customBusy, setCustomBusy] = useState(false)
  const [lastMcpSync, setLastMcpSync] = useState('')

  const [sel, setSel] = useState('')
  const [toolQuery, setToolQuery] = useState('')
  const [riskFilter, setRiskFilter] = useState('')
  const [sourceFilter, setSourceFilter] = useState('')
  const [args, setArgs] = useState('{}')
  const [exec, setExec] = useState<ExecResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [mcpOpen, setMcpOpen] = useState(false)
  const [customOpen, setCustomOpen] = useState(false)

  useEffect(() => {
    setServers(mcpLoaded)
    setCustomTools(customLoaded)
  }, [customLoaded, mcpLoaded])

  const catalog = useMemo<CatalogTool[]>(() => {
    const bi = builtIn.map((t) => ({ ref: t.ref, description: t.description, risk_level: t.risk_level, permission: t.permission, input_schema: t.input_schema, source: '内置' as CatalogSource }))
    const cu = (customTools ?? []).map((t) => ({ ref: t.ref, description: t.description, risk_level: t.risk_level, permission: '', input_schema: t.input_schema, source: '自定义' as CatalogSource }))
    const mc = (servers ?? []).flatMap((s) => (s.tools ?? []).map((ref) => ({ ref, description: `来自 MCP：${s.name}`, risk_level: 'READ', permission: '', input_schema: undefined, source: 'MCP' as CatalogSource })))
    return [...bi, ...cu, ...mc]
  }, [builtIn, customTools, servers])

  useEffect(() => {
    if (catalog.length && (!sel || !catalog.some((t) => t.ref === sel))) {
      selectTool(catalog[0].ref)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [catalog])

  const filteredCatalog = useMemo(() => {
    const q = toolQuery.trim().toLowerCase()
    return catalog.filter((t) => {
      if (q && !`${t.ref} ${t.description} ${t.permission}`.toLowerCase().includes(q)) return false
      if (riskFilter && t.risk_level !== riskFilter) return false
      if (sourceFilter && t.source !== sourceFilter) return false
      return true
    })
  }, [catalog, toolQuery, riskFilter, sourceFilter])

  const selectedTool = catalog.find((t) => t.ref === sel) ?? null

  function selectTool(ref: string) {
    setSel(ref)
    const t = catalog.find((x) => x.ref === ref)
    setArgs(JSON.stringify(defaultArgsFor(t?.input_schema ?? {}), null, 2))
    setExec(null)
  }

  function fillSample() {
    if (!selectedTool?.input_schema) return
    setArgs(JSON.stringify(sampleArgsFor(selectedTool.input_schema), null, 2))
  }
  function resetArgs() {
    if (!selectedTool?.input_schema) return
    setArgs(JSON.stringify(defaultArgsFor(selectedTool.input_schema), null, 2))
  }
  function copyArgs() {
    navigator.clipboard?.writeText(args)
  }

  async function run() {
    if (!sel) return
    setBusy(true)
    setExec(null)
    try {
      let parsed: Record<string, unknown> = {}
      try {
        parsed = JSON.parse(args || '{}')
      } catch {
        throw new Error('参数不是合法 JSON')
      }
      setExec(await api.execTool(sel, parsed))
    } catch (e) {
      setExec({ ok: false, error: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  // MCP
  function addServer(name: string, url: string, allow: string) {
    const list = allow.split(',').map((s) => s.trim()).filter(Boolean)
    setServers((prev) => [...(prev ?? []), { name, base_url: url, allow: list, enabled: true, registered: false, tools: [] }])
  }
  function toggleServer(name: string) {
    setServers((prev) => (prev ?? []).map((s) => (s.name === name ? { ...s, enabled: !s.enabled } : s)))
  }
  function removeServer(name: string) {
    setServers((prev) => (prev ?? []).filter((s) => s.name !== name))
  }
  async function saveMcp() {
    setMcpBusy(true)
    try {
      const list = (servers ?? []).map((s) => ({ name: s.name, base_url: s.base_url, allow: s.allow, enabled: s.enabled }))
      const r = await api.mcpServersSet(list)
      const details = Object.entries(r.results || {}).map(([k, v]) => `${k}: ${v}`).join('；')
      toast(`已保存 ${r.count} 个 server${details ? `（${details}）` : ''}`)
      setLastMcpSync(new Date().toLocaleTimeString())
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setMcpBusy(false)
    }
  }

  // 自定义工具
  async function saveCustom(body: { ref: string; description: string; timeout_s: number; risk_level: string; input_schema: Record<string, unknown>; code: string }) {
    if (!body.ref.trim() || !body.code.trim()) return
    setCustomBusy(true)
    try {
      const base = (customTools ?? []).filter((t) => t.ref !== body.ref.trim())
      const list = [
        ...base.map((t) => ({ ref: t.ref, description: t.description, input_schema: t.input_schema, code: t.code, timeout_s: t.timeout_s, risk_level: t.risk_level })),
        { ref: body.ref.trim(), description: body.description.trim(), input_schema: body.input_schema, code: body.code, timeout_s: body.timeout_s, risk_level: body.risk_level },
      ]
      const r = await api.customToolsSet(list)
      const details = Object.entries(r.results || {}).map(([k, v]) => `${k}: ${v}`).join('；')
      toast(`已保存 ${r.count} 个工具${details ? `（${details}）` : ''}`)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setCustomBusy(false)
    }
  }
  async function deleteCustom(ref: string) {
    setCustomBusy(true)
    try {
      const list = (customTools ?? []).filter((t) => t.ref !== ref).map((t) => ({ ref: t.ref, description: t.description, input_schema: t.input_schema, code: t.code, timeout_s: t.timeout_s, risk_level: t.risk_level }))
      await api.customToolsSet(list)
      toast(`已删除 ${ref}`)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setCustomBusy(false)
    }
  }

  const registeredMcp = (servers ?? []).filter((s) => s.registered).length
  const activeMcp = (servers ?? []).filter((s) => s.enabled).length
  const registeredCustom = (customTools ?? []).filter((t) => t.registered).length
  const highRiskCount = builtIn.filter((t) => t.risk_level === 'HIGH_RISK_WRITE' || t.risk_level === 'CRITICAL').length

  return (
    <div className="tools-page">
      {confirmEl}
      {error && <ErrorBox message={(error as Error).message} />}

      <PageHeader
        title="工具"
        desc="能用什么、怎么用、要不要审批，都在这。先选一个工具，再决定怎么接入和试跑。"
        actions={
          <div className="tools-page-actions">
            <Button onClick={() => setMcpOpen(true)}>接入 MCP</Button>
            <Button onClick={() => setCustomOpen(true)}>新建自定义工具</Button>
            <Button asChild>
              <Link to="/evaluation">去评测</Link>
            </Button>
            <Button tone="primary" asChild>
              <Link to="/release">看发布链路</Link>
            </Button>
          </div>
        }
      />

      <div className="grid cols-4">
        <Stat label="内置工具" value={builtIn.length} sub="平台开箱能力" />
        <Stat label="MCP 接入" value={`${registeredMcp}/${servers?.length ?? 0}`} sub={`启用 ${activeMcp} 个`} />
        <Stat label="自定义工具" value={`${registeredCustom}/${customTools?.length ?? 0}`} sub="保存即热注册" />
        <Stat label="高风险工具" value={highRiskCount} sub="先走审批再调用" />
      </div>

      <div className="tool-layout">
        <Card title={`工具目录（${filteredCatalog.length}）`} className="tools-panel tools-list-panel">
          <div className="tools-panel-stack">
            <Field label="搜索">
              <input value={toolQuery} onChange={(e) => setToolQuery(e.target.value)} placeholder="按 ref、说明、权限筛选" />
            </Field>
            <div className="tools-filter-group">
              {RISK_FILTERS.map((f) => (
                <Button key={f.value} tone={riskFilter === f.value ? 'primary' : 'default'} onClick={() => setRiskFilter(f.value)}>
                  {f.label}
                </Button>
              ))}
            </div>
            <div className="tools-filter-group">
              {SOURCE_FILTERS.map((f) => (
                <Button key={f.value} tone={sourceFilter === f.value ? 'primary' : 'default'} onClick={() => setSourceFilter(f.value)}>
                  {f.label}
                </Button>
              ))}
            </div>
            <div className="tool-list-body">
              {loading ? (
                <TableSkeleton rows={6} cols={3} />
              ) : filteredCatalog.length === 0 ? (
                <EmptyState
                  title="还没有工具"
                  desc="接入一个 MCP 源，或创建一个自定义工具，目录就会开始有内容。"
                  actions={
                    <div className="empty-state-actions">
                      <Button onClick={() => setMcpOpen(true)}>接入 MCP</Button>
                      <Button onClick={() => setCustomOpen(true)}>创建自定义工具</Button>
                      <Button asChild>
                        <Link to="/approvals">去看审批</Link>
                      </Button>
                    </div>
                  }
                />
              ) : (
                <div className="tool-list">
                  {filteredCatalog.map((t) => (
                    <button
                      key={`${t.source}-${t.ref}`}
                      type="button"
                      className={`tool-list-item${sel === t.ref ? ' on' : ''}`}
                      onClick={() => selectTool(t.ref)}
                    >
                      <div className="tool-list-main">
                        <span className="mono small">{t.ref}</span>
                        <Badge status={riskBadge(t.risk_level)}>{stateLabel(t.risk_level)}</Badge>
                      </div>
                      <div className="tool-list-sub">
                        <span className="tool-source-tag">{t.source}</span>
                        <span className="small muted">{t.description}</span>
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </Card>

        <ToolDetail
          tool={selectedTool}
          args={args}
          exec={exec}
          busy={busy}
          onArgs={setArgs}
          onRun={run}
          onFillSample={fillSample}
          onReset={resetArgs}
          onCopy={copyArgs}
          onDelete={
            selectedTool?.source === '自定义'
              ? () =>
                  confirm('删除自定义工具', `确定删除「${selectedTool.ref}」吗？此操作不可撤销。`, async () => {
                    await deleteCustom(selectedTool.ref)
                    setSel('')
                  }, { danger: true, confirmText: '删除' })
              : undefined
          }
        />
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="MCP 接入">
          <div className="tools-card-copy">
            <div className="tool-source-summary">
              <div className="tool-source-line"><span>已注册</span><b>{registeredMcp} / {servers?.length ?? 0}</b></div>
              <div className="tool-source-line"><span>启用</span><b>{activeMcp}</b></div>
              <div className="tool-source-line"><span>最近同步</span><b>{lastMcpSync || '—'}</b></div>
            </div>
            <p className="small muted tools-card-desc">新增、编辑、删除 MCP 源都在接入面板里，主页面只保留状态。</p>
            <div className="tools-card-actions">
              <Button onClick={() => setMcpOpen(true)}>管理接入源</Button>
            </div>
          </div>
        </Card>
        <Card title="自定义工具">
          <div className="tools-card-copy">
            <div className="tool-source-summary">
              <div className="tool-source-line"><span>已注册</span><b>{registeredCustom} / {customTools?.length ?? 0}</b></div>
              <div className="tool-source-line"><span>风险</span><b>{highRiskCount} 个高风险</b></div>
              <div className="tool-source-line"><span>保存</span><b>热注册</b></div>
            </div>
            <p className="small muted tools-card-desc">把内部脚本包装成可审计的工具，三步创建、可编辑、可删除。</p>
            <div className="tools-card-actions">
              <Button onClick={() => setCustomOpen(true)}>管理自定义工具</Button>
            </div>
          </div>
        </Card>
      </div>

      <McpDrawer
        open={mcpOpen}
        onClose={() => setMcpOpen(false)}
        servers={servers}
        busy={mcpBusy}
        onAdd={addServer}
        onToggle={toggleServer}
        onRemove={removeServer}
        onSave={saveMcp}
      />
      <CustomToolDrawer
        open={customOpen}
        onClose={() => setCustomOpen(false)}
        customTools={customTools}
        reservedRefs={catalog.map((t) => t.ref)}
        busy={customBusy}
        onSave={saveCustom}
        onDelete={deleteCustom}
      />
    </div>
  )
}
