import { FormEvent, useState } from 'react'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/sheet'
import { useRequest } from 'ahooks'
import { api, MemoryEntry } from '@/services'
import { Badge, Button, Card, ErrorBox, Field, fmtTime, TableSkeleton } from '@/components'
import { Switch } from '@/components/switch'
import { EmptyState, PageHeader } from '@/components/Page'
import { usePermissions } from '@/hooks/usePermissions'
import { toast } from '@/toast'

const SCOPES = ['USER', 'AGENT']
const TYPES = ['SEMANTIC', 'EPISODIC', 'PROCEDURAL']
const SCOPE_LABELS: Record<string, string> = { USER: '用户', AGENT: '智能体' }
const TYPE_LABELS: Record<string, string> = { SEMANTIC: '语义', EPISODIC: '情景', PROCEDURAL: '程序性' }
const TRUST_LABELS: Record<string, string> = { trusted: '可信', untrusted: '不可信' }
const SOURCE_LABELS: Record<string, string> = { auto: '自动沉淀', console: '控制台' }

const QUICK_TEMPLATES = [
  { label: '用户偏好', value: '用户偏好：后续回答尽量用中文，先给结论，再补细节。' },
  { label: '业务事实', value: '业务事实：退款流程负责人是张三，紧急问题先找他确认。' },
  { label: '流程约束', value: '流程约束：发布前需要先过评测，再走审批。' },
]

