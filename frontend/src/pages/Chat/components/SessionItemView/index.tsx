import { memo, useEffect, useRef, useState } from 'react'
import { MoreHorizontal, Pin } from 'lucide-react'
import { fmtTime } from '@/components'
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
  const rootRef = useRef<HTMLDivElement | null>(null)
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    if (!menuOpen) return
    const onDocMouseDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setMenuOpen(false)
    }
    const onDocKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onDocMouseDown)
    document.addEventListener('keydown', onDocKeyDown)
    return () => {
      document.removeEventListener('mousedown', onDocMouseDown)
      document.removeEventListener('keydown', onDocKeyDown)
    }
  }, [menuOpen])

  const closeMenu = () => setMenuOpen(false)

  return (
    <div ref={rootRef} className={`chat-session ${active ? 'on' : ''}`} onClick={onOpen}>
      <div className="chat-session-title">
        <span className="chat-session-title-text">{s.title || '新会话'}</span>
        {s.created_at && <span className="chat-session-time">{fmtTime(s.created_at)}</span>}
      </div>
      <div className="chat-session-preview">{s.last_content || '（空）'}</div>
      <div className="chat-session-ops">
        <button
          type="button"
          className={`chat-session-pin ${pinned ? 'on' : ''}`}
          onClick={(e) => { e.stopPropagation(); onTogglePin() }}
          title={pinned ? '取消置顶' : '置顶'}
          aria-label={pinned ? '取消置顶' : '置顶'}
        >
          <Pin size={13} />
        </button>
        <button
          type="button"
          className={`chat-session-more ${menuOpen ? 'open' : ''}`}
          onClick={(e) => { e.stopPropagation(); setMenuOpen((v) => !v) }}
          title="更多操作"
          aria-label="更多操作"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
        >
          <MoreHorizontal size={13} aria-hidden="true" />
        </button>
        {menuOpen && (
          <div className="chat-session-menu" role="menu" aria-label="会话操作" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="chat-session-menu-item" onClick={() => { closeMenu(); onRename() }}>重命名</button>
            <button type="button" className="chat-session-menu-item danger" onClick={() => { closeMenu(); onDelete() }}>删除</button>
          </div>
        )}
      </div>
    </div>
  )
})
