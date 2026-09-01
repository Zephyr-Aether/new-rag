import { memo } from 'react'
import { Pin } from 'lucide-react'
import { SessionItem } from '../../type/chat'

export const SessionItemView = memo(function SessionItemView({ s, active, pinned, onOpen, onRename, onDelete, onTogglePin }: {
  s: SessionItem
  active: boolean
  pinned: boolean
  onOpen: () => void
  onRename: () => void
  onDelete: () => void
  onTogglePin: () => void
}) {
  return (
    <div className={`chat-session ${active ? 'on' : ''}`} onClick={onOpen}>
      <div className="chat-session-title">
        <span className="chat-session-title-text">{s.title || '新会话'}</span>
        <button
          type="button"
          className={`chat-session-pin ${pinned ? 'on' : ''}`}
          onClick={(e) => { e.stopPropagation(); onTogglePin() }}
          title={pinned ? '取消置顶' : '置顶'}
          aria-label={pinned ? '取消置顶' : '置顶'}
        >
          <Pin size={13} />
        </button>
      </div>
      <div className="chat-session-preview">{s.last_content || '（空）'}</div>
      <div className="chat-session-ops">
        <a className="link small" onClick={(e) => { e.stopPropagation(); onRename() }}>重命名</a>
        <a className="link small" style={{ color: 'var(--danger)' }} onClick={(e) => { e.stopPropagation(); onDelete() }}>删除</a>
      </div>
    </div>
  )
})
