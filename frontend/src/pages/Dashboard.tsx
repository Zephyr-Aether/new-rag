import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, HealthHA, Meta, ModelConfig, Run, Version } from '../api'
import { Badge, Card, Empty, fmtTime, shortId, TableSkeleton } from '../components/ui'
import { PageHeader } from '../components/Page'

type DocRow = {
  document_id: string
  title: string
  source_uri: string
  status: string
  created_at?: string
}

export default function Dashboard() {
  const [health, setHealth] = useState<HealthHA | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [cfg, setCfg] = useState<ModelConfig | null>(null)
  const [kbCount, setKbCount] = useState(0)
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [docs, setDocs] = useState<DocRow[] | null>(null)
  const [versions, setVersions] = useState<Version[] | null>(null)

  useEffect(() => {
    let alive = true
    api.health().then((r) => alive && setHealth(r)).catch(() => undefined)
    api.meta().then((r) => alive && setMeta(r)).catch(() => undefined)
    api.modelConfig().then((r) => alive && setCfg(r)).catch(() => undefined)
    api.kbBases().then((r) => alive && setKbCount(r.bases.length)).catch(() => undefined)
    api.listRuns(10).then((r) => alive && setRuns(r.runs)).catch(() => undefined)
    api.documents().then((r) => alive && setDocs(r.rows)).catch(() => undefined)
    return () => {
      alive = false
    }
  }, [])

  // 版本列表需要 agent_id，等 meta 回包后再拉
  useEffect(() => {
    if (!meta) return
    api.versions(meta.agent_id).then((r) => setVersions(r.versions)).catch(() => setVersions([]))
  }, [meta])

  const modelReady = !!cfg && !cfg.is_mock
  const kbReady = kbCount > 0
  const platformReady = health?.ready === true
  const hasRuns = (runs?.length ?? 0) > 0
  const hasCompletedRun = runs?.some((r) => r.state === 'COMPLETED') ?? false

  const recentRuns = (runs ?? []).slice(0, 3)
  const recentDocs = (docs ?? []).slice(0, 3)
  const recentVersions = versions ? [...versions].sort((a, b) => b.version - a.version).slice(0, 3) : null

  // 主路径：5 个里程碑。当前未完成的一步 = 首页唯一的主行动。
  const STEPS = [
    { label: '接模型', done: modelReady, to: '/settings', cta: '去接入模型', text: '先接入真实模型（或用内置模拟先跑通），对话和任务才有引擎。' },
    { label: '导知识', done: kbReady, to: '/knowledge', cta: '去导入知识', text: '导入第一份资料，Agent 才能基于你的内容回答。' },
    { label: '对话验证', done: hasRuns, to: '/chat', cta: '去开始对话', text: '发起一次对话或任务，确认从检索到回答的整条链路是通的。' },
    { label: '评测', done: hasCompletedRun, to: '/evaluation', cta: '去效果评测', text: '用评测样例给当前版本把关，再决定是否放量。' },
    { label: '发布', done: (recentVersions?.length ?? 0) > 0, to: '/release', cta: '去版本发布', text: '做灰度与发布决策，把稳定版本推向线上。' },
  ]
  const currentStep = STEPS.find((s) => !s.done)
  const hint = currentStep
    ? { label: currentStep.label, text: currentStep.text, to: currentStep.to, cta: currentStep.cta }
    : { label: '全部就绪', text: '五步都走通了：从一次对话开始今天的工作，或直接进入评测发布做放量决策。', to: '/chat', cta: '去开始对话' }
  const loading = cfg === null && meta === null && runs === null

  return (
    <div className="grid" style={{ gap: 18 }}>
      <PageHeader
        title="工作台"
        desc="接模型 → 导知识 → 对话验证 → 评测 → 发布。首页只回答两件事：现在到哪一步了、下一步点什么。"
      />

      {/* 主路径引导页：一个主行动 + 一条进度链，不再堆平行卡片 */}
      <Card title="主路径 · 现在到哪一步了">
        {loading ? (
          <p className="muted small">正在读取平台状态…</p>
        ) : (
          <>
            <div className="home-hint">
              <div className="home-hint-copy">
                <span className="home-hint-kicker">下一步：{hint.label}</span>
                <span>{hint.text}</span>
              </div>
              <Link className="btn primary" to={hint.to}>{hint.cta}</Link>
            </div>
            <div className="home-path">
              {STEPS.map((s) => (
                <Link key={s.label} className={`home-path-step${s.done ? ' done' : ''}`} to={s.to}>
                  <span className="home-path-dot">{s.done ? '✓' : '•'}</span>
                  <span>{s.label}</span>
                </Link>
              ))}
            </div>
            <div className="row small muted mt">
              <span>模型 {modelReady ? '已接入' : '模拟'}</span>
              <span>· 知识 {kbCount} 个库</span>
              <span>· 平台 {platformReady ? '正常' : '连接中'}</span>
              {health && <span>· 队列水位 {Math.round(health.queue_watermark * 100)}%</span>}
            </div>
          </>
        )}
      </Card>

      {/* 最近发生：辅助信息，降权展示，不看也不影响走主路径 */}
      <div className="grid cols-3">
        <Card title="最近任务">
          {runs === null ? (
            <TableSkeleton rows={3} cols={2} />
          ) : recentRuns.length === 0 ? (
            <Empty text="还没有任务，去发起第一次对话验证吧" />
          ) : (
            <>
              {recentRuns.map((r) => (
                <div key={r.run_id} className="recent-item">
                  <div className="recent-main">
                    <div className="recent-title">
                      <Link className="link" to={`/runs/${r.run_id}`}>{shortId(r.run_id)}</Link> <Badge status={r.state} />
                    </div>
                    <div className="recent-sub">{r.input ? r.input.slice(0, 40) : '—'}</div>
                  </div>
                  <div className="recent-right">{fmtTime(r.started_at)}</div>
                </div>
              ))}
              <Link className="recent-more" to="/runs">查看全部任务 →</Link>
            </>
          )}
        </Card>

        <Card title="最近导入">
          {docs === null ? (
            <TableSkeleton rows={3} cols={2} />
          ) : recentDocs.length === 0 ? (
            <Empty text="还没有文档，上传第一份资料吧" />
          ) : (
            <>
              {recentDocs.map((d) => (
                <div key={d.document_id} className="recent-item">
                  <div className="recent-main">
                    <div className="recent-title">{d.title || shortId(d.document_id)}</div>
                    <div className="recent-sub"><Badge status={d.status} /></div>
                  </div>
                  <div className="recent-right">{fmtTime(d.created_at)}</div>
                </div>
              ))}
              <Link className="recent-more" to="/knowledge">去知识库 →</Link>
            </>
          )}
        </Card>

        <Card title="最近发布">
          {recentVersions === null ? (
            <TableSkeleton rows={3} cols={2} />
          ) : recentVersions.length === 0 ? (
            <Empty text="还没有发过版本" />
          ) : (
            <>
              {recentVersions.map((v) => (
                <div key={v.version} className="recent-item">
                  <div className="recent-main">
                    <div className="recent-title">
                      <span className="mono">v{v.version}</span> <Badge status={v.status} />
                    </div>
                    <div className="recent-sub">{v.model}</div>
                  </div>
                  <div className="recent-right">{fmtTime(v.created_at)}</div>
                </div>
              ))}
              <Link className="recent-more" to="/release">去版本发布 →</Link>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}