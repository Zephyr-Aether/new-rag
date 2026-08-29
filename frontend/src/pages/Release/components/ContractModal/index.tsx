import { Button, Modal } from '@/components'
import { Badge } from '@/components'
import { ContractCheck } from '@/services'

export default function ContractModal({
  data,
  onClose,
  onEvaluate,
}: {
  data: ContractCheck
  onClose: () => void
  onEvaluate: () => void
}) {
  return (
    <Modal title={`发布契约检查 · v${data.version}`} onClose={onClose}>
      <div className="row" style={{ marginBottom: 14 }}>
        <span>
          总体 <Badge status={data.status} /> {data.blocked ? <b style={{ color: 'var(--red)' }}>（阻断发布）</b> : <span className="muted">（未阻断）</span>}
        </span>
        {data.needs_manual.length > 0 && (
          <span className="small muted">人工签核：{data.needs_manual.join('、')}</span>
        )}
      </div>
      <table className="tbl">
        <thead>
          <tr>
            <th>检查</th>
            <th>结果</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {data.checks.map((c) => (
            <tr key={c.id}>
              <td className="mono small">{c.id}</td>
              <td>
                <Badge status={c.status} />
              </td>
              <td className="small">{c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row mt">
        <Button tone="primary" disabled={data.blocked} onClick={onEvaluate}>
          通过回归并发布
        </Button>
        <Button onClick={onClose}>关闭</Button>
      </div>
    </Modal>
  )
}
