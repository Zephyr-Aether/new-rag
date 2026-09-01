import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, HealthHA, Meta, ModelConfig, Run, Version } from '@/services'
import { Badge, Card, fmtTime, shortId, stateLabel } from '@/components'
import { PageHeader } from '@/components/Page'
import { ArrowRight, Database, FileText, Rocket, Server, SquareActivity } from 'lucide-react'

type DocRow = {
  document_id: string
  title: string
  source_uri: string
  status: string
  created_at?: string
}

type RecentItem = {
  key: string
  icon: ReactNode
  title: string
  sub: string
  time: string
  to: string
}

export default function Dashboard() {
  const [health, setHealth] = useState<HealthHA | null>(null)
  const [meta, setMeta] = useState<Meta | null>(null)
  const [cfg, setCfg] = useState<ModelConfig | null>(null)
  const [kbCount, setKbCount] = useState(0)
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [docs, setDocs] = useState<DocRow[] | null>(null)
  const [versions, setVersions] = useState<Version[] | null>(null)
  const [quotas, setQuotas] = useState<{ key: string; label: string; used: number; limit: number | null; percent: number | null; over: boolean }[] | null>(null)

  useEffect(() => {
    let alive = true
    api.health().then((r) => alive && setHealth(r)).catch(() => undefined)
    api.meta().then((r) => alive && setMeta(r)).catch(() => undefined)
    api.modelConfig().then((r) => alive && setCfg(r)).catch(() => undefined)
    api.kbBases().then((r) => alive && setKbCount(r.bases.length)).catch(() => undefined)
    api.listRuns(10).then((r) => alive && setRuns(r.runs)).catch(() => undefined)
    api.documents().then((r) => alive && setDocs(r.rows)).catch(() => undefined)
    api.costQuotas().then((r) => alive && setQuotas(r.quotas)).catch(() => setQuotas(null))
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
  const hasVersion = (versions?.length ?? 0) > 0

  // 主流程五步：当前未完成的一步 = 首页唯一的主行动，其余进步骤条，不并排摆卡片
  const STEPS = [
    { key: 'model', label: '接模型', done: modelReady, to: '/settings', cta: '去接入模型', title: '接上你的模型引擎', body: '对话、评测、发布都靠模型引擎跑。先接真实模型，或用内置模拟把流程走通，结果才可信。' },
    { key: 'knowledge', label: '导知识', done: kbReady, to: '/knowledge', cta: '去导入知识', title: '把资料喂给 Agent', body: '现在 Agent 还没有你的内容，问什么都答不准。导入第一份资料（产品手册、制度文档…），它才能基于你的东西回答。' },
    { key: 'chat', label: '对话验证', done: hasRuns, to: '/chat', cta: '去开始对话', title: '发一个问题，验证整条链路', body: '问一个真实业务问题，看它有没有检索到你的资料、回答靠不靠谱。不稳就先回去补知识。' },
    { key: 'evaluation', label: '评测门禁', done: hasCompletedRun, to: '/evaluation', cta: '去设门禁', title: '给版本立一道门禁', body: '补几条高质量问答样例，让每次发版前自动跑一遍，防止越改越差。' },
    { key: 'release', label: '发布', done: hasVersion, to: '/release', cta: '去版本发布', title: '把稳定版本放出去', body: '沿发布链路走：契约检查 → 回归评测 → 灰度放量 → 全量上线。出了问题还能一键回滚。' },
  ]
  const doneCount = STEPS.filter((s) => s.done).length
  const current = STEPS.find((s) => !s.done)
  const hero = current
    ? { step: current, index: STEPS.indexOf(current), allDone: false }
    : {
        step: { key: 'done', label: '全部完成', to: '/chat', cta: '去开始对话', title: '主线已经走通', body: '接模型、导知识、验证、门禁、发布都齐了。从一次对话开始今天的工作，或进发布页做放量决策。' },
        index: STEPS.length,
        allDone: true,
      }
  const loading = cfg === null && meta === null && runs === null
  const latestVersion = versions && versions.length > 0 ? versions.reduce((a, b) => (b.version > a.version ? b : a), versions[0]) : null

  const recentItems: RecentItem[] = []
  if (runs && runs.length > 0) {
    recentItems.push({
      key: `run-${runs[0].run_id}`,
      icon: <SquareActivity size={16} />,
      title: `任务 ${shortId(runs[0].run_id)}`,
      sub: `状态 ${stateLabel(runs[0].state)} · ${runs[0].steps} 步 · ${runs[0].tokens_in + runs[0].tokens_out} tokens`,
      time: fmtTime(runs[0].started_at),
      to: '/runs',
    })
  }
  if (docs && docs.length > 0) {
    recentItems.push({
      key: `doc-${docs[0].document_id}`,
      icon: <FileText size={16} />,
      title: `导入「${docs[0].title || '文档'}」`,
      sub: docs[0].source_uri || '—',
      time: fmtTime(docs[0].created_at),
      to: '/knowledge',
    })
  }
  if (latestVersion) {
    recentItems.push({
      key: `version-${latestVersion.version}`,
      icon: <Rocket size={16} />,
      title: `发布 v${latestVersion.version}`,
      sub: `${latestVersion.model || '默认模型'} · ${stateLabel(latestVersion.status)}`,
      time: fmtTime(latestVersion.created_at),
      to: '/release',
    })
  }

  const statusCards = [
    {
      key: 'model',
      icon: <Server size={15} />,
      label: '模型',
      value: modelReady ? '已接入' : '模拟中',
      sub: modelReady ? '真实模型已就绪' : '先把流程跑通',
    },
    {
      key: 'knowledge',
      icon: <Database size={15} />,
      label: '知识库',
      value: `${kbCount} 个`,
      sub: kbReady ? '可以开始检索' : '还没有导入内容',
    },
    {
      key: 'runs',
      icon: <SquareActivity size={15} />,
      label: '任务记录',
      value: hasRuns ? `${runs!.length} 条` : '暂无',
      sub: hasCompletedRun ? '已有完成任务' : '还没形成闭环',
    },
    {
      key: 'release',
      icon: <Rocket size={15} />,
      label: '发布版本',
      value: hasVersion ? `v${latestVersion!.version}` : '未发布',
      sub: latestVersion ? stateLabel(latestVersion.status) : '还没进入发布',
    },
  ]

  const canStart = platformReady && kbReady && (modelReady || cfg?.is_mock)

  return (
    <div className="grid" style={{ gap: 16 }}>
      <PageHeader
        title="首页"
        desc="这里只保留最关键的事：你现在该做哪一步，平台最近发生了什么。主线仍然是接模型、导知识、对话验证、评测门禁、发布。"
      />

      {loading ? (
        <p className="muted small">正在读取平台状态…</p>
      ) : (
        <>
          <div className="home-overview">
            <Card className="home-hero">
              <div className="home-hero-kicker">
                <span>{hero.allDone ? '主线完成' : `当前建议 · 第 ${hero.index + 1} 步`}</span>
                <Badge status={hero.allDone ? 'COMPLETED' : 'RUNNING'}>{hero.allDone ? '已走通' : '下一步'}</Badge>
              </div>
              <h1 className="home-hero-title">{hero.step.title}</h1>
              <p className="home-hero-body">{hero.step.body}</p>
              <div className="home-hero-actions">
                <Link className="btn primary home-hero-cta" to={hero.step.to}>
                  {hero.step.cta}
                  <ArrowRight size={14} />
                </Link>
                <div className="home-hero-foot small muted">
                  <span>模型 {modelReady ? '已接入' : '模拟'}</span>
                  <span>知识 {kbCount} 个库</span>
                  <span>平台 {platformReady ? '正常' : '连接中'}</span>
                </div>
              </div>
            </Card>

            <div className="home-status-grid">
              {statusCards.map((card) => (
                <Card key={card.key} className="home-stat">
                  <div className="home-stat-head">
                    <span className="home-stat-icon">{card.icon}</span>
                    <span className="home-stat-label">{card.label}</span>
                  </div>
                  <div className="home-stat-value">{card.value}</div>
                  <div className="home-stat-sub">{card.sub}</div>
                </Card>
              ))}
            </div>
          </div>

          <div className="grid cols-2 home-lower">
            <Card title="最近动态" className="home-list-card">
              {recentItems.length > 0 ? (
                <div className="home-recent-list">
                  {recentItems.map((item) => (
                    <Link key={item.key} className="home-recent-item" to={item.to}>
                      <span className="home-recent-icon">{item.icon}</span>
                      <span className="home-recent-main">
                        <span className="home-recent-title">{item.title}</span>
                        <span className="home-recent-sub">{item.sub}</span>
                      </span>
                      <span className="home-recent-time">{item.time}</span>
                    </Link>
                  ))}
                </div>
              ) : (
                <div className="home-empty">
                  <div className="home-empty-title">还没有历史动作</div>
                  <div className="home-empty-sub">先导入第一份知识，或去对话里跑一次真实问题。</div>
                  <div className="row" style={{ marginTop: 10 }}>
                    <Link className="link" to="/knowledge">去导知识</Link>
                    <Link className="link" to="/chat">去对话</Link>
                  </div>
                </div>
              )}
            </Card>

            <Card title="平台状态" className="home-panel-card">
              <div className="home-state-list">
                <div className="home-state-row">
                  <span className="home-state-label">建议节奏</span>
                  <span className="home-state-value">{canStart ? '现在可以开始验证主线' : '先把基础链路补齐'}</span>
                </div>
                <div className="home-state-row">
                  <span className="home-state-label">当前门槛</span>
                  <span className="home-state-value">{hero.step.title}</span>
                </div>
                <div className="home-state-row">
                  <span className="home-state-label">完成度</span>
                  <span className="home-state-value">{doneCount}/5</span>
                </div>
                <div className="home-state-row">
                  <span className="home-state-label">发布状态</span>
                  <span className="home-state-value">{hasVersion ? `已有 v${latestVersion!.version}` : '等待首个版本'}</span>
                </div>
              </div>
              {quotas && quotas.some((q) => q.limit != null) && (
                <div className="home-quota">
                  <div className="home-quota-title">配额用量</div>
                  {quotas.filter((q) => q.limit != null).map((q) => (
                    <div className="home-quota-row" key={q.key}>
                      <div className="home-quota-head">
                        <span className="home-quota-label">{q.label}</span>
                        <span className={`home-quota-value ${q.over ? 'over' : ''}`}>
                          {q.used.toLocaleString()} / {q.limit!.toLocaleString()}
                          {q.over && ' ⚠'}
                        </span>
                      </div>
                      <div className="home-quota-bar">
                        <div
                          className={`home-quota-fill ${q.over ? 'over' : ''}`}
                          style={{ width: `${Math.min((q.percent ?? 0), 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="home-panel-foot small muted">
                这个首页不承担分析工作，只负责告诉你现在该去哪一页。
              </div>
            </Card>
          </div>
        </>
      )}
    </div>
  )
}
