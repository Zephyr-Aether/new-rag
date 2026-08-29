import { Link } from 'react-router-dom'
import { Badge, Button, Card, Field, stateLabel } from '@/components/ui'
import { EmptyState } from '@/components/Page'
import { CodeEditor } from '@/components/CodeEditor'

export interface ExecResult {
  ok: boolean
  data?: unknown
  error?: unknown
  latency_ms?: number
}

interface ToolDetailProps {
  tool: {
    ref: string
    description: string
    risk_level: string
    permission: string
    input_schema?: Record<string, unknown>
    source: string
  } | null
  args: string
  exec: ExecResult | null
  busy: boolean
  onArgs: (s: string) => void
  onRun: () => void
  onFillSample: () => void
  onReset: () => void
  onCopy: () => void
  onDelete?: () => void
}

/** 简单 schema（≤8 个属性且都有基础类型）→ 自动生成表单；否则保留 JSON 编辑。 */
function isSimpleSchema(schema?: Record<string, unknown>): boolean {
  const props = (schema?.properties ?? {}) as Record<string, unknown>
  const keys = Object.keys(props)
  return !!schema && keys.length > 0 && keys.length <= 8
}

function parseArgs(s: string): Record<string, unknown> {
  try {
    const v = JSON.parse(s || '{}')
    return v && typeof v === 'object' ? v : {}
  } catch {
    return {}
  }
}

function ArgInput({ prop, value, onChange }: {
  prop: { type?: string; enum?: unknown[]; description?: string }
  value: unknown
  onChange: (v: unknown) => void
}) {
  if (Array.isArray(prop.enum)) {
    return (
      <select value={String(value ?? prop.enum[0])} onChange={(e) => onChange(e.target.value)}>
        {prop.enum.map((o) => (
          <option key={String(o)} value={String(o)}>{String(o)}</option>
        ))}
      </select>
    )
  }
  if (prop.type === 'boolean') {
    return (
      <select value={value ? 'true' : 'false'} onChange={(e) => onChange(e.target.value === 'true')}>
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    )
  }
  if (prop.type === 'integer' || prop.type === 'number') {
    return <input type="number" value={(value ?? 0) as number} onChange={(e) => onChange(Number(e.target.value))} />
  }
  if (prop.type === 'array' || prop.type === 'object') {
    return (
      <input
        value={JSON.stringify(value ?? (prop.type === 'array' ? [] : {}))}
        onChange={(e) => { try { onChange(JSON.parse(e.target.value)) } catch { /* keep old */ } }}
        placeholder="JSON"
      />
    )
  }
  return <input value={(value ?? '') as string} onChange={(e) => onChange(e.target.value)} />
}

export default function ToolDetail({ tool, args, exec, busy, onArgs, onRun, onFillSample, onReset, onCopy, onDelete }: ToolDetailProps) {
  if (!tool) {
    return (
      <Card title="工具详情">
        <EmptyState title="还没有选择工具" desc="从左边的工具目录选一个，这里会显示它的能力、风险和试跑入口。" />
      </Card>
    )
  }

  const schema = tool.input_schema
  const simple = isSimpleSchema(schema)
  const parsed = parseArgs(args)
  const riskLevel = tool.risk_level || 'READ'
  const riskBadge = riskLevel === 'READ' ? 'PASS' : riskLevel === 'LOW_RISK_WRITE' ? 'WARN' : 'FAIL'
  const needsApproval = riskLevel === 'HIGH_RISK_WRITE' || riskLevel === 'CRITICAL'

  const props = ((schema?.properties ?? {}) as Record<string, { type?: string; enum?: unknown[]; description?: string }>)

  function updateArg(k: string, v: unknown) {
    const next = { ...parsed, [k]: v }
    onArgs(JSON.stringify(next, null, 2))
  }

  return (
    <Card title={`工具详情${tool.source ? ` · ${tool.source}` : ''}`}>
      <div className="tool-detail-grid">
        <div className="tool-detail-row"><span className="tool-detail-label">名称</span><span className="tool-detail-value mono">{tool.ref}</span></div>
        <div className="tool-detail-row"><span className="tool-detail-label">来源</span><span className="tool-detail-value">{tool.source || '—'}</span></div>
        <div className="tool-detail-row"><span className="tool-detail-label">权限</span><span className="tool-detail-value">{tool.permission || '—'}</span></div>
        <div className="tool-detail-row">
          <span className="tool-detail-label">风险</span>
          <span className="tool-detail-value"><Badge status={riskBadge}>{stateLabel(riskLevel)}</Badge></span>
        </div>
        <div className="tool-detail-row"><span className="tool-detail-label">描述</span><span className="tool-detail-value">{tool.description || '—'}</span></div>
        <div className="tool-detail-row">
          <span className="tool-detail-label">关联流程</span>
          <span className="tool-detail-value">
            <Link className="link" to="/evaluation">评测门禁</Link>
            {' · '}
            <Link className="link" to="/release">发布链路</Link>
          </span>
        </div>
      </div>

      {tool.source === '自定义' && onDelete && (
        <div className="row mt" style={{ justifyContent: 'flex-end' }}>
          <Button tone="danger" onClick={onDelete}>删除该工具</Button>
        </div>
      )}

      <div className="tool-run">
        <div className="tool-run-head">
          <span className="tool-run-title">试跑</span>
          <span className="small muted">{simple ? '按入参自动生成表单' : 'schema 较复杂，直接编辑 JSON'}</span>
        </div>
        {needsApproval && (
          <div className="tool-approval-hint">该工具为高风险，接入流程会触发审批。</div>
        )}
        {!tool.input_schema ? (
          <p className="small muted">该工具来自 MCP，入参详情请在「接入源」查看。</p>
        ) : simple ? (
          <div className="tool-arg-form">
            {Object.keys(props).map((k) => (
              <div key={k} className="tool-arg-field">
                <label className="small">{k}</label>
                <ArgInput prop={props[k]} value={parsed[k]} onChange={(v) => updateArg(k, v)} />
              </div>
            ))}
          </div>
        ) : (
          <Field label="参数（JSON）">
            <CodeEditor value={args} onChange={onArgs} />
          </Field>
        )}

        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <Button tone="primary" disabled={busy || !tool.input_schema} onClick={onRun}>{busy ? '执行中…' : '执行试跑'}</Button>
          <Button disabled={!tool.input_schema} onClick={onFillSample}>填充示例</Button>
          <Button disabled={!tool.input_schema} onClick={onReset}>重置默认参数</Button>
          <Button disabled={!tool.input_schema} onClick={onCopy}>复制入参</Button>
        </div>

        {exec && (
          <div className="mt">
            {exec.ok ? (
              <div className="tool-run-ok">
                <pre className="pretty">{JSON.stringify(exec.data, null, 2)}</pre>
                {typeof exec.latency_ms === 'number' && <div className="small muted mt">耗时 {exec.latency_ms} ms</div>}
                {needsApproval && <div className="small mt" style={{ color: 'var(--warning)' }}>提示：接入流程后该工具调用会触发审批。</div>}
              </div>
            ) : (
              <div className="tool-run-fail">
                <b>试跑失败</b>
                <div className="small mt">{typeof exec.error === 'string' ? exec.error : JSON.stringify(exec.error)}</div>
                <div className="small muted mt">可能原因：参数与 schema 不匹配、入参不是合法 JSON，或工具运行时报错。可先「重置默认参数」再试。</div>
              </div>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}
