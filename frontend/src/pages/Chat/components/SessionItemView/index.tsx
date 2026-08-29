import { memo } from 'react'
import { SessionItem } from '../../type/chat'

export const SessionItemView = memo(function SessionItemView({ s, active, onOpen, onRename, onDelete }: {
  s: SessionItem
  active: boolean
  onOpen: () => void
  onRename: () => void
  onDelete: () => void
}) {
  return (
    <div className={`chat-session ${active ? 'on' : ''}`} onClick={onOpen}>
      <div className="chat-session-title">{s.title || '新会话'}</div>
      <div className="chat-session-preview">{s.last_content || '（空）'}</div>
      <div className="chat-session-ops">
        <a className="link small" onClick={(e) => { e.stopPropagation(); onRename() }}>重命名</a>
        <a className="link small" style={{ color: 'var(--danger)' }} onClick={(e) => { e.stopPropagation(); onDelete() }}>删除</a>
      </div>
    </div>
  )
})
