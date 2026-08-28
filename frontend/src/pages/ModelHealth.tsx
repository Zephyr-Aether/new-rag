import { Link } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { api, ModelHealthEntry } from '../api'
import { Badge, Card, TableSkeleton } from '../components/ui'
import { EmptyState, PageError, PageHeader } from '../components/Page'

type HealthDecision = {
  badge: 'OK' | 'WARN' | 'FAIL'
  label: string
  note: string
}

function assessModel(model: ModelHealthEntry): HealthDecision {
  const status = model.status.toLowerCase()
  const severe =
    status.includes('fail') ||
    status.includes('down') ||
    status.includes('open') ||
    model.error_rate >= 0.05 ||
    model.rate_429 >= 0.05 ||
    model.latency_p95_ms >= 3000
  const warn =
    !severe &&
    (status.includes('warn') ||
      status.includes('degrad') ||
      status.includes('half') ||
      model.error_rate > 0 ||
      model.rate_429 > 0 ||
      model.latency_p95_ms >= 1500)

  if (severe) {
    return { badge: 'FAIL', label: '需降级', note: '优先降权或切到降级链，避免继续把流量打到不稳节点。' }
  }

  if (warn) {
    return { badge: 'WARN', label: '需关注', note: '建议继续观察并保留回退路线，确认问题没有放大。' }
  }

  return { badge: 'OK', label: '可放量', note: '当前模型路由可继续放量。' }
}

export default function ModelHealth() {
  const { data, loading, error, refresh } = useRequest(() => api.modelHealth())
  const models = data?.models ?? null
  const breaker = data?.breaker

  const assessed = (models ?? []).map((m) => ({ model: m, decision: assessModel(m) }))
  const healthy = assessed.filter((row) => row.decision.badge === 'OK')
  const watch = assessed.filter((row) => row.decision.badge === 'WARN')
  const critical = assessed.filter((row) => row.decision.badge === 'FAIL')
  const topConcern = critical[0] ?? watch[0] ?? null
  const topHealthy = healthy[0] ?? null

  const summary =
    !models || models.length === 0
      ? {
          badge: 'WARN',
          title: '还没有模型健康结论',
          note: '先接入真实模型并跑几次任务，这里才会出现可放量、需关注或需降级的判断。',
          chips: ['暂无健康样本'],
        }
      : critical.length > 0
        ? {
            badge: 'FAIL',
            title: `当前不适合继续放量，优先处理 ${critical.length} 个高风险模型`,
            note: `建议先处理 ${topConcern?.model.model ?? '高风险模型'}，再决定是否继续发布或扩大流量。`,
            chips: [breaker ? `熔断器 ${breaker}` : '存在失败模型', `需降级 ${critical.length} 个`],
          }
        : watch.length > 0
          ? {
              badge: 'WARN',
              title: `当前可以观测运行，但仍有 ${watch.length} 个模型需要关注`,
              note: '先稳住当前流量，观察错误率、限流和延迟是否继续恶化，再决定要不要继续放量。',
              chips: [breaker ? `熔断器 ${breaker}` : '处在观察期', `需关注 ${watch.length} 个`],
            }
          : {
              badge: 'OK',
              title: '模型路由整体健康，可以继续放量',
              note: topHealthy ? `当前最稳定的是 ${topHealthy.model.model}，可以作为继续承载流量的主路由。` : '错误率、限流和延迟都处在低位。',
              chips: [breaker ? `熔断器 ${breaker}` : '路由正常', `可放量 ${healthy.length} 个`],
            }

  const advice =
    models && models.length > 0
      ? critical.length > 0
        ? `有 ${critical.length} 个模型建议先降级或降权；优先处理 ${critical[0]?.model.model ?? '高风险模型'}，再考虑继续放量。`
        : watch.length > 0
          ? `有 ${watch.length} 个模型处在观察期；建议先稳住流量，再去发布页确认是否可以放量。`
          : '模型路由整体健康：错误率与限流都在低位，可以继续放量。'
      : '还没有模型健康数据：接入模型并跑几次任务后，这里会展示每个模型的状态、风险等级与流量分配。'

  return (
    <div className="grid" style={{ gap: 18 }}>
      {error && <PageError message={(error as Error).message} retry={() => refresh()} />}

      <PageHeader
        title="模型健康"
        desc="先看可否放量，再决定是否降权、降级或保持现状。"
        actions={
          <>
            <Link className="btn" to="/settings">
              去接入模型
            </Link>
            <Link className="btn primary" to="/release">
              看发布链路
            </Link>
          </>
        }
      />

      <Card title="当前健康判断">
        <div className="decision-panel">
          <div className="decision-main">
            <div className="row" style={{ gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
              <Badge status={summary.badge} />
              <div className="decision-title">{summary.title}</div>
            </div>
            <div className="decision-note">{summary.note}</div>
            <div className="decision-list">
              {summary.chips.map((item) => (
                <span key={item} className="decision-chip">{item}</span>
              ))}
            </div>
            <div className="row mt" style={{ flexWrap: 'wrap' }}>
              <Link className="btn" to="/settings">
                去调配置
              </Link>
              <Link className="btn primary" to="/release">
                去看发布
              </Link>
            </div>
          </div>

          <div className="decision-side">
            <div className="decision-meta-row">
              <span className="decision-meta-label">可放量</span>
              <span className="decision-meta-value">{healthy.length} 个</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">需关注</span>
              <span className="decision-meta-value">{watch.length} 个</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">需降级</span>
              <span className="decision-meta-value">{critical.length} 个</span>
            </div>
            <div className="decision-meta-row">
              <span className="decision-meta-label">熔断器</span>
              <span className="decision-meta-value">{breaker || '—'}</span>
            </div>
          </div>
        </div>
      </Card>

      {models && models.length > 0 && (
        <div className="home-hint" style={{ marginBottom: 0 }}>
          <span>{advice}</span>
          <Link className="btn" to="/release">
            去看发布
          </Link>
        </div>
      )}

      <Card title="模型路由与状态">
        {loading ? (
          <TableSkeleton rows={5} cols={7} />
        ) : (models ?? []).length === 0 ? (
          <EmptyState title="暂无模型状态" desc="完成模型接入后，这里会列出每个模型的状态、风险等级与流量分配。" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>模型</th>
                <th>决策</th>
                <th>状态</th>
                <th className="num">错误率</th>
                <th className="num">429 率</th>
                <th className="num">P95 延迟</th>
                <th className="num">流量权重</th>
                <th>建议</th>
              </tr>
            </thead>
            <tbody>
              {assessed.map(({ model: m, decision }) => (
                <tr key={m.model}>
                  <td className="mono">{m.model}</td>
                  <td>
                    <Badge status={decision.badge} />
                  </td>
                  <td>
                    <Badge status={m.status} />
                  </td>
                  <td className="num">{m.error_rate}</td>
                  <td className="num">{m.rate_429}</td>
                  <td className="num">{m.latency_p95_ms}ms</td>
                  <td className="num">{m.traffic_weight.toFixed(2)}</td>
                  <td className="small muted">{decision.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="small muted mt">
          熔断器状态：{breaker ? <code>{breaker}</code> : '—'}（CLOSED=正常 / OPEN=熔断 / HALF_OPEN=试探）
        </p>
      </Card>
    </div>
  )
}
