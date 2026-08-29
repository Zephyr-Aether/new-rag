import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { ArrowRight, Info } from 'lucide-react'
import { api } from '@/api'
import { Badge, Button, Card, ErrorBox, Field, fmtTime, Stat, SuccessBox, TableSkeleton } from '@/components/ui'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { EmptyState, FlowChain, PageError, PageHeader } from '@/components/Page'
import { CodeEditor } from '@/components/CodeEditor'
import { usePermissions } from '@/hooks/usePermissions'

const KINDS = ['GOLDEN', 'REGRESSION', 'BADCASES', 'ADVERSARIAL']

const KIND_LABELS: Record<string, string> = {
  BADCASES: '坏案例',
  GOLDEN: '黄金集',
  ADVERSARIAL: '对抗集',
  REGRESSION: '回归集',
}

const KIND_DESC: Record<string, string> = {
  BADCASES: '线上跑挂 / 答错的失败样本，用于回归防退化',
  GOLDEN: '人工标注的高质量标准问答，作为评测的黄金标准',
  ADVERSARIAL: '对抗性 / 注入攻击样例，测试安全与鲁棒性',
  REGRESSION: '历史回归样本集，用于对比新版本是否质量回退',
}

const PARAM_DESC: [string, string][] = [
  ['query', '必填，评测问题'],
  ['kind', '数据集类型：BADCASES / GOLDEN / ADVERSARIAL / REGRESSION'],
  ['category', '场景分类：kb / math / security / refund / after-sale / tech 等'],
  ['reason', '为什么这条样例重要，方便后续做回归解释'],
  ['expected', '期望答案关键词（数组），全部命中才算通过'],
  ['expected_tool_calls', '期望按序调用的工具（数组），如 kb.search'],
  ['must_not_call', '禁用工具（数组），调用即判失败，如 http.get'],
  ['judge_type', '判定方式：keyword 关键词 / llm LLM 判定（需接真 LLM）'],
  ['answer', '参考答案，LLM 判定时的评分基准'],
  ['contexts / metadata', '预留：参考上下文 / 元信息'],
]

const CATEGORY_LABELS: Record<string, string> = {
  kb: '知识库',
  math: '数学',
  security: '安全',
  refund: '退款',
  sentiment: '情感',
  'after-sale': '售后',
  tech: '技术',
  general: '通用',
}

const EVAL_ACTIONS = [
  { title: '补评测再发布', desc: '先把黄金集和回归集补齐，再回到发布页。', to: '/release' },
  { title: '看模型健康', desc: '确认底座稳定后，再决定要不要放量。', to: '/model' },
  { title: '回到总览', desc: '先看当前项目的整体就绪状态。', to: '/' },
]

