import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { ArrowRight } from 'lucide-react'
import { api, CustomTool, McpServer, ToolDef } from '../api'
import { Badge, Button, Card, ErrorBox, Field, Stat, stateLabel, SuccessBox, TableSkeleton } from '../components/ui'
import { CodeEditor } from '../components/CodeEditor'
import { EmptyState, PageHeader } from '../components/Page'
import { useConfirm } from '../components/Confirm'

const RISK_OPTIONS = [
  { value: 'READ', label: '只读（READ）' },
  { value: 'LOW_RISK_WRITE', label: '低风险写（LOW_RISK_WRITE）' },
  { value: 'HIGH_RISK_WRITE', label: '高风险写·需审批（HIGH_RISK_WRITE）' },
  { value: 'CRITICAL', label: '关键操作·需审批（CRITICAL）' },
]

const TOOL_ACTIONS = [
  { title: '去评测', desc: '把工具调用也纳入样例门禁。', to: '/evaluation' },
  { title: '看发布链路', desc: '确认工具、评测和模型都能一起过线。', to: '/release' },
  { title: '审批队列', desc: '高风险工具先走审批，再放给用户。', to: '/approvals' },
]

export default function Tools() {
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, error, refresh } = useRequest(() => Promise.all([api.tools(), api.mcpServers(), api.customTools()]))

  const tools = data?.[0].tools ?? []
  const mcpLoaded = data?.[1].servers ?? []
  const customLoaded = data?.[2].tools ?? []

  const [sel, setSel] = useState('')
  const [toolQuery, setToolQuery] = useState('')
  const [args, setArgs] = useState('{}')
  const [exec, setExec] = useState<{ ok: boolean; data?: unknown; error?: unknown; latency_ms?: number } | null>(null)
  const [busy, setBusy] = useState(false)

  // MCP 服务器（页面接入）
  const [servers, setServers] = useState<McpServer[] | null>(null)
  const [mcpMsg, setMcpMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [mcpBusy, setMcpBusy] = useState(false)
  const [newName, setNewName] = useState('')
  const [newUrl, setNewUrl] = useState('')
  const [newAllow, setNewAllow] = useState('')

  // 自定义工具（沙箱代码）
  const [customTools, setCustomTools] = useState<CustomTool[] | null>(null)
  const [customMsg, setCustomMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [customBusy, setCustomBusy] = useState(false)
  const [cRef, setCRef] = useState('')
  const [cDesc, setCDesc] = useState('')
  const [cTimeout, setCTimeout] = useState('5')
  const [cRisk, setCRisk] = useState('LOW_RISK_WRITE')
  const [cSchema, setCSchema] = useState(`{
  "type": "object",
  "properties": {}
}`)
  const [cCode, setCCode] = useState('def run(args):\n    return {"echo": args}')

  useEffect(() => {
    setServers(mcpLoaded)
    setCustomTools(customLoaded)
  }, [customLoaded, mcpLoaded])

  useEffect(() => {
    if (!tools.length) return
    if (!sel || !tools.some((t) => t.ref === sel)) {
      selectTool(tools[0].ref, tools)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tools])

  const filteredTools = useMemo(() => {
    const q = toolQuery.trim().toLowerCase()
    if (!q) return tools
    return tools.filter((t) => `${t.ref} ${t.description} ${t.permission}`.toLowerCase().includes(q))
  }, [toolQuery, tools])

  const selectedTool = tools.find((t) => t.ref === sel) ?? null

  function riskStatus(r: string) {
    return r === 'READ' ? 'PASS' : r === 'LOW_RISK_WRITE' ? 'WARN' : 'FAIL'
  }

  function defaultArgsFor(schema: Record<string, unknown>): Record<string, unknown> {
    const props = (schema?.properties ?? {}) as Record<string, { type?: string; default?: unknown; enum?: unknown[] }>
    const required = (schema?.required ?? []) as string[]
    const args: Record<string, unknown> = {}
    for (const [k, p] of Object.entries(props)) {
      if (p && p.default !== undefined) {
        args[k] = p.default
      } else if (required.includes(k)) {
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

  function selectTool(ref: string, list: ToolDef[] | null = tools) {
    setSel(ref)
    const t = (list ?? []).find((x) => x.ref === ref)
    setArgs(JSON.stringify(defaultArgsFor(t?.input_schema ?? {}), null, 2))
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

  function addServer() {
    if (!newName.trim() || !newUrl.trim()) return
    const allow = newAllow.split(',').map((s) => s.trim()).filter(Boolean)
    setServers((prev) => [
      ...(prev ?? []),
      { name: newName.trim(), base_url: newUrl.trim(), allow, enabled: true, registered: false, tools: [] },
    ])
    setNewName('')
    setNewUrl('')
    setNewAllow('')
  }

  function toggleServer(name: string) {
    setServers((prev) => (prev ?? []).map((s) => (s.name === name ? { ...s, enabled: !s.enabled } : s)))
  }

  function removeServer(name: string) {
    setServers((prev) => (prev ?? []).filter((s) => s.name !== name))
  }

  async function saveMcp() {
    setMcpBusy(true)
    setMcpMsg(null)
    try {
      const list = (servers ?? []).map((s) => ({ name: s.name, base_url: s.base_url, allow: s.allow, enabled: s.enabled }))
      const r = await api.mcpServersSet(list)
      const details = Object.entries(r.results || {}).map(([k, v]) => `${k}: ${v}`).join('；')
      setMcpMsg({ kind: 'ok', text: `已保存 ${r.count} 个 server${details ? `（${details}）` : ''}` })
      refresh()
    } catch (e) {
      setMcpMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setMcpBusy(false)
    }
  }

  function resetCustomForm() {
    setCRef('')
    setCDesc('')
    setCTimeout('5')
    setCRisk('LOW_RISK_WRITE')
    setCSchema(`{
  "type": "object",
  "properties": {}
}`)
    setCCode('def run(args):\n    return {"echo": args}')
  }

  async function saveCustom() {
    if (!cRef.trim() || !cCode.trim()) return
    setCustomBusy(true)
    setCustomMsg(null)
    try {
      let schema: Record<string, unknown>
      try {
        schema = JSON.parse(cSchema || '{}')
      } catch {
        setCustomMsg({ kind: 'err', text: 'input_schema 不是合法 JSON' })
        return
      }
      const base = (customTools ?? []).filter((t) => t.ref !== cRef.trim())
      const list = [
        ...base.map((t) => ({ ref: t.ref, description: t.description, input_schema: t.input_schema, code: t.code, timeout_s: t.timeout_s, risk_level: t.risk_level })),
        { ref: cRef.trim(), description: cDesc.trim(), input_schema: schema, code: cCode, timeout_s: Number(cTimeout) || 5, risk_level: cRisk },
      ]
      const r = await api.customToolsSet(list)
      const details = Object.entries(r.results || {}).map(([k, v]) => `${k}: ${v}`).join('；')
      setCustomMsg({ kind: 'ok', text: `已保存 ${r.count} 个工具${details ? `（${details}）` : ''}` })
      refresh()
      resetCustomForm()
    } catch (e) {
      setCustomMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setCustomBusy(false)
    }
  }

  function loadCustom(t: CustomTool) {
    setCRef(t.ref)
    setCDesc(t.description)
    setCTimeout(String(t.timeout_s))
    setCRisk(t.risk_level || 'LOW_RISK_WRITE')
    setCSchema(JSON.stringify(t.input_schema, null, 2))
    setCCode(t.code)
  }

  async function deleteCustom(ref: string) {
    setCustomBusy(true)
    setCustomMsg(null)
    try {
      const list = (customTools ?? [])
        .filter((t) => t.ref !== ref)
        .map((t) => ({ ref: t.ref, description: t.description, input_schema: t.input_schema, code: t.code, timeout_s: t.timeout_s, risk_level: t.risk_level }))
      await api.customToolsSet(list)
      setCustomMsg({ kind: 'ok', text: `已删除 ${ref}` })
      refresh()
      if (cRef === ref) resetCustomForm()
    } catch (e) {
      setCustomMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setCustomBusy(false)
    }
  }

  const builtInCount = tools.length
  const readCount = tools.filter((t) => t.risk_level === 'READ').length
  const writeCount = tools.filter((t) => t.risk_level !== 'READ').length
  const highRiskCount = tools.filter((t) => t.risk_level === 'HIGH_RISK_WRITE' || t.risk_level === 'CRITICAL').length
  const registeredMcp = (servers ?? []).filter((s) => s.registered).length
  const activeMcp = (servers ?? []).filter((s) => s.enabled).length
  const registeredCustom = (customTools ?? []).filter((t) => t.registered).length
  const customCount = customTools?.length ?? 0
  const toolAdvice =
    builtInCount > 0
      ? `当前有 ${builtInCount} 个内置工具、${registeredMcp}/${servers?.length ?? 0} 个 MCP 服务器已注册、${registeredCustom}/${customCount} 个自定义工具已注册。高风险工具 ${highRiskCount} 个，建议先把它们和审批链路绑紧。`
      : '还没有可用工具：先接一个 MCP 服务器，或创建一个自定义工具，目录就会开始有内容。'

  return (
    <div className="grid" style={{ gap: 18 }}>
      {confirmEl}
      {error && <ErrorBox message={(error as Error).message} />}

      <PageHeader
        title="工具"
        desc="把工具当能力目录，而不是调试台。"
        actions={
          <>
            <Link className="btn" to="/evaluation">
              去评测
            </Link>
            <Link className="btn primary" to="/release">
              看发布链路
            </Link>
          </>
        }
      />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">工具能力</span>
          <span>{toolAdvice}</span>
          <span className="small muted" style={{ color: 'var(--text-2)' }}>
            先看目录和风险，再去试跑参数。这样用户更容易分清“能用什么”和“怎么接进来”。
          </span>
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <Link className="btn" to="/approvals">
            审批队列 <ArrowRight size={14} />
          </Link>
          <Link className="btn" to="/evaluation">
            评测门禁 <ArrowRight size={14} />
          </Link>
        </div>
      </div>

      <div className="grid cols-4">
        <Stat label="内置工具" value={builtInCount} sub={`只读 ${readCount} / 写操作 ${writeCount}`} />
        <Stat label="MCP 接入" value={`${registeredMcp}/${servers?.length ?? 0}`} sub={`启用 ${activeMcp} 个 server`} />
        <Stat label="自定义工具" value={`${registeredCustom}/${customCount}`} sub="保存即热注册，适合内部门类能力" />
        <Stat label="高风险工具" value={highRiskCount} sub="先走审批，再开放调用" />
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="能力目录">
          <div className="small muted" style={{ marginBottom: 10 }}>
            这里看的是平台到底能调用什么，不是怎么拼参数。
          </div>
          <Field label="筛选工具">
            <input value={toolQuery} onChange={(e) => setToolQuery(e.target.value)} placeholder="按 ref、说明、权限筛选" />
          </Field>
          {loading ? (
            <TableSkeleton rows={5} cols={4} />
          ) : filteredTools.length === 0 ? (
            <EmptyState
              title="还没有可用工具"
              desc="先接一个 MCP 服务器，或新建一个自定义工具。保存后，工具目录会自动变成可调用的能力清单。"
              actions={
                <div className="empty-state-actions">
                  <Link className="btn primary" to="/approvals">
                    先看审批
                  </Link>
                  <Link className="btn" to="/evaluation">
                    去评测
                  </Link>
                </div>
              }
            />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>工具</th>
                  <th>权限</th>
                  <th>风险</th>
                  <th>说明</th>
                </tr>
              </thead>
              <tbody>
                {filteredTools.map((t) => (
                  <tr
                    key={t.ref}
                    onClick={() => selectTool(t.ref)}
                    style={{ cursor: 'pointer', background: sel === t.ref ? 'var(--bg)' : undefined }}
                  >
                    <td className="mono">{t.ref}</td>
                    <td className="small muted">{t.permission || '—'}</td>
                    <td>
                      <Badge status={riskStatus(t.risk_level)}>{stateLabel(t.risk_level)}</Badge>
                    </td>
                    <td className="small muted">{t.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="试跑与检查">
          <div className="small muted" style={{ marginBottom: 10 }}>
            选一个工具试跑，先确认参数和返回值，再决定要不要把它接进流程。
          </div>
          <div className="tool-meta-grid">
            <div className="tool-meta-row">
              <span className="tool-meta-label">当前工具</span>
              <span className="tool-meta-value mono">{selectedTool?.ref ?? '—'}</span>
            </div>
            <div className="tool-meta-row">
              <span className="tool-meta-label">权限</span>
              <span className="tool-meta-value">{selectedTool?.permission || '—'}</span>
            </div>
            <div className="tool-meta-row">
              <span className="tool-meta-label">风险</span>
              <span className="tool-meta-value">
                {selectedTool ? <Badge status={riskStatus(selectedTool.risk_level)}>{stateLabel(selectedTool.risk_level)}</Badge> : '—'}
              </span>
            </div>
            <div className="tool-meta-row">
              <span className="tool-meta-label">说明</span>
              <span className="tool-meta-value tool-meta-copy">{selectedTool?.description || '—'}</span>
            </div>
          </div>
          <Field label="工具">
            <select value={sel} onChange={(e) => selectTool(e.target.value)}>
              {(tools ?? []).map((t) => (
                <option key={t.ref} value={t.ref}>
                  {t.ref}
                </option>
              ))}
            </select>
          </Field>
          <Field label="参数（JSON）">
            <CodeEditor value={args} onChange={setArgs} />
          </Field>
          <Button tone="primary" disabled={busy || !sel} onClick={run}>
            {busy ? '执行中…' : '执行'}
          </Button>
          {exec && (
            <div className="mt">
              {exec.ok ? (
                <pre className="pretty">
                  <span className="ok">ok:</span> {JSON.stringify(exec.data, null, 2)}
                </pre>
              ) : (
                <ErrorBox message={typeof exec.error === 'string' ? exec.error : JSON.stringify(exec.error)} />
              )}
              {typeof exec.latency_ms === 'number' && <div className="small muted mt">耗时 {exec.latency_ms} ms</div>}
            </div>
          )}
        </Card>
      </div>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <Card title="MCP 接入源">
          <div className="small muted" style={{ marginBottom: 10 }}>
            接入完成后会自动注册到 Agent。保存前先确认白名单，避免把整站能力都暴露出去。
          </div>
          <div className="tool-source-form">
            <input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="server 名" />
            <input value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="base_url，如 http://localhost:8081" />
            <input value={newAllow} onChange={(e) => setNewAllow(e.target.value)} placeholder="工具白名单（逗号，可选）" />
            <Button disabled={!newName.trim() || !newUrl.trim()} onClick={addServer}>
              添加
            </Button>
          </div>
          {servers === null ? (
            <TableSkeleton rows={5} cols={5} />
          ) : servers.length === 0 ? (
            <EmptyState title="还没有 MCP 服务器" desc="添加一个 MCP 服务器并保存，它提供的工具会自动注册到 Agent。" />
          ) : (
            <table className="tbl">
              <thead>
                <tr>
                  <th>名称</th>
                  <th>base_url</th>
                  <th>工具数</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {servers.map((s) => (
                  <tr key={s.name}>
                    <td className="mono small">{s.name}</td>
                    <td className="mono small muted">{s.base_url}</td>
                    <td className="num small">{s.tools.length}</td>
                    <td>
                      <Badge status={s.registered ? 'PASS' : s.enabled ? 'WARN' : 'DISABLED'}>
                        {s.registered ? '已注册' : s.enabled ? '待注册' : '已停用'}
                      </Badge>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <Button onClick={() => toggleServer(s.name)}>{s.enabled ? '停用' : '启用'}</Button>
                        <Button
                          tone="danger"
                          onClick={() =>
                            confirm(
                              '移除 MCP 服务器',
                              `确定移除「${s.name}」吗？该服务器下的所有工具将立即不可用。`,
                              () => removeServer(s.name),
                              { danger: true, confirmText: '移除' },
                            )
                          }
                        >
                          移除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <div className="row mt">
            <Button tone="primary" disabled={mcpBusy} onClick={saveMcp}>
              {mcpBusy ? '保存中…' : '保存并热注册'}
            </Button>
            {mcpMsg && (mcpMsg.kind === 'ok' ? <SuccessBox message={mcpMsg.text} /> : <ErrorBox message={mcpMsg.text} />)}
          </div>
        </Card>

        <Card title="自定义工具">
          <div className="small muted" style={{ marginBottom: 10 }}>
            适合把内部脚本包装成一个可审计的工具。保存后会热注册，风险级别可以直接接审批链。
          </div>
          <div className="grid cols-2" style={{ gap: 12 }}>
            <div>
              <Field label="工具 ref">
                <input value={cRef} onChange={(e) => setCRef(e.target.value)} placeholder="my.weather" />
              </Field>
              <Field label="描述">
                <input value={cDesc} onChange={(e) => setCDesc(e.target.value)} placeholder="工具说明…" />
              </Field>
              <Field label="超时（秒）">
                <input type="number" min={1} max={60} value={cTimeout} onChange={(e) => setCTimeout(e.target.value)} />
              </Field>
              <Field label="风险级（HIGH_RISK_WRITE / CRITICAL 触发审批）">
                <select value={cRisk} onChange={(e) => setCRisk(e.target.value)}>
                  {RISK_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <Field label="input_schema（JSON）">
              <CodeEditor value={cSchema} onChange={setCSchema} />
            </Field>
          </div>
          <Field label="Python 代码（定义 def run(args)，返回 JSON 可序列化；沙箱禁网络 / 限文件访问）">
            <CodeEditor value={cCode} onChange={setCCode} language="python" />
          </Field>
          <div className="row mt">
            <Button tone="primary" disabled={customBusy || !cRef.trim() || !cCode.trim()} onClick={saveCustom}>
              {customBusy ? '保存中…' : '保存工具'}
            </Button>
            <Button disabled={customBusy} onClick={resetCustomForm}>
              清空
            </Button>
            {customMsg && (customMsg.kind === 'ok' ? <SuccessBox message={customMsg.text} /> : <ErrorBox message={customMsg.text} />)}
          </div>

          {customTools !== null && customTools.length > 0 && (
            <table className="tbl mt">
              <thead>
                <tr>
                  <th>ref</th>
                  <th>描述</th>
                  <th>超时</th>
                  <th>风险</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {customTools.map((t) => (
                  <tr key={t.ref}>
                    <td className="mono small">{t.ref}</td>
                    <td className="small muted">{t.description || '—'}</td>
                    <td className="num small">{t.timeout_s}s</td>
                    <td>
                      <Badge status={riskStatus(t.risk_level)}>{stateLabel(t.risk_level)}</Badge>
                    </td>
                    <td>
                      <Badge status={t.registered ? 'PASS' : 'WARN'}>{t.registered ? '已注册' : '未注册'}</Badge>
                    </td>
                    <td>
                      <div className="row" style={{ gap: 6 }}>
                        <Button disabled={customBusy} onClick={() => loadCustom(t)}>
                          编辑
                        </Button>
                        <Button
                          tone="danger"
                          disabled={customBusy}
                          onClick={() =>
                            confirm('删除自定义工具', `确定删除自定义工具「${t.ref}」吗？此操作不可撤销。`, () => deleteCustom(t.ref), {
                              danger: true,
                              confirmText: '删除',
                            })
                          }
                        >
                          删除
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div className="grid cols-3">
        {TOOL_ACTIONS.map((a) => (
          <Link key={a.to} className="stat-link action-tile" to={a.to}>
            <div className="stat">
              <div className="label">{a.title}</div>
              <div className="sub">{a.desc}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
