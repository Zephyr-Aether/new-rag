import { useState } from 'react'
import { Pagination } from '@/components/pagination'
import { Link, useNavigate } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { Info } from 'lucide-react'
import { api } from '@/services'
import { Badge, Button, Card, ErrorBox, Field, fmtTime, SuccessBox, TableSkeleton } from '@/components'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/tooltip'
import { EmptyState, FlowChain, PageError, PageHeader } from '@/components/Page'
import { CodeEditor } from '@/components/CodeEditor'
import { usePermissions } from '@/hooks/usePermissions'
import { toast } from '@/toast'

const PAGE_SIZE = 10

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
  const navigate = useNavigate()
  const [kind, setKind] = useState('GOLDEN')
  const [page, setPage] = useState(1)
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
  const runsReq = useRequest(async () => {
    const m = await api.meta()
    return api.regressionRuns(m.agent_id)
  })
  const evalRuns = runsReq.data?.runs ?? null

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
      toast('已录入样例')
      setQuery('')
      setReason('')
      setCategory('')
      setToolCalls('')
      setMustNotCall('')
      setExpected('')
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
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

  const missing = []
  if (goldenCount === 0) missing.push('黄金集')
  if (regressionCount === 0) missing.push('回归集')
  const verdict = testTotal === 0
    ? { status: '待补样本', ok: false, reason: '还没有任何评测样例，门禁无从谈起。', action: '先补第一条黄金集样例，再补回归集。' }
    : missing.length === 0
      ? { status: '通过', ok: true, reason: `黄金集 ${goldenCount} / 回归集 ${regressionCount} 已就位，坏案例 ${badcaseCount}、对抗集 ${adversarialCount}。`, action: '可以去发布页跑契约、回归和灰度。' }
      : { status: '待补样本', ok: false, reason: `门禁还缺 ${missing.join('、')}，当前 ${testTotal} 条样例撑不起稳定门禁。`, action: `先补${missing[0]}，再补${missing[1] ?? '坏案例'}。` }

  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  void verdict
  void scrollTo

  function downloadTemplate() {
    const tpl = [
      { query: '退货几天内到账？', kind: 'GOLDEN', category: 'refund', expected: ['3', '5'], reason: '示例黄金样例' },
      { query: '知识库: 退款政策', kind: 'REGRESSION', expected: [], reason: '示例回归样例' },
    ]
    const blob = new Blob([JSON.stringify(tpl, null, 2)], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'eval-template.json'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  const kindCards = KINDS.map((k) => ({
    key: k,
    label: KIND_LABELS[k] ?? k,
    desc: KIND_DESC[k] ?? '',
    count: counts[k] ?? 0,
    active: kind === k,
  }))

  return (
    <div className="grid evaluation-page" style={{ gap: 16 }}>
      {error && <PageError message={(error as Error).message} retry={() => refresh()} />}

      <FlowChain current="evaluation" />
      <PageHeader
        title="评测"
        desc="这一步只回答一件事：这版能不能发。先补样例，再看回归，够了再去发布。"
        actions={
          <>
            <Button onClick={() => scrollTo('eval-library')}>样例库</Button>
            <Button onClick={() => scrollTo('eval-input')}>补样本</Button>
            <Button onClick={() => scrollTo('eval-import')}>批量导入</Button>
            <Button tone="primary" onClick={() => navigate('/release')}>
              看发布页
            </Button>
          </>
        }
      />

      <Card className="evaluation-hero">
        <div className="evaluation-hero-main">
          <div className="evaluation-hero-kicker">评测门禁</div>
          <div className="evaluation-hero-title">这版能不能发？</div>
          <div className="evaluation-hero-copy">{verdict.reason}</div>
          <div className="evaluation-hero-action">建议：{verdict.action}</div>
          <div className="evaluation-hero-foot">
            <span>黄金集 {goldenCount}</span>
            <span>回归集 {regressionCount}</span>
            <span>坏案例 {badcaseCount}</span>
            <span>对抗集 {adversarialCount}</span>
            <span className={gateReady ? 'good' : 'warn'}>{gateReady ? '门禁已就绪' : '还需要补样'}</span>
          </div>
        </div>
        <div className="evaluation-hero-side">
          <div className="evaluation-hero-status">
            <Badge status={gateReady ? 'OK' : 'WARN'}>{gateReady ? '可发布' : '需补样'}</Badge>
            <div className="evaluation-hero-status-copy">
              <div className="evaluation-hero-status-title">当前样例 {testTotal} 条</div>
              <div className="evaluation-hero-status-sub">补齐黄金集和回归集后，再去发布页跑契约与灰度。</div>
            </div>
          </div>
          <div className="evaluation-hero-links">
            {EVAL_ACTIONS.map((a) => (
              <Link key={a.to} className="stat-link action-tile evaluation-hero-link" to={a.to}>
                <div className="stat">
                  <div className="label">{a.title}</div>
                  <div className="sub">{a.desc}</div>
                </div>
              </Link>
            ))}
          </div>
        </div>
      </Card>

      <div className="evaluation-layout">
        <div className="evaluation-main">
          <Card id="eval-library" title={
            <span className="evaluation-card-title">
              <span>样例库</span>
              <span className="evaluation-card-sub">当前分类 · {KIND_LABELS[kind] ?? kind}</span>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Info size={14} style={{ color: 'var(--text-3)', cursor: 'help' }} />
                  </TooltipTrigger>
                  <TooltipContent>{KIND_DESC[kind] ?? ''}</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </span>
          }>
            <div className="evaluation-library-head">
              <div className="small muted">
                当前分类有 <b>{selectedCount}</b> 条样例。切换分类后会自动刷新列表。
              </div>
              <Button onClick={() => refresh()} disabled={initialLoading || refreshing}>刷新当前分类</Button>
            </div>

            <div className="evaluation-kind-grid">
              {kindCards.map((item) => (
                <button
                  key={item.key}
                  className={`action-tile stat-link evaluation-kind-card${item.active ? ' recommended' : ''}`}
                  onClick={() => {
                    setKind(item.key)
                    setPage(1)
                    refresh(item.key)
                  }}
                >
                  <div className="stat">
                    <div className="label evaluation-kind-label">
                      <span>{item.label}</span>
                      <Badge status={item.count > 0 ? 'OK' : 'WARN'}>{item.count} 条</Badge>
                    </div>
                    <div className="sub">{item.desc}</div>
                  </div>
                </button>
              ))}
            </div>

            {refreshing && (
              <div className="evaluation-refreshing small muted">
                正在切换到 <b>{KIND_LABELS[kind] ?? kind}</b>，先保留当前列表。
              </div>
            )}

            {initialLoading ? (
              <TableSkeleton rows={5} cols={5} />
            ) : (rows ?? []).length === 0 ? (
              <EmptyState
                title="该数据集还没有样例"
                desc="先补一条样例让门禁开始生效，或者直接批量导入。发布前最好至少有一条黄金集和一条回归集。"
                actions={
                  <div className="empty-state-actions">
                    <Button tone="primary" onClick={() => scrollTo('eval-input')}>去录入</Button>
                    <Button onClick={() => scrollTo('eval-import')}>去导入</Button>
                    <Link className="btn" to="/model">看模型健康</Link>
                  </div>
                }
              />
            ) : (
              <>
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
                    {(rows ?? []).slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE).map((c) => (
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
                {(rows?.length ?? 0) > PAGE_SIZE && (
                  <div className="row mt" style={{ justifyContent: 'flex-end' }}>
                    <Pagination current={page} pageSize={PAGE_SIZE} total={rows?.length ?? 0} onChange={setPage} />
                  </div>
                )}
              </>
            )}
          </Card>

          <Card title="运行记录" className="evaluation-history-card">
            {runsReq.loading ? (
              <TableSkeleton rows={3} cols={4} />
            ) : evalRuns === null || evalRuns.length === 0 ? (
              <EmptyState
                title="还没有评测运行"
                desc="到发布页对草稿跑回归评测，这里会记录每次结果，以及和上一次的通过率差值。"
                actions={
                  <div className="empty-state-actions">
                    <Link className="btn primary" to="/release">去发布页跑回归</Link>
                  </div>
                }
              />
            ) : (
              <table className="tbl">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th className="num">通过率</th>
                    <th className="num">对比上次</th>
                    <th className="num">通过 / 样本</th>
                    <th>结果</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {evalRuns.map((r) => {
                    const delta = r.delta
                    const up = delta !== null && delta >= 0
                    const deltaLabel = delta === null ? '—' : `${up ? '+' : ''}${(delta * 100).toFixed(1)}%`
                    return (
                      <tr key={r.id}>
                        <td className="mono">v{r.agent_version}</td>
                        <td className="num">{Math.round((r.pass_rate ?? 0) * 100)}%</td>
                        <td className={`num mono ${delta === null ? '' : up ? 'eval-delta-up' : 'eval-delta-down'}`}>{deltaLabel}</td>
                        <td className="num">{r.passed}/{r.total}</td>
                        <td>
                          <Badge status={r.regressed ? 'FAIL' : 'PASS'}>{r.regressed ? '退化' : '正常'}</Badge>
                        </td>
                        <td className="mono small muted">{fmtTime(r.created_at)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
            <p className="small muted mt">与上一次运行对比：绿色为上升，红色为下降。跑回归在发布页的回归步骤里，失败样本定位也在那里。</p>
          </Card>
        </div>

        <div className="evaluation-rail">
          <Card title="录入样例" id="eval-input">
            <div className="small muted evaluation-copy">
              当前在 <b>{KIND_LABELS[kind] ?? kind}</b> 分类下录入，保存后会回到当前数据集。
            </div>
            <div className="evaluation-form-grid">
              <Field label="数据集类型">
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABELS[k] ?? k}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="判定方式">
                <select value={judgeType} onChange={(e) => setJudgeType(e.target.value)}>
                  <option value="keyword">关键词匹配</option>
                  <option value="llm">LLM 判定（需接真 LLM）</option>
                </select>
              </Field>
              <Field label="问题" className="evaluation-span-2">
                <textarea value={query} onChange={(e) => setQuery(e.target.value)} placeholder="评测问题 / 注入用例" />
              </Field>
              <Field label="原因" className="evaluation-span-2">
                <textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="这条样例为什么重要" />
              </Field>
              <Field label="期望关键词（逗号分隔，可选）" className="evaluation-span-2">
                <input value={expected} onChange={(e) => setExpected(e.target.value)} placeholder="42, 退款" />
              </Field>
            </div>
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
            </details>
            <Button tone="primary" disabled={busy || !query.trim() || !can('eval:write')} onClick={add} className="mt">
              录入样例
            </Button>
            
          </Card>

          <Card title="批量导入" id="eval-import">
            <div className="small muted evaluation-copy">
              样本大多不是手填出来的，导入更快。来源：<code>{seedSource || '加载中…'}</code>
            </div>
            <div className="row mb" style={{ gap: 8 }}>
              <Button onClick={downloadTemplate}>下载模板</Button>
              <span className="small muted">按模板填好后粘贴到下方，保存即按 query + kind upsert。</span>
            </div>
            <details className="eval-advanced">
              <summary>导入配置（JSON）</summary>
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
