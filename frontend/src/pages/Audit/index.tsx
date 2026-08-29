import { useState } from 'react'
import { Pagination } from '@/components/pagination'
import { useRequest } from 'ahooks'
import { api } from '@/services'
import { Badge, Card, Empty, ErrorBox, fmtTime, TableSkeleton } from '@/components'
import { PageHeader } from '@/components/Page'

const PAGE_SIZE = 10

export default function Audit() {
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(1)
  const { data, loading, error } = useRequest(() => api.audit(200))

  const rows = data?.rows ?? null
  const shown = (rows ?? []).filter((r) => !filter || r.action.includes(filter))
  const pageRows = shown.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  return (
    <div>
      {error && <div className="mb"><ErrorBox message={(error as Error).message} /></div>}
      <PageHeader title="操作记录" desc="谁、在什么时候、对什么资源做了哪些操作" />
      <Card title="操作记录">
        <div className="row mb">
          <input
            value={filter}
            onChange={(e) => { setFilter(e.target.value); setPage(1) }}
            placeholder="按操作过滤（如 tool:execute）"
            style={{ maxWidth: 320 }}
          />
          <span className="small muted">{shown.length} 条</span>
        </div>
        {loading ? (
          <TableSkeleton rows={5} cols={5} />
        ) : shown.length === 0 ? (
          <Empty text="暂无操作记录：这里会记录谁、在什么时候、做了什么操作" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作</th>
                <th>资源</th>
                <th>actor</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              {pageRows.map((r) => (
                <tr key={r.id}>
                  <td className="mono small">{fmtTime(r.created_at)}</td>
                  <td className="mono small">{r.action}</td>
                  <td className="mono small">{r.resource}</td>
                  <td className="small">{r.actor_id}</td>
                  <td><Badge status={r.outcome} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {shown.length > PAGE_SIZE && (
          <div className="row mt" style={{ justifyContent: 'flex-end' }}>
            <Pagination current={page} pageSize={PAGE_SIZE} total={shown.length} onChange={setPage} />
          </div>
        )}
      </Card>
    </div>
  )
}
