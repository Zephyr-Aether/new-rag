import type { ReactNode } from 'react'
import { Badge, Button, Modal } from '@/components'
import { fmtCost } from '@/components'
import { CanaryCheck } from '@/services'

export default function CanaryModal({
  version,
  data,
  onClose,
  onHalt,
  onRollback,
}: {
  version: number
  data: CanaryCheck
  onClose: () => void
  onHalt: () => void
  onRollback: () => void
}) {
  const m = data.metrics
  const cell = (label: string, value: ReactNode, warn: boolean) => (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value" style={{ color: warn ? 'var(--red)' : undefined, fontSize: 18 }}>{value}</div>
    </div>
  )
  return (
    <Modal title={`Canary 检查 · v${version}`} onClose={onClose}>
      <div className="row" style={{ marginBottom: 12 }}>
        <span>
          结论 <Badge status={data.action === 'stop' ? 'FAILED' : 'PASSED'} />
        </span>
        <span className="small muted">{data.reasons.join(' · ')}</span>
      </div>
      <div className="grid cols-4" style={{ gap: 12 }}>
        {cell('错误率', m.error_rate.toFixed(3), m.error_rate > 0.1)}
        {cell('平均延迟', `${m.avg_latency_s.toFixed(1)}s`, m.avg_latency_s > 30)}
        {cell('工具成功率', m.tool_success_rate === null ? '—' : m.tool_success_rate.toFixed(3), (m.tool_success_rate ?? 1) < 0.9)}
        {cell('RAG recall', m.rag_recall === null ? '—' : m.rag_recall.toFixed(3), (m.rag_recall ?? 1) < 0.3)}
        {cell('LLM 429', m.llm_429_rate.toFixed(3), m.llm_429_rate > 0.2)}
        {cell('负面反馈', m.negative_feedback, m.negative_feedback >= 3)}
        {cell('成本', fmtCost(m.avg_cost), m.avg_cost > 1)}
        {cell('runs', m.runs, false)}
      </div>
      <div className="row mt">
        <Button tone="danger" disabled={data.action !== 'stop'} onClick={onHalt}>停用灰度</Button>
        <Button disabled={data.action !== 'stop'} onClick={onRollback}>回滚</Button>
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}
