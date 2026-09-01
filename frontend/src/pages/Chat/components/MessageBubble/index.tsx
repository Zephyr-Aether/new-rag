import { memo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Bot, Check, ChevronDown, Copy, ThumbsDown, ThumbsUp, UserRound } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Badge } from '@/components'
import { ChatMsg } from '../../type/chat'
import { closeUnclosedFence, normalizeContent } from '../../util/chat'

// ReactMarkdown 的 pre 子树 → 纯文本（代码块复制用）
function extractCodeText(node: ReactNode): string {
  if (node == null || node === false) return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractCodeText).join('')
  if (typeof node === 'object' && 'props' in node) {
    return extractCodeText((node as { props: { children?: ReactNode } }).props.children)
  }
  return ''
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false)
  const text = extractCodeText(children).replace(/\n+$/, '')
  function copy() {
    if (!text) return
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }, () => undefined)
  }
  return (
    <div className="chat-code">
      <pre>{children}</pre>
      <button type="button" className="chat-code-copy" onClick={copy} title="复制代码" aria-label="复制代码">
        {copied ? <Check size={12} /> : <Copy size={12} />}
        {copied ? '已复制' : '复制'}
      </button>
    </div>
  )
}

export const MessageBubble = memo(function MessageBubble({ m, openTools, openCitations, onToggleTools, onToggleCitations, onRegenerate, onRetry, onContinue, onFeedback, onDeleteMessage }: {
  m: ChatMsg
  openTools: boolean
  openCitations: boolean
  onToggleTools: (id: number) => void
  onToggleCitations: (id: number) => void
  onRegenerate: () => void
  onRetry: () => void
  onContinue: () => void
  onFeedback: (fb: 'good' | 'bad') => void
  onDeleteMessage: (m: ChatMsg) => void
}) {
  const [copied, setCopied] = useState(false)
  const raw = m.role === 'assistant' ? normalizeContent(m.content) : m.content
  // 流式期间补闭合 fence，避免未闭合代码块吞掉后续内容造成页面跳动；复制/最终态用原始文本
  const content = m.running && m.role === 'assistant' ? closeUnclosedFence(raw) : raw
  const visibleTools = (m.tools ?? []).filter((t) => t.tool_ref && t.tool_ref.trim())
  const visibleDocs = (m.docs ?? []).map((d) => d.trim()).filter(Boolean)
  function copyContent() {
    if (!raw) return
    navigator.clipboard?.writeText(raw).then(() => setCopied(true), () => undefined)
  }
  return (
    <div className={`chat-msg ${m.role}`}>
      <span className={`chat-avatar ${m.role}`} aria-hidden="true">
        {m.role === 'assistant' ? <Bot size={16} /> : <UserRound size={16} />}
      </span>
      <div className="chat-bubble">
        {m.role === 'assistant' && content ? (
          <div className="chat-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{ pre: ({ children }) => <CodeBlock>{children}</CodeBlock> }}
            >
              {content}
            </ReactMarkdown>
          </div>
        ) : (
          content
        )}
        {m.running && <span className="chat-thinking">…</span>}
        {m.interrupted && <div className="chat-meta-line">已停止，内容不完整</div>}
        {m.error && (
          <div className="chat-fail">
            <div className="chat-fail-title">运行失败</div>
            <div className="chat-fail-reason">{m.error}</div>
            {m.retriable && (
              <div className="row" style={{ gap: 8 }}>
                <button type="button" className="chat-fail-retry" onClick={onRetry}>重试</button>
                <span className="small muted">将复用原配置重试，不会重复执行</span>
              </div>
            )}
          </div>
        )}
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
            {m.role === 'assistant' && m.interrupted && m.content.trim() && (
              <a className="link" onClick={onContinue}>继续</a>
            )}
            {m.role === 'assistant' && <a className="link" onClick={onRegenerate}>重新生成</a>}
            {m.retriable && <a className="link" onClick={onRetry}>重试</a>}
            {m.role === 'assistant' && m.runId && (
              <span className="chat-feedback">
                <button
                  type="button"
                  className={`chat-feedback-btn ${m.feedback === 'good' ? 'on' : ''}`}
                  onClick={() => onFeedback('good')}
                  disabled={!!m.feedback}
                  title="有用"
                  aria-label="有用"
                >
                  <ThumbsUp size={13} />
                </button>
                <button
                  type="button"
                  className={`chat-feedback-btn ${m.feedback === 'bad' ? 'on' : ''}`}
                  onClick={() => onFeedback('bad')}
                  disabled={!!m.feedback}
                  title="无用"
                  aria-label="无用"
                >
                  <ThumbsDown size={13} />
                </button>
              </span>
            )}
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
