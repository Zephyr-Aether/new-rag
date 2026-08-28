import { FormEvent, useState } from 'react'
import { useRequest } from 'ahooks'
import { api } from '../api'
import { Badge, Button, Card, ErrorBox, Field, fmtTime, shortId, SuccessBox, TableSkeleton } from '../components/ui'
import { useConfirm } from '../components/Confirm'
import { EmptyState, PageHeader } from '../components/Page'
import { usePermissions } from '../hooks/usePermissions'

const SCOPES = ['USER', 'AGENT']
const TYPES = ['SEMANTIC', 'EPISODIC', 'PROCEDURAL']

const SCOPE_LABELS: Record<string, string> = { USER: '用户', AGENT: '智能体' }
const TYPE_LABELS: Record<string, string> = { SEMANTIC: '语义', EPISODIC: '情景', PROCEDURAL: '程序性' }
const TRUST_LABELS: Record<string, string> = { trusted: '可信', untrusted: '不可信' }
const SOURCE_LABELS: Record<string, string> = { auto: '自动沉淀', console: '控制台' }

const QUICK_TEMPLATES = [
  {
    label: '用户偏好',
    value: '用户偏好：后续回答尽量用中文，先给结论，再补细节。',
  },
  {
    label: '业务事实',
    value: '业务事实：退款流程负责人是张三，紧急问题先找他确认。',
  },
  {
    label: '流程约束',
    value: '流程约束：发布前需要先过评测，再走审批。',
  },
]

export default function Memory() {
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const [query, setQuery] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [content, setContent] = useState('')
  const [scope, setScope] = useState('USER')
  const [memType, setMemType] = useState('SEMANTIC')
  const [source, setSource] = useState('')
  const [trust, setTrust] = useState('trusted')
  const [ttl, setTtl] = useState('')

  const { data, loading, error, run } = useRequest((q: string) => api.recallMemory(q, 50), { defaultParams: [''] as [string] })
  const entries = data?.entries ?? null

  async function write(e: FormEvent) {
    e.preventDefault()
    if (!content.trim() || busy) return
    setBusy(true)
    setMsg(null)
    try {
      await api.writeMemory({
        content: content.trim(),
        scope,
        memory_type: memType,
        source: source.trim(),
        source_trust: trust,
        ttl_days: ttl ? Number(ttl) : undefined,
      })
      setMsg({ kind: 'ok', text: '记忆已写入' })
      setContent('')
      setSource('')
      setTtl('')
      await run('')
    } catch (e2) {
      setMsg({ kind: 'err', text: (e2 as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function remove(id: string) {
    setMsg(null)
    try {
      await api.deleteMemory(id)
      setMsg({ kind: 'ok', text: '已删除' })
      await run(query)
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  return (
    <div>
      {confirmEl}
      <PageHeader title="历史记忆" desc="Agent 跨会话记住的上下文；支持召回、写入与删除。" />
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div>
          <Card title="记忆召回（按租户与用户隔离）">
            <div className="row">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && run(query)}
                placeholder="按相关性召回，留空=最近写入"
                style={{ flex: 1 }}
              />
              <Button tone="primary" onClick={() => run(query)}>召回</Button>
            </div>
          </Card>
          {error && <div className="mt"><ErrorBox message={(error as Error).message} /></div>}
          {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
          <div className="mt">
            <Card title={`记忆条目（${entries?.length ?? '…'}）`}>
              {loading ? (
                <TableSkeleton rows={5} cols={5} />
              ) : (entries ?? []).length === 0 ? (
                <EmptyState
                  title="暂无记忆条目"
                  desc="先写入一条偏好、事实或流程约束，再用召回验证它会不会出现在这里。"
                  action={() => run('')}
                  actionLabel="召回最近写入"
                />
              ) : (
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>内容</th>
                      <th>类型</th>
                      <th>信任</th>
                      <th className="num">置信/相关</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(entries ?? []).map((m) => (
                      <tr key={m.memory_id}>
                        <td className="small">
                          <div>{m.content}</div>
                          <div className="muted mono" style={{ fontSize: 11 }}>
                            {fmtTime(m.created_at)} · {shortId(m.memory_id)} · {SCOPE_LABELS[m.scope] ?? m.scope}
                            {m.source ? ` · 来源 ${SOURCE_LABELS[m.source] ?? m.source}` : ''}
                          </div>
                        </td>
                        <td><Badge status={m.memory_type}>{TYPE_LABELS[m.memory_type] ?? m.memory_type}</Badge></td>
                        <td className="small muted">{TRUST_LABELS[m.source_trust] ?? m.source_trust}</td>
                        <td className="num small mono">
                          {m.confidence?.toFixed(2)}
                          {m.score !== undefined ? ` / ${m.score.toFixed(2)}` : ''}
                        </td>
                        <td className="num">
                          <Button tone="danger" onClick={() => confirm('删除记忆', '确定删除这条记忆吗？此操作不可撤销。', () => remove(m.memory_id), { danger: true, confirmText: '删除' })}>删除</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>
        </div>
        <div className="memory-panel">
          <Card title="写入记忆">
            <div className="small muted memory-intro">
              把稳定偏好、事实和流程约束写进来，后续召回会优先命中这些内容。
            </div>
            <div className="memory-template-grid">
              {QUICK_TEMPLATES.map((item) => (
                <Button key={item.label} className="memory-template-btn" tone="default" onClick={() => setContent(item.value)}>
                  {item.label}：{item.value}
                </Button>
              ))}
            </div>
            <form onSubmit={write}>
              <Field label="内容">
                <textarea
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="如：用户偏好中文回答 / 退款流程负责人是张三"
                />
              </Field>
              <Field label="作用域">
                <select value={scope} onChange={(e) => setScope(e.target.value)}>
                  {SCOPES.map((s) => (
                    <option key={s} value={s}>{SCOPE_LABELS[s] ?? s}</option>
                  ))}
                </select>
              </Field>
              <Field label="记忆类型">
                <select value={memType} onChange={(e) => setMemType(e.target.value)}>
                  {TYPES.map((t) => (
                    <option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>
                  ))}
                </select>
              </Field>
              <Field label="来源（可选）">
                <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="console / doc-xxx" />
              </Field>
              <Field label="来源可信度（可信分级）">
                <select value={trust} onChange={(e) => setTrust(e.target.value)}>
                  <option value="trusted">可信（用户明确表达）</option>
                  <option value="untrusted">不可信（自动提炼，需谨慎）</option>
                </select>
              </Field>
              <Field label="TTL 天数（可选，到期自动失效）">
                <input type="number" min={1} value={ttl} onChange={(e) => setTtl(e.target.value)} />
              </Field>
              <Button tone="primary" disabled={busy || !content.trim() || !can('memory:write')} className="mt">
                {busy ? '写入中…' : '写入'}
              </Button>
            </form>
          </Card>

          <Card title="写入建议">
            <div className="memory-guide-list">
              <div className="memory-guide-item">
                <div className="memory-guide-title">优先写稳定信息</div>
                <div className="memory-guide-desc">偏好、角色、流程、责任人，比临时性的对话片段更适合沉淀成记忆。</div>
              </div>
              <div className="memory-guide-item">
                <div className="memory-guide-title">尽量写成可复用事实</div>
                <div className="memory-guide-desc">用“谁 / 什么 / 什么时候 / 约束是什么”来表述，后续召回更容易命中。</div>
              </div>
              <div className="memory-guide-item">
                <div className="memory-guide-title">写入前先看守卫</div>
                <div className="memory-guide-desc">注入、敏感或明显噪声内容会被拒绝，建议只写业务上真的要长期记住的东西。</div>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
