import { useState } from 'react'
import { Drawer } from 'antd'
import { Badge, Button, ErrorBox, SuccessBox, TableSkeleton } from '@/components/ui'
import { EmptyState } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { McpServer } from '@/api'

interface McpDrawerProps {
  open: boolean
  onClose: () => void
  servers: McpServer[] | null
  busy: boolean
  msg: { kind: 'ok' | 'err'; text: string } | null
  onAdd: (name: string, url: string, allow: string) => void
  onToggle: (name: string) => void
  onRemove: (name: string) => void
  onSave: () => void
}

export default function McpDrawer({ open, onClose, servers, busy, msg, onAdd, onToggle, onRemove, onSave }: McpDrawerProps) {
  const { confirm, confirmEl } = useConfirm()
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [allow, setAllow] = useState('')

  function submitAdd() {
    if (!name.trim() || !url.trim()) return
    onAdd(name.trim(), url.trim(), allow)
    setName('')
    setUrl('')
    setAllow('')
  }

  return (
    <Drawer title="接入源 · MCP" open={open} onClose={onClose} width={620}>
      {confirmEl}
      <p className="small muted" style={{ marginTop: 0 }}>
        在这里新增、编辑 MCP 接入源。保存后自动注册，白名单先确认，避免把整站能力都暴露出去。
      </p>
      <div className="tool-source-form">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="server 名" />
        <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="base_url，如 http://localhost:8081" />
        <input value={allow} onChange={(e) => setAllow(e.target.value)} placeholder="工具白名单（逗号，可选）" />
        <Button disabled={!name.trim() || !url.trim()} onClick={submitAdd}>添加</Button>
      </div>

      {servers === null ? (
        <TableSkeleton rows={5} cols={4} />
      ) : servers.length === 0 ? (
        <EmptyState title="还没有 MCP 服务器" desc="添加一个 MCP 服务器并保存，它提供的工具会自动注册到 Agent。" />
      ) : (
        <table className="tbl">
          <thead>
            <tr>
              <th>名称</th>
              <th>base_url</th>
              <th>工具数</th>
              <th>状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {servers.map((s) => (
              <tr key={s.name}>
                <td className="mono small">{s.name}</td>
                <td className="mono small muted">{s.base_url}</td>
                <td className="num small">{s.tools.length}</td>
                <td>
                  <Badge status={s.registered ? 'PASS' : s.enabled ? 'WARN' : 'DISABLED'}>
                    {s.registered ? '已注册' : s.enabled ? '待注册' : '已停用'}
                  </Badge>
                </td>
                <td>
                  <div className="row" style={{ gap: 6 }}>
                    <Button onClick={() => onToggle(s.name)}>{s.enabled ? '停用' : '启用'}</Button>
                    <Button
                      tone="danger"
                      onClick={() =>
                        confirm('移除 MCP 服务器', `确定移除「${s.name}」吗？该服务器下的所有工具将立即不可用。`, () => onRemove(s.name), { danger: true, confirmText: '移除' })
                      }
                    >
                      移除
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row mt" style={{ gap: 8 }}>
        <Button tone="primary" disabled={busy} onClick={onSave}>{busy ? '保存中…' : '保存并热注册'}</Button>
        {msg && (msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />)}
      </div>
    </Drawer>
  )
}
