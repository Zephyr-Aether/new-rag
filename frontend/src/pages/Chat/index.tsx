import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Paperclip, Send, Square } from 'lucide-react'
import { api, MAX_UPLOAD_BYTES, StreamEvent } from '@/services'
import { Button, Field, Modal } from '@/components'
import { useConfirm } from '@/components/Confirm'
import { FlowChain, PageHeader } from '@/components/Page'
import { MessageBubble } from './components/MessageBubble'
import { SessionItemView } from './components/SessionItemView'
import { ChatMsg, SessionItem, ToolCallView } from './type/chat'
import { budgetHistory, normalizeContent } from './util/chat'

let seq = 1
const QUICK_PROMPTS = [
  { label: '算一下 12 + 30', prompt: '12 + 30' },
  { label: '介绍一下你自己', prompt: '用一句话介绍你自己' },
  { label: '问知识库退款到账', prompt: '知识库: 退款到账时间' },
]

export default function Chat() {
  const { confirm, confirmEl } = useConfirm()
  const [sessions, setSessions] = useState<SessionItem[]>([])
  const [currentSid, setCurrentSid] = useState('')
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [activeRunId, setActiveRunId] = useState('')
  const [openTools, setOpenTools] = useState<Record<number, boolean>>({})
  const [openCitations, setOpenCitations] = useState<Record<number, boolean>>({})
  const [kbInfo, setKbInfo] = useState<{ bases: number; docs: number } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [renameSid, setRenameSid] = useState('')
  const [renameTitle, setRenameTitle] = useState('')
  const [uploadErr, setUploadErr] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  // 请求令牌：每次 send 自增，回调/清理只在令牌仍最新时生效，隔离过期请求的迟到事件
  const tokenRef = useRef(0)
  const fileRef = useRef<HTMLInputElement>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const messagesRef = useRef(messages)
  useEffect(() => {
    messagesRef.current = messages
  }, [messages])

  function loadSessions() {
    api.sessions().then((r) => setSessions(r.sessions)).catch(() => setSessions([]))
  }
  useEffect(() => {
    // 只请求一次：加载列表 + 自动恢复最近会话
    api
      .sessions()
      .then((r) => {
        setSessions(r.sessions)
        if (r.sessions.length) openSession(r.sessions[0].id)
      })
      .catch(() => setSessions([]))
    api.kbBases().then((r) => setKbInfo((p) => ({ bases: r.bases.length, docs: p?.docs ?? 0 }))).catch(() => undefined)
    api.documents().then((r) => setKbInfo((p) => ({ bases: p?.bases ?? 0, docs: r.rows.length }))).catch(() => undefined)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const openSession = useCallback(async (sid: string) => {
    if (busy) return
    setCurrentSid(sid)
    try {
      const r = await api.sessionMessages(sid)
      setMessages(
        r.messages.map((m) => ({
          id: seq++,
          mid: m.id,
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: normalizeContent(m.content),
          state: m.state,
          // 服务端持久化的中断/失败状态 → 历史里也能显示「已停止」
          interrupted: m.state === 'CANCELLED',
          tools: m.tools ?? [],
          docs: m.docs ?? [],
          running: false,
        })),
      )
    } catch {
      setMessages([])
    }
  }, [busy])

  function newSession() {
    if (busy) return
    setCurrentSid('')
    setMessages([])
  }

  const deleteSession = useCallback(async (sid: string) => {
    confirm(
      '删除会话',
      `确定删除该会话吗？会话内 ${sessions.find((s) => s.id === sid)?.message_count ?? ''} 条消息将一并删除。`,
      async () => {
        await api.sessionDelete(sid)
        if (sid === currentSid) {
          setCurrentSid('')
          setMessages([])
        }
        loadSessions()
      },
      { danger: true, confirmText: '删除' },
    )
  }, [sessions, currentSid])

  const renameSession = useCallback(async (sid: string) => {
    const cur = sessions.find((s) => s.id === sid)?.title ?? ''
    setRenameSid(sid)
    setRenameTitle(cur === '新会话' ? '' : cur)
  }, [sessions])

  async function saveRename() {
    if (!renameSid) return
    await api.sessionPatch(renameSid, { title: renameTitle.trim() })
    setRenameSid('')
    loadSessions()
  }

  const deleteMessage = useCallback(async (m: ChatMsg) => {
    if (!currentSid || !m.mid) {
      setMessages((prev) => prev.filter((x) => x.id !== m.id))
      return
    }
    await api.sessionMessageDelete(currentSid, m.mid)
    setMessages((prev) => prev.filter((x) => x.id !== m.id))
  }, [currentSid])

  async function send(e?: FormEvent, retry?: string, opts: { clientRunId?: string } = {}) {
    if (e) e.preventDefault()
    const text = (retry ?? input).trim()
    if (!text || busy) return
    if (!retry) setInput('')
    const rid = tokenRef.current + 1
    tokenRef.current = rid
    // §32.5 幂等键：普通发送/重新生成为新键，重试复用原键让服务端去重
    const clientRunId = opts.clientRunId ?? crypto.randomUUID()
    setBusy(true)
    setActiveRunId('')
    abortRef.current = new AbortController()

    const history = budgetHistory(messages.map((m) => ({ role: m.role, content: m.content })))
    const userMsg: ChatMsg = { id: seq++, role: 'user', content: text, clientRunId }
    const asstId = seq
    seq++
    const asstMsg: ChatMsg = { id: asstId, role: 'assistant', content: '', running: true }
    setMessages((prev) => [...prev, userMsg, asstMsg])
    // 只有仍是最新一次请求的回调才允许写入，过期请求的迟到事件直接丢弃
    const patch = (p: Partial<ChatMsg>) => {
      if (tokenRef.current !== rid) return
      setMessages((prev) => prev.map((m) => (m.id === asstId ? { ...m, ...p } : m)))
    }
    const tools: ToolCallView[] = []
    let tokenBuf = ''
    let finished = false
    // 流式 token 批次刷新：避免逐 token 全量重渲染（长答案几百次 → 几十次）
    const flushToken = () => {
      if (!tokenBuf || tokenRef.current !== rid) return
      const chunk = tokenBuf
      tokenBuf = ''
      setMessages((prev) => prev.map((m) => (m.id === asstId ? { ...m, content: normalizeContent(m.content + chunk) } : m)))
    }
    const tokenTimer = setInterval(flushToken, 50)

    try {
      await api.streamRun(
        text,
        { sessionId: currentSid, history, clientRunId },
        (ev: StreamEvent) => {
          if (tokenRef.current !== rid) return
          if (ev.type === 'start') setActiveRunId(ev.run_id)
          else if (ev.type === 'tool_call') {
            const tool_ref = (ev.tool || '').trim()
            if (!tool_ref) return
            tools.push({ tool_ref })
            patch({ tools: [...tools] })
          } else if (ev.type === 'tool_result') {
            const tool_ref = (ev.tool || '').trim()
            if (!tool_ref) return
            const t = tools.find((x) => x.tool_ref === tool_ref)
            if (t) t.ok = ev.ok
            patch({ tools: [...tools] })
            if (ev.docs && ev.docs.length) {
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === asstId ? { ...m, docs: [...new Set([...(m.docs ?? []), ...ev.docs!])] } : m,
                ),
              )
            }
          } else if (ev.type === 'answer') {
            tokenBuf = '' // answer 是完整答案，直接替换，丢弃缓冲的零散 token
            patch({ content: normalizeContent(ev.answer) })
          } else if (ev.type === 'token') {
            tokenBuf += ev.text
          } else if (ev.type === 'done') {
            finished = true
            if (ev.session_id) setCurrentSid(ev.session_id)
            if (ev.answer != null) tokenBuf = '' // 内容由完整 answer 覆盖，丢弃未 flush 的零散 token
            // answer 字段在幂等重放路径（只发 done 不回放 token）必须有内容；正常流式下也一致
            patch(
              ev.answer != null
                ? { content: normalizeContent(ev.answer), state: ev.state, runId: ev.run_id, running: false }
                : { state: ev.state, runId: ev.run_id, running: false },
            )
            loadSessions()
          } else if (ev.type === 'error') {
            finished = true
            patch({ content: `出错了：${ev.message}`, state: 'FAILED', retriable: true, running: false })
          }
        },
        abortRef.current.signal,
      )
    } catch (err) {
      // 正常流式阶段的 AbortError 已被 streamRun 吞掉；这里兜底 fetch 阶段（响应头未返回就停止）
      if ((err as Error).name === 'AbortError') return
      finished = true
      patch({ content: `出错了：${(err as Error).message}`, state: 'FAILED', retriable: true, running: false })
    } finally {
      clearInterval(tokenTimer)
      flushToken()
      if (tokenRef.current === rid) {
        // 流正常返回但没收到 done/error → 用户停止或连接中断，落账为「已中断」
        if (!finished) patch({ interrupted: true, state: 'INTERRUPTED', running: false })
        setBusy(false)
        setActiveRunId('')
        abortRef.current = null
      }
    }
  }

  const regenerate = useCallback(() => {
    if (busy) return
    const msgs = messagesRef.current
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    const idx = msgs.findIndex((m) => m.id === lastUser.id)
    setMessages((prev) => prev.slice(0, idx + 1)) // 保留到最后一个用户消息
    void send(undefined, lastUser.content)
  }, [busy])

  const retryMessage = useCallback((m: ChatMsg) => {
    if (busy) return
    const msgs = messagesRef.current
    const idx = msgs.findIndex((x) => x.id === m.id)
    if (idx < 0) return
    const userMsg = [...msgs].slice(0, idx).reverse().find((x) => x.role === 'user')
    if (!userMsg) return
    // 截到用户消息，复用同一 client_run_id 重发 → 服务端去重，不重复执行
    setMessages((prev) => prev.slice(0, prev.findIndex((x) => x.id === userMsg.id) + 1))
    void send(undefined, userMsg.content, { clientRunId: userMsg.clientRunId })
  }, [busy])

  const toggleTools = useCallback((id: number) => {
    setOpenTools((prev) => ({ ...prev, [id]: !prev[id] }))
  }, [])

  const toggleCitations = useCallback((id: number) => {
    setOpenCitations((prev) => ({ ...prev, [id]: !prev[id] }))
  }, [])

  async function uploadFile(f: File) {
    if (busy || uploading) return
    if (f.size > MAX_UPLOAD_BYTES) {
      setUploadErr(`文件超过 ${(MAX_UPLOAD_BYTES / 1024 / 1024).toFixed(0)}MB 上限，请压缩后再试。`)
      return
    }
    setUploading(true)
    try {
      const r = await api.uploadDocument(f)
      void send(undefined, `我刚上传了文档「${r.title}」（${r.document_id}），请阅读并告诉我它讲了什么`)
    } catch (e) {
      setUploadErr(`上传失败：${(e as Error).message}`)
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  function stop() {
    if (activeRunId) api.cancelRun(activeRunId).catch(() => {})
    abortRef.current?.abort()
  }

  function exportChat() {
    const text = messages.map((m) => `${m.role === 'user' ? '用户' : '助手'}: ${m.content}`).join('\n\n')
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `chat-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  // 右侧验证栏：只看最近一条助手回答的引用/工具/可追踪情况
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant') ?? null
  const lastTools = (lastAssistant?.tools ?? []).filter((t) => t.tool_ref && t.tool_ref.trim())
  const lastDocs = (lastAssistant?.docs ?? []).map((d) => d.trim()).filter(Boolean)

  return (
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
      <FlowChain current="chat" />
      <PageHeader
        title="对话"
        desc="这一步负责验证：发一个问题看整条链路（检索→引用→回答）是否通畅。答不稳就回知识库补资料，稳了就往下设门禁。"
        actions={
          <>
            <Button onClick={newSession} disabled={busy}>新会话</Button>
            <Button tone="primary" onClick={exportChat} disabled={messages.length === 0}>导出</Button>
          </>
        }
      />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">对话验证 · 这一步</span>
          <span>1. 先点一个示例问题 2. 需要资料就上传文档 3. 答不稳就去知识库补资料。</span>
        </div>
        <Link className="btn primary" to="/knowledge">去知识库</Link>
      </div>

      <div className="chat-layout">
        <aside className="chat-side">
          <div className="row mb" style={{ justifyContent: 'space-between' }}>
            <span className="small muted">会话</span>
            <Button onClick={newSession} disabled={busy}>+ 新会话</Button>
          </div>
          <div className="chat-side-note small muted">会话会自动保留上下文，删除后无法恢复。</div>
          <div className="chat-session-list">
            {sessions.length === 0 ? (
              <div className="chat-session-empty">
                <span className="small muted">暂无历史会话</span>
                <span className="small muted">先发一句，系统会自动创建会话并保留上下文。</span>
              </div>
            ) : (
              sessions.map((s) => (
                <SessionItemView
                  key={s.id}
                  s={s}
                  active={s.id === currentSid}
                  onOpen={() => openSession(s.id)}
                  onRename={() => renameSession(s.id)}
                  onDelete={() => deleteSession(s.id)}
                />
              ))
            )}
          </div>
        </aside>

        <div className="chat">
          <div className="chat-head">
            <span className="muted small">{currentSid ? '会话中' : '新会话'}</span>
            <div className="row" style={{ gap: 6 }}>
              {messages.length > 0 && <Button onClick={exportChat}>导出</Button>}
              <Button onClick={newSession} disabled={busy}>清空</Button>
            </div>
          </div>

          <div className="chat-stream">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty-title">先从一个问题开始</div>
                <div className="chat-empty-desc">点一个示例直接发出去，或者自己输入问题。这里会保留上下文、展示工具调用，也能带出引用来源。</div>
                <div className="chat-empty-note">如果答案不稳，先去知识库补资料，再回来重试同一个问题。</div>
                <div className="chat-empty-actions">
                  {QUICK_PROMPTS.map((p) => (
                    <Button key={p.prompt} type="button" onClick={() => void send(undefined, p.prompt)}>
                      {p.label}
                    </Button>
                  ))}
                </div>
                <div className="row" style={{ justifyContent: 'center', marginTop: 14 }}>
                  <Link className="btn" to="/knowledge">去知识库补资料</Link>
                  <Link className="btn" to="/runs">看任务记录</Link>
                </div>
              </div>
            ) : (
              messages.map((m) => (
                <MessageBubble
                  key={m.id}
                  m={m}
                  openTools={!!openTools[m.id]}
                  openCitations={!!openCitations[m.id]}
                  onToggleTools={toggleTools}
                  onToggleCitations={toggleCitations}
                  onRegenerate={regenerate}
                  onRetry={() => retryMessage(m)}
                  onDeleteMessage={deleteMessage}
                />
              ))
            )}
            <div ref={endRef} />
          </div>

          <form className="chat-input" onSubmit={send}>
            <div className="chat-input-box">
              <input
                ref={fileRef}
                type="file"
                hidden
                accept=".txt,.md,.pdf,.doc,.docx,.csv,.xlsx"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void uploadFile(f)
                }}
              />
              <button type="button" className="chat-input-upload" disabled={busy || uploading} onClick={() => fileRef.current?.click()} title="上传文档直接入库">
                <Paperclip size={15} />
                {uploading ? '上传中' : ''}
              </button>
              <textarea
                value={input}
                onChange={(e) => {
                  setInput(e.target.value)
                  const el = e.target
                  el.style.height = 'auto'
                  el.style.height = Math.min(el.scrollHeight, 160) + 'px'
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    if (busy) stop()
                    else send()
                  }
                }}
                placeholder="输入问题，Enter 发送，Shift+Enter 换行"
                rows={1}
              />
              {busy ? (
                <button type="button" className="chat-send" onClick={stop} title="停止" style={{ background: 'var(--danger)' }}>
                  <Square size={15} />
                </button>
              ) : (
                <button type="submit" className="chat-send" disabled={!input.trim()} title="发送">
                  <Send size={15} />
                </button>
              )}
            </div>
          </form>
        </div>

        <aside className="chat-inspect">
          <div className="chat-inspect-title">本次回答 · 验证信息</div>

          <div className="chat-inspect-block">
            <div className="chat-inspect-label">当前知识</div>
            {kbInfo === null ? (
              <div className="small muted">读取中…</div>
            ) : kbInfo.bases > 0 && kbInfo.docs > 0 ? (
              <div className="chat-inspect-line">
                <span className="chat-inspect-ok">✓</span> {kbInfo.bases} 个知识库 · {kbInfo.docs} 份文档
              </div>
            ) : (
              <div className="chat-inspect-line">
                <span className="chat-inspect-warn">○</span>
                {kbInfo.bases > 0 ? '知识库还没有文档' : '还没有知识库'}
                <Link className="link" to="/knowledge">去导入</Link>
              </div>
            )}
          </div>

          {lastAssistant && (
            <div className="chat-inspect-block">
              <div className="chat-inspect-block" style={{ gap: 4 }}>
                <div className="chat-inspect-label">是否命中知识</div>
                <div className="chat-inspect-line">
                  {lastDocs.length > 0 ? (
                    <span className="chat-inspect-ok">✓ 命中 {lastDocs.length} 篇</span>
                  ) : (
                    <span className="chat-inspect-warn">未命中知识库</span>
                  )}
                </div>
              </div>
              <div className="chat-inspect-block" style={{ gap: 4 }}>
                <div className="chat-inspect-label">工具调用</div>
                <div className="chat-inspect-line">{lastTools.length > 0 ? `${lastTools.length} 次调用` : '未调用工具'}</div>
              </div>
              <div className="chat-inspect-block" style={{ gap: 4 }}>
                <div className="chat-inspect-label">可追踪</div>
                <div className="chat-inspect-line">
                  {lastAssistant.runId ? (
                    <Link className="link" to={`/runs/${lastAssistant.runId}`}>查看执行 →</Link>
                  ) : (
                    <span className="muted">进行中</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {lastDocs.length > 0 && (
            <div className="chat-inspect-block">
              <div className="chat-inspect-label">引用来源</div>
              <div className="chat-tools">
                {lastDocs.map((d) => (
                  <Link key={d} className="chat-tool" to="/knowledge">{d}</Link>
                ))}
              </div>
            </div>
          )}

          {lastTools.length > 0 && (
            <div className="chat-inspect-block">
              <div className="chat-inspect-label">工具明细</div>
              <div className="chat-tools">
                {lastTools.map((t, i) => (
                  <span key={`${t.tool_ref}-${i}`} className={`chat-tool ${t.ok === false ? 'bad' : ''}`}>
                    {t.tool_ref} {t.ok === false ? '❌' : '✅'}
                  </span>
                ))}
              </div>
            </div>
          )}
        </aside>
      </div>

      {renameSid && (
        <Modal title="重命名会话" onClose={() => setRenameSid('')}>
          <Field label="会话标题">
            <input value={renameTitle} onChange={(e) => setRenameTitle(e.target.value)} placeholder="输入标题" onKeyDown={(e) => e.key === 'Enter' && saveRename()} />
          </Field>
          <div className="row mt">
            <Button tone="primary" disabled={!renameTitle.trim()} onClick={saveRename}>保存</Button>
            <Button onClick={() => setRenameSid('')}>取消</Button>
          </div>
        </Modal>
      )}

      {uploadErr && (
        <Modal title="提示" onClose={() => setUploadErr('')}>
          <p className="small" style={{ margin: '0 0 16px' }}>{uploadErr}</p>
          <div className="row">
            <Button tone="primary" onClick={() => setUploadErr('')}>知道了</Button>
          </div>
        </Modal>
      )}
    </div>
  )
}
