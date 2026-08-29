import { memo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, ChevronDown, UserRound } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge } from '@/components/ui'
import { ChatMsg } from '../../type/chat'
import { normalizeContent } from '../../util/chat'

export const MessageBubble = memo(function MessageBubble({ m, openTools, openCitations, onToggleTools, onToggleCitations, onRegenerate, onDeleteMessage }: {
  m: ChatMsg
  openTools: boolean
  openCitations: boolean
  onToggleTools: (id: number) => void
  onToggleCitations: (id: number) => void
  onRegenerate: () => void
  onDeleteMessage: (m: ChatMsg) => void
}) {
  const [copied, setCopied] = useState(false)
  const content = m.role === 'assistant' ? normalizeContent(m.content) : m.content
  const visibleTools = (m.tools ?? []).filter((t) => t.tool_ref && t.tool_ref.trim())
  const visibleDocs = (m.docs ?? []).map((d) => d.trim()).filter(Boolean)
  function copyContent() {
    if (!content) return
    navigator.clipboard?.writeText(content).then(() => setCopied(true), () => undefined)
  }
  return (
    <div className={`chat-msg ${m.role}`}>
      <span className={`chat-avatar ${m.role}`} aria-hidden="true">
        {m.role === 'assistant' ? <Bot size={16} /> : <UserRound size={16} />}
      </span>
      <div className="chat-bubble">
        {m.role === 'assistant' && content ? (
          <div className="chat-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
          </div>
        ) : (
          content
        )}
        {m.running && <span className="chat-thinking">…</span>}
        {visibleTools.length > 0 && (
          <div className="chat-tools">
            <div className="chat-tools-head">
              <button
                type="button"
                className={`chat-tools-toggle ${openTools ? 'open' : ''}`}
                onClick={() => onToggleTools(m.id)}
                aria-label={openTools ? '收起工具调用' : '展开工具调用'}
                title={openTools ? '收起工具调用' : '展开工具调用'}
              >
                <ChevronDown size={14} />
              </button>
              <span className="small muted">工具调用（{visibleTools.length}）</span>
            </div>
            {openTools && (
              <div className="chat-tools-list">
                {visibleTools.map((t, i) => (
                  <div key={`${t.tool_ref}-${i}`} className={`chat-tool ${t.ok === false ? 'bad' : ''}`}>
                    {t.tool_ref} {t.ok === false ? '❌' : '✅'}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
        {visibleDocs.length > 0 && (
          <div className="chat-tools">
            <div className="chat-tools-head">
              <button
                type="button"
                className={`chat-tools-toggle ${openCitations ? 'open' : ''}`}
                onClick={() => onToggleCitations(m.id)}
                aria-label={openCitations ? '收起引用来源' : '展开引用来源'}
                title={openCitations ? '收起引用来源' : '展开引用来源'}
              >
                <ChevronDown size={14} />
              </button>
              <span className="small muted">引用来源（{visibleDocs.length}）</span>
            </div>
            {openCitations && (
              <div className="chat-tools-list">
                {visibleDocs.map((d) => (
                  <Link key={d} className="chat-tool" to="/knowledge">
                    {d}
                  </Link>
                ))}
              </div>
            )}
          </div>
        )}
        {m.state && !m.running && (
          <div className="chat-meta">
            <Badge status={m.state} />
            {m.runId && (
              <Link className="link" to={`/runs/${m.runId}`}>
                {m.state === 'FAILED' || m.state === 'UNKNOWN' ? '去复盘 →' : '查看执行 →'}
              </Link>
            )}
            {m.role === 'assistant' && <a className="link" onClick={onRegenerate}>重新生成</a>}
            {!m.running && (
              <>
                <a className="link" onClick={copyContent}>{copied ? '已复制' : '复制'}</a>
                <a className="link" style={{ color: 'var(--danger)' }} onClick={() => onDeleteMessage(m)}>删除</a>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
})