export default function Evaluation() {
  const { can } = usePermissions()
  const [kind, setKind] = useState('GOLDEN')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [reason, setReason] = useState('')
  const [category, setCategory] = useState('')
  const [expected, setExpected] = useState('')
  const [toolCalls, setToolCalls] = useState('')
  const [mustNotCall, setMustNotCall] = useState('')
  const [judgeType, setJudgeType] = useState('keyword')
  const [cfgMsg, setCfgMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [cfgBusy, setCfgBusy] = useState(false)
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [seedCfg, setSeedCfg] = useState('')
  const [seedSource, setSeedSource] = useState('')

  const { data, loading, error, run } = useRequest((k: string) => api.evalCases(k), { defaultParams: ['BADCASES'] as [string] })
  const rows = data?.rows ?? null
  const initialLoading = loading && rows === null
  const refreshing = loading && rows !== null
  const countsReq = useRequest(
    () => Promise.all(KINDS.map((k) => api.evalCases(k).then((r) => [k, r.total] as const))),
    { onSuccess: (arr) => setCounts(Object.fromEntries(arr)) },
  )
  useRequest(() => api.evalSeedConfig(), {
    onSuccess: (r) => {
      setSeedCfg(JSON.stringify(r.cases, null, 2))
      setSeedSource(r.source || '未知来源')
    },
  })

  const refresh = (k = kind) => {
    run(k)
    countsReq.run()
  }

  async function saveSeedConfig() {
    setCfgBusy(true)
    setCfgMsg(null)
    try {
      let parsed: unknown
      try {
        parsed = JSON.parse(seedCfg)
      } catch {
        setCfgMsg({ kind: 'err', text: 'JSON 格式有误，请检查后重试' })
        return
      }
      if (!Array.isArray(parsed)) {
        setCfgMsg({ kind: 'err', text: '配置应为 JSON 数组' })
        return
      }
      await api.evalSeedConfigSet(parsed as Record<string, unknown>[])
      const r = await api.evalSeed()
      setCfgMsg({ kind: 'ok', text: `已保存并应用：新增 ${r.added} 条，更新 ${r.updated} 条，跳过重复 ${r.skipped} 条` })
      refresh()
    } catch (e) {
      setCfgMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setCfgBusy(false)
    }
  }

  async function add() {
    if (!query.trim()) return
    setBusy(true)
    setMsg(null)
    try {
      await api.addEvalCase({
        query: query.trim(),
        kind,
        reason: reason.trim() || undefined,
        category: category.trim() || undefined,
        judge_type: judgeType,
        expected: expected ? expected.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
        expected_tool_calls: toolCalls ? toolCalls.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
        must_not_call: mustNotCall ? mustNotCall.split(',').map((s) => s.trim()).filter(Boolean) : undefined,
      })
      setMsg({ kind: 'ok', text: '已录入样例' })
      setQuery('')
      setReason('')
      setCategory('')
      setToolCalls('')
      setMustNotCall('')
      setExpected('')
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const testTotal = KINDS.reduce((a, k) => a + (counts[k] ?? 0), 0)
  const goldenCount = counts.GOLDEN ?? 0
  const regressionCount = counts.REGRESSION ?? 0
  const adversarialCount = counts.ADVERSARIAL ?? 0
  const badcaseCount = counts.BADCASES ?? 0
  const gateReady = goldenCount > 0 && regressionCount > 0
  const selectedCount = counts[kind] ?? 0
  const testAdvice =
    testTotal === 0
      ? '测试集还是空的：先录入第一条样例，或展开“种子同步”批量导入。'
      : gateReady
        ? `门禁基础已经齐了：黄金集 ${goldenCount} 条、回归集 ${regressionCount} 条，坏案例 ${badcaseCount} 条、对抗集 ${adversarialCount} 条。可以去发布页跑契约、回归和灰度。`
        : `当前已有 ${testTotal} 条样例，但门禁还不够完整：建议先补齐黄金集和回归集，再把坏案例 ${badcaseCount} 条、对抗集 ${adversarialCount} 条补上。`

  return (
    <div className="grid" style={{ gap: 18 }}>
      {error && <PageError message={(error as Error).message} retry={() => refresh()} />}

      <FlowChain current="evaluation" />
      <PageHeader
        title="评测"
        desc="这一步负责设门禁：补齐样例形成门禁，只有通过的版本才允许放量发布。"
        actions={
          <>
            <Link className="btn" to="/model">
              看模型健康
            </Link>
            <Link className="btn primary" to="/release">
              去发布
            </Link>
          </>
        }
      />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">评测门禁</span>
          <span>{testAdvice}</span>
          <span className="small muted" style={{ color: 'var(--text-2)' }}>
            当前最重要的是补出能拦住回退的样例，而不是把配置做得更长。
          </span>
        </div>
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <Link className="btn" to="/release">
            <span className="row" style={{ gap: 6 }}>
              去看发布 <ArrowRight size={14} />
            </span>
          </Link>
          <Link className="btn" to="/model">
            <span className="row" style={{ gap: 6 }}>
              看健康页 <ArrowRight size={14} />
            </span>
          </Link>
        </div>
      </div>

      <div className="grid cols-3">
        <Stat label="样例总数" value={testTotal} sub="四类样例合计，直接决定门禁厚度" />
        <Stat label="黄金 + 回归" value={`${goldenCount} / ${regressionCount}`} sub="发版时优先看这两类" />
        <Stat
          label="是否可发布"
          value={<Badge status={gateReady ? 'OK' : 'WARN'}>{gateReady ? '可发布' : '需补样'}</Badge>}
          sub={
            gateReady
              ? '门禁已过：可以去发布页跑契约、回归和灰度'
              : '门禁未过：先补齐黄金集和回归集'
          }
        />
      </div>

      <Card title="门禁摘要">
          {initialLoading ? (
            <TableSkeleton rows={2} cols={4} />
          ) : (
            <>
              <div className="status-grid">
              {KINDS.map((k) => (
                <div key={k} className="status-row">
                  <span className="status-label">{KIND_LABELS[k] ?? k}</span>
                  <span className="status-value">
                    <b>{counts[k] ?? 0}</b> 条
                  </span>
                </div>
              ))}
              <div className="status-row">
                <span className="status-label">门禁状态</span>
                <span className="status-value">
                  <Badge status={gateReady ? 'OK' : 'WARN'}>{gateReady ? '可发布' : '需补样'}</Badge>
                </span>
              </div>
            </div>
            <div className="small muted" style={{ marginTop: 12, lineHeight: 1.6 }}>
              {testAdvice}
            </div>
          </>
        )}
      </Card>

      <div className="grid cols-2" style={{ alignItems: 'start' }}>
        <div className="grid" style={{ gap: 16 }}>
          <Card
            title={
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                样例库 · {KIND_LABELS[kind] ?? kind}
                <TooltipProvider>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info size={14} style={{ color: 'var(--text-3)', cursor: 'help' }} />
                    </TooltipTrigger>
                    <TooltipContent>{KIND_DESC[kind] ?? ''}</TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </span>
            }
          >
            <div className="small muted" style={{ marginBottom: 10 }}>
              当前分类有 <b>{selectedCount}</b> 条样例，点下面的分类条即可切换。
            </div>
            <div className="grid cols-2" style={{ gap: 10, marginBottom: 14 }}>
              {KINDS.map((k) => (
                <button
                  key={k}
                  className={`action-tile stat-link ${kind === k ? 'recommended' : ''}`}
                  onClick={() => {
                    setKind(k)
                    refresh(k)
                  }}
                >
                  <div className="stat">
                    <div className="label" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                      <span>{KIND_LABELS[k] ?? k}</span>
                      <Badge status={(counts[k] ?? 0) > 0 ? 'OK' : 'WARN'}>{counts[k] ?? 0} 条</Badge>
                    </div>
                    <div className="sub">{KIND_DESC[k]}</div>
                  </div>
                </button>
              ))}
            </div>
            {refreshing && (
              <div className="small muted" style={{ margin: '-2px 0 10px' }}>
                正在切换到 <b>{KIND_LABELS[kind] ?? kind}</b>，先保留当前列表。
              </div>
            )}
            {initialLoading ? (
              <TableSkeleton rows={5} cols={5} />
            ) : (rows ?? []).length === 0 ? (
              <EmptyState
                title="该数据集还没有样例"
                desc="先在右侧录入样例，或展开高级种子同步批量导入。发布前最好先补一条黄金集和一条回归集。"
                actions={
                  <div className="empty-state-actions">
                    <Link className="btn primary" to="/release">
                      去发布
                    </Link>
                    <Link className="btn" to="/model">
                      看模型健康
                    </Link>
                  </div>
                }
              />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>问题</th>
                    <th>期望工具</th>
                    <th>判定</th>
                    <th>原因</th>
                    <th>分类</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {(rows ?? []).map((c) => (
                    <tr key={c.case_id}>
                      <td className="small">{c.query}</td>
                      <td className="small">
                        {c.expected_tool_calls && c.expected_tool_calls.length > 0 ? (
                          <span className="muted mono" style={{ fontSize: 11 }}>
                            {c.expected_tool_calls.join(' → ')}
                          </span>
                        ) : (
                          '—'
                        )}
                      </td>
                      <td className="small muted">{c.judge_type === 'llm' ? 'LLM 判定' : '关键词'}</td>
                      <td className="small muted">{c.reason || '—'}</td>
                      <td className="small muted">{c.category ? CATEGORY_LABELS[c.category] ?? c.category : '—'}</td>
                      <td className="mono small muted">{fmtTime(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <div className="grid cols-3">
            {EVAL_ACTIONS.map((a) => (
              <Link key={a.to} className="stat-link action-tile" to={a.to}>
                <div className="stat">
                  <div className="label">{a.title}</div>
                  <div className="sub">{a.desc}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>

        <div className="grid" style={{ gap: 16 }}>
          <Card title="录入样例">
            <div className="small muted" style={{ marginBottom: 10 }}>
              当前在 <b>{KIND_LABELS[kind] ?? kind}</b> 分类下录入，保存后会回到当前数据集。
            </div>
            <Field label="数据集类型">
              <select value={kind} onChange={(e) => setKind(e.target.value)}>
                {KINDS.map((k) => (
                  <option key={k} value={k}>
                    {KIND_LABELS[k] ?? k}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="问题">
              <textarea value={query} onChange={(e) => setQuery(e.target.value)} placeholder="评测问题 / 注入用例" />
            </Field>
            <Field label="原因">
              <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="这条样例为什么重要" />
            </Field>
            <Field label="期望关键词（逗号分隔，可选）">
              <input value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="42, 退款" />
            </Field>
            <details className="eval-advanced">
              <summary>更多字段（高级）</summary>
              <div className="small muted eval-advanced-note">
                场景分类、工具调用、判定方式等，首次补样例用不上可以先不填。
              </div>
              <Field label="场景分类">
                <select value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">未分类</option>
                  {Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="期望工具调用（逗号分隔，可选）">
                <input value={toolCalls} onChange={(e) => setToolCalls(e.target.value)} placeholder="kb.search, calc.add" />
              </Field>
              <Field label="禁用工具（逗号分隔，可选）">
                <input value={mustNotCall} onChange={(e) => setMustNotCall(e.target.value)} placeholder="http.get, shell.exec" />
              </Field>
              <Field label="判定方式">
                <select value={judgeType} onChange={(e) => setJudgeType(e.target.value)}>
                  <option value="keyword">关键词匹配</option>
                  <option value="llm">LLM 判定（需接真 LLM）</option>
                </select>
              </Field>
            </details>
            <Button tone="primary" disabled={busy || !query.trim() || !can('eval:write')} onClick={add} className="mt">
              录入样例
            </Button>
            {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
          </Card>

          <Card title="种子同步">
            <div className="small muted" style={{ marginBottom: 10 }}>
              仅在需要批量导入时打开。来源：<code>{seedSource || '加载中…'}</code>
            </div>
            <details className="eval-advanced">
              <summary>种子配置（高级）</summary>
              <div className="small muted eval-advanced-note">
                这里按 <code>query + kind</code> upsert，同步前先确认数组内容是你想让平台长期保留的那批样例。
              </div>
              <CodeEditor value={seedCfg} onChange={setSeedCfg} />
              <div className="eval-param-box">
                <div className="eval-param-title">参数说明</div>
                {PARAM_DESC.map(([k, v]) => (
                  <div key={k} className="eval-param-row">
                    <code className="eval-param-key">{k}</code>
                    <span className="muted small">{v}</span>
                  </div>
                ))}
              </div>
              <div className="row mt">
                <Button tone="primary" disabled={cfgBusy || !can('eval:write')} onClick={saveSeedConfig}>
                  {cfgBusy ? '保存并应用中…' : '保存并应用'}
                </Button>
                <span className="small muted">保存到配置中心并同步导入评测集（按 query + kind 去重）</span>
              </div>
              {cfgMsg && <div className="mt">{cfgMsg.kind === 'ok' ? <SuccessBox message={cfgMsg.text} /> : <ErrorBox message={cfgMsg.text} />}</div>}
            </details>
          </Card>
        </div>
      </div>
    </div>
  )
}
