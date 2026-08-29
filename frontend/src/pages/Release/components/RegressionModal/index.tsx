import { Badge, Button, Modal } from '@/components'
import { EmptyState } from '@/components/Page'
import { Regression } from '@/services'

export default function RegressionModal({ version, data, onClose }: { version: number; data: Regression; onClose: () => void }) {
  const rate = (data.pass_rate ?? 0) * 100
  const prev = data.previous_pass_rate
  const delta = prev === null || prev === undefined ? null : rate - prev * 100
  const prevTxt = prev === null || prev === undefined ? '无历史基线' : `${(prev * 100).toFixed(0)}%`
  const cases = data.cases ?? []
  return (
    <Modal title={`基准集回归 · v${version}（BADCASES / GOLDEN）`} onClose={onClose}>
      <div className="row mb">
        <span>
          通过率 <b className="mono">{rate.toFixed(0)}%</b>
          <span className="muted small">
            （{data.passed}/{data.total} 通过 · 完成 {data.completed}/{data.total}）
          </span>
        </span>
        <span className="muted small">上一版本 {prevTxt}</span>
        {delta !== null ? (
          <Badge status={data.regressed ? 'fail' : 'pass'}>
            {data.regressed ? `质量回退 ${delta.toFixed(0)}pt` : `对比 ${delta >= 0 ? '+' : ''}${delta.toFixed(0)}pt`}
          </Badge>
        ) : (
          <span className="small muted">（首条回归记录，尚无对比基线）</span>
        )}
      </div>
      {data.regressed && (
        <div className="error-box mb">
          通过率低于上一版本，发布会被回归门禁阻断（RELEASE_REGRESSION_FAILED）。请先修复质量问题；确属误判可到「发布引导」勾选强制发布跳过门禁。
        </div>
      )}
      {cases.length === 0 ? (
        <EmptyState
          title="该版本没有可回归的评测样例"
          desc="先到「效果评测」页录入坏案例 / 黄金集 / 对抗样例，再回来运行回归。"
        />
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>问题</th>
              <th>状态</th>
              <th>判定</th>
              <th>实际工具</th>
              <th>期望工具</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => (
              <tr key={i}>
                <td className="small">{c.query}</td>
                <td>
                  <Badge status={c.state} />
                </td>
                <td>
                  <Badge status={c.ok ? 'pass' : 'fail'} />
                </td>
                <td className="small mono">{c.tool_calls?.join(' → ') || '—'}</td>
                <td className="small mono">{c.expected_tool_calls?.join(' → ') || '—'}</td>
                <td className="small muted">
                  {c.forbidden_calls && c.forbidden_calls.length > 0 ? `禁调 ${c.forbidden_calls.join(', ')}；` : ''}
                  {c.judge_note || ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row mt">
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}