export default function Memory() {
  const { can } = usePermissions()
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const [content, setContent] = useState('')
  const [scope, setScope] = useState('USER')
  const [memType, setMemType] = useState('SEMANTIC')
  const [source, setSource] = useState('')
  const [trust, setTrust] = useState('trusted')
  const [ttl, setTtl] = useState('')
  const [fScope, setFScope] = useState('')
  const [fType, setFType] = useState('')
  const [fTrust, setFTrust] = useState('')
  const [highConfOnly, setHighConfOnly] = useState(false)
  const [detail, setDetail] = useState<MemoryEntry | null>(null)
  const [undo, setUndo] = useState<{ entry: MemoryEntry } | null>(null)
  const [undoBusy, setUndoBusy] = useState(false)

  const { data, loading, error, run } = useRequest((q: string) => api.recallMemory(q, 50), { defaultParams: [''] as [string] })
  const entries = data?.entries ?? null

  const filtered = (entries ?? []).filter((m) => {
    if (fScope && m.scope !== fScope) return false
    if (fType && m.memory_type !== fType) return false
    if (fTrust && m.source_trust !== fTrust) return false
    if (highConfOnly && (m.confidence ?? 0) < 0.8) return false
    return true
  })

  async function write(e: FormEvent) {
    e.preventDefault()
    if (!content.trim() || busy) return
    setBusy(true)
    try {
      await api.writeMemory({
        content: content.trim(),
        scope,
        memory_type: memType,
        source: source.trim(),
        source_trust: trust,
        ttl_days: ttl ? Number(ttl) : undefined,
      })
      toast('记忆已写入')
      setContent('')
      setSource('')
      setTtl('')
      await run('')
    } catch (e2) {
      toast((e2 as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  async function remove(entry: MemoryEntry) {
    try {
      await api.deleteMemory(entry.memory_id)
      setUndo({ entry })
      setTimeout(() => setUndo((u) => (u?.entry.memory_id === entry.memory_id ? null : u)), 6000)
      await run(query)
    } catch (e) {
      toast((e as Error).message, 'err')
    }
  }

  async function undoDelete() {
    if (!undo) return
    setUndoBusy(true)
    try {
      await api.writeMemory({
        content: undo.entry.content,
        scope: undo.entry.scope,
        memory_type: undo.entry.memory_type,
        source: undo.entry.source,
        source_trust: undo.entry.source_trust,
      })
      setUndo(null)
      await run(query)
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setUndoBusy(false)
    }
  }

  const guardHint = trust === 'untrusted'
    ? '标记为「不可信」时，守卫可能拒绝写入或降低召回权重，谨慎使用。'
    : '守卫会拦截注入、敏感或明显噪声内容；业务相关的稳定信息通常可以直接写入。'

  return (
    <div>
      <PageHeader title="历史记忆" desc="Agent 跨会话记住的上下文；召回为主入口，支持写入与撤销删除。" />

      {/* 召回主入口 */}
      <div className="memory-search">
        <div className="memory-search-row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run(query)}
            placeholder="召回：输入问题或关键词，回车直接召回；留空 = 最近写入"
            style={{ flex: 1 }}
          />
          <Button tone="primary" disabled={loading} onClick={() => run(query)}>{loading ? '召回中…' : '召回'}</Button>
        </div>
        <div className="memory-search-filters">
          <span className="memory-filter-label">快捷筛选</span>
          {[['', '全部作用域'], ['USER', '用户'], ['AGENT', '智能体']].map(([v, l]) => (
            <button key={v} type="button" className={`btn ${fScope === v ? 'primary' : ''}`} onClick={() => setFScope(v)}>{l}</button>
          ))}
          {[['', '全部类型'], ['SEMANTIC', '语义'], ['EPISODIC', '情景'], ['PROCEDURAL', '程序性']].map(([v, l]) => (
            <button key={v} type="button" className={`btn ${fType === v ? 'primary' : ''}`} onClick={() => setFType(v)}>{l}</button>
          ))}
          {[['', '全部信任'], ['trusted', '可信'], ['untrusted', '不可信']].map(([v, l]) => (
            <button key={v} type="button" className={`btn ${fTrust === v ? 'primary' : ''}`} onClick={() => setFTrust(v)}>{l}</button>
          ))}
          <label className="memory-switch flex items-center gap-2 text-sm">
            <Switch checked={highConfOnly} onCheckedChange={setHighConfOnly} />
            只看高置信
          </label>
        </div>
      </div>

      {error && <div className="mt"><ErrorBox message={(error as Error).message} /></div>}
      
      {undo && (
        <div className="memory-undo">
          <span>已删除「{undo.entry.content.slice(0, 30)}…」</span>
          <Button disabled={undoBusy} onClick={undoDelete}>{undoBusy ? '恢复中…' : '撤销'}</Button>
        </div>
      )}

      <div className="memory-layout">
        {/* 列表 + 详情 */}
        <div className="memory-list-col">
          <Card title={`记忆条目（${filtered.length} 命中${query.trim() ? ` · 按相关性排序` : ''}）`}>
            {loading ? (
              <TableSkeleton rows={5} cols={3} />
            ) : filtered.length === 0 ? (
              <EmptyState
                title="还没有匹配的记忆"
                desc="先写一条偏好或事实，再回来召回；也可以一键填充示例再召回验证。"
                actions={
                  <div className="empty-state-actions">
                    <Button onClick={() => { setContent(QUICK_TEMPLATES[0].value); document.getElementById('memory-write')?.scrollIntoView({ behavior: 'smooth' }) }}>填充示例去写入</Button>
                    <Button disabled={loading} onClick={() => run('')}>召回最近写入</Button>
                  </div>
                }
              />
            ) : (
              <div className="memory-cards">
                {filtered.map((m) => (
                  <button key={m.memory_id} type="button" className="memory-card" onClick={() => setDetail(m)}>
                    <div className="memory-card-head">
                      <span className={`memory-trust ${m.source_trust === 'trusted' ? 'ok' : 'warn'}`}>
                        {TRUST_LABELS[m.source_trust] ?? m.source_trust}
                      </span>
                      <Badge status={m.memory_type}>{TYPE_LABELS[m.memory_type] ?? m.memory_type}</Badge>
                      <span className="memory-card-score">{m.score !== undefined ? `相关 ${m.score.toFixed(2)}` : `置信 ${(m.confidence ?? 0).toFixed(2)}`}</span>
                    </div>
                    <div className="memory-card-content">{m.content}</div>
                    <div className="memory-card-meta">{fmtTime(m.created_at)} · {SCOPE_LABELS[m.scope] ?? m.scope}{m.source ? ` · ${SOURCE_LABELS[m.source] ?? m.source}` : ''}</div>
                  </button>
                ))}
              </div>
            )}
          </Card>
        </div>

        {/* 写入编辑器 */}
        <div className="memory-panel" id="memory-write">
          <Card title="写入记忆">
            <div className="small muted memory-intro">
              把稳定偏好、事实和流程约束写进来，后续召回会优先命中。
            </div>
            <div className="memory-template-chips">
              {QUICK_TEMPLATES.map((item) => (
                <button key={item.label} type="button" className="memory-template-chip" onClick={() => setContent(item.value)}>
                  {item.label}
                </button>
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
              {content.trim() && (
                <div className="memory-preview">
                  <div className="memory-preview-title">写入预览</div>
                  <div className="memory-preview-line"><b>内容</b> {content.trim() ? content.trim().slice(0, 60) + (content.trim().length > 60 ? '…' : '') : '—'}</div>
                  <div className="memory-preview-line"><b>作用域</b> {SCOPE_LABELS[scope] ?? scope}</div>
                  <div className="memory-preview-line"><b>类型</b> {TYPE_LABELS[memType] ?? memType}</div>
                  <div className="memory-preview-line"><b>TTL</b> {ttl ? `${ttl} 天` : '永久'}</div>
                  <div className={`memory-guard ${trust === 'untrusted' ? 'warn' : ''}`}>{guardHint}</div>
                </div>
              )}
              <div className="grid cols-2" style={{ gap: 10 }}>
                <Field label="作用域">
                  <select value={scope} onChange={(e) => setScope(e.target.value)}>
                    {SCOPES.map((s) => (<option key={s} value={s}>{SCOPE_LABELS[s] ?? s}</option>))}
                  </select>
                </Field>
                <Field label="记忆类型">
                  <select value={memType} onChange={(e) => setMemType(e.target.value)}>
                    {TYPES.map((t) => (<option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>))}
                  </select>
                </Field>
              </div>
              <div className="grid cols-2" style={{ gap: 10 }}>
                <Field label="来源可信度">
                  <select value={trust} onChange={(e) => setTrust(e.target.value)}>
                    <option value="trusted">可信（用户明确表达）</option>
                    <option value="untrusted">不可信（自动提炼）</option>
                  </select>
                </Field>
                <Field label="TTL 天数（可选）">
                  <input type="number" min={1} value={ttl} onChange={(e) => setTtl(e.target.value)} placeholder="到期自动失效" />
                </Field>
              </div>
              <Field label="来源（可选）">
                <input value={source} onChange={(e) => setSource(e.target.value)} placeholder="console / doc-xxx" />
              </Field>
              <Button tone="primary" disabled={busy || !content.trim() || !can('memory:write')} className="mt">
                {busy ? '写入中…' : '写入'}
              </Button>
            </form>
          </Card>
        </div>
      </div>

      {detail && (
        <Sheet open={!!detail} onOpenChange={(o) => !o && setDetail(null)}>
      <SheetContent side="right" className="w-[480px] max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>记忆详情</SheetTitle>
        </SheetHeader>
        <div className="px-4">
          <div className="memory-detail">
            <div className="memory-card-head">
              <span className={`memory-trust ${detail.source_trust === 'trusted' ? 'ok' : 'warn'}`}>{TRUST_LABELS[detail.source_trust] ?? detail.source_trust}</span>
              <Badge status={detail.memory_type}>{TYPE_LABELS[detail.memory_type] ?? detail.memory_type}</Badge>
            </div>
            <div className="memory-detail-content">{detail.content}</div>
            <div className="memory-detail-meta">
              <div className="memory-preview-line"><b>记忆 ID</b> <span className="mono small">{detail.memory_id}</span></div>
              <div className="memory-preview-line"><b>作用域</b> {SCOPE_LABELS[detail.scope] ?? detail.scope}</div>
              <div className="memory-preview-line"><b>来源</b> {detail.source ? `${detail.source}（${SOURCE_LABELS[detail.source] ?? '未知'}）` : '—'}</div>
              <div className="memory-preview-line"><b>创建时间</b> {fmtTime(detail.created_at)}</div>
              <div className="memory-preview-line"><b>置信度</b> {(detail.confidence ?? 0).toFixed(2)}{detail.score !== undefined ? ` · 本次召回相关度 ${detail.score.toFixed(2)}` : ''}</div>
            </div>
            <div className="memory-detail-affect">这条记忆可能影响：召回命中时作为上下文注入 Agent 的回答，删除后相关内容将不再被召回。</div>
            <div className="row mt">
              <Button tone="danger" onClick={() => { remove(detail); setDetail(null) }}>删除这条记忆</Button>
              <Button onClick={() => setDetail(null)}>关闭</Button>
            </div>
          </div>
                </div>
      </SheetContent>
    </Sheet>
      )}
    </div>
  )
}
