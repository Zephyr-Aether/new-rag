import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link } from 'react-router-dom'
import { Drawer, Progress, Upload } from 'antd'
import { ChevronDown, Trash2 } from 'lucide-react'
import { api, KbBase, KBHit, KBSearch, MAX_UPLOAD_BYTES } from '@/api'
import { Badge, Button, Card, Empty, ErrorBox, Field, fmtTime, Loading, Modal, stateLabel, SuccessBox, TableSkeleton } from '@/components/ui'
import { EmptyState, FlowChain, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'
import { chunkedUpload } from './util/upload'
import { highlight } from './util/highlight'
import { DocDetail, DocRow } from './type/knowledge'
import { RETRIEVAL_PARAM_DESC } from './constants/knowledge'

export default function Knowledge() {
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const [docId, setDocId] = useState('')
  const [title, setTitle] = useState('')
  const [text, setText] = useState('')
  const [ingMsg, setIngMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [ingBusy, setIngBusy] = useState(false)
  const [upTitle, setUpTitle] = useState('')
  const [upMsg, setUpMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [upPct, setUpPct] = useState<number | null>(null)

  const [query, setQuery] = useState('')
  const [searching, setSearching] = useState(false)
  const [result, setResult] = useState<KBSearch | null>(null)
  const [searchErr, setSearchErr] = useState('')

  const [docs, setDocs] = useState<DocRow[] | null>(null)
  const [docErr, setDocErr] = useState('')
  const [delBusy, setDelBusy] = useState('')
  const [view, setView] = useState<{ doc: DocDetail | null; loading: boolean; err: string } | null>(null)

  // 多知识库
  const [bases, setBases] = useState<KbBase[]>([])
  const [curKb, setCurKb] = useState('default')
  const [newKbName, setNewKbName] = useState('')
  const [kbMsg, setKbMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [cfgTopK, setCfgTopK] = useState('20')
  const [cfgBm25, setCfgBm25] = useState('20')
  const [cfgRerank, setCfgRerank] = useState('5')
  const [cfgBusy, setCfgBusy] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [tab, setTab] = useState<'docs' | 'search'>('docs')
  const [newKbOpen, setNewKbOpen] = useState(false)
  const [newKbDesc, setNewKbDesc] = useState('')
  const [preview, setPreview] = useState<{ cleaned: string; chunks: number } | null>(null)
  const [previewBusy, setPreviewBusy] = useState(false)
  const currentBase = bases.find((b) => b.kb_id === curKb)
  const currentDocCount = typeof currentBase?.doc_count === 'number' ? currentBase.doc_count : docs?.length ?? 0
  const kbHint = currentDocCount > 0
    ? `当前库「${currentBase?.name ?? '默认知识库'}」已有 ${currentDocCount} 份文档。下一步可以直接搜索，再去对话页问同一个问题看引用。`
    : `当前库「${currentBase?.name ?? '默认知识库'}」还没有文档，先导入第一份资料，Agent 才有东西可答。`

  function openImportDrawer() {
    setIngMsg(null)
    setUpMsg(null)
    setPreview(null)
    setImportOpen(true)
  }

  async function doPreview() {
    if (!text.trim()) return
    setPreviewBusy(true)
    try {
      setPreview(await api.previewClean(text))
    } catch (e) {
      setIngMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setPreviewBusy(false)
    }
  }

  function loadBases() {
    api.kbBases().then((r) => setBases(r.bases)).catch(() => setBases([]))
  }

  // 当前库切换时回填检索参数
  useEffect(() => {
    const cfg = bases.find((b) => b.kb_id === curKb)?.retrieval_config
    setCfgTopK(String(cfg?.top_k ?? 20))
    setCfgBm25(String(cfg?.bm25_top_k ?? 20))
    setCfgRerank(String(cfg?.rerank_n ?? 5))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curKb, bases])

  async function saveKbConfig() {
    setCfgBusy(true)
    setKbMsg(null)
    try {
      await api.kbConfig(curKb, {
        top_k: Number(cfgTopK) || 20,
        bm25_top_k: Number(cfgBm25) || 20,
        rerank_n: Number(cfgRerank) || 5,
      })
      setKbMsg({ kind: 'ok', text: '已保存推荐的检索参数' })
      loadBases()
    } catch (e) {
      setKbMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setCfgBusy(false)
    }
  }

  function loadDocs() {
    api.documents(curKb).then((r) => setDocs(r.rows)).catch((e: Error) => setDocErr(e.message))
  }
  useEffect(() => {
    loadBases()
    loadDocs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    // 切换知识库：重新加载文档、清空检索结果
    loadDocs()
    setResult(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [curKb])

  async function createKb() {
    if (!newKbName.trim()) return
    try {
      await api.kbCreate(newKbName.trim(), newKbDesc.trim())
      setKbMsg({ kind: 'ok', text: `已创建知识库「${newKbName.trim()}」` })
      setNewKbName('')
      setNewKbDesc('')
      setNewKbOpen(false)
      loadBases()
    } catch (e) {
      setKbMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  function deleteKb(id: string, name: string) {
    confirm(
      '删除知识库',
      `确定删除知识库「${name}」及其全部文档吗？此操作不可撤销。`,
      async () => {
        try {
          await api.kbDelete(id)
          setKbMsg({ kind: 'ok', text: `已删除「${name}」` })
          if (curKb === id) setCurKb('default')
          loadBases()
        } catch (e) {
          setKbMsg({ kind: 'err', text: (e as Error).message })
        }
      },
      { danger: true, confirmText: '删除' },
    )
  }

  async function openDoc(id: string) {
    setView({ doc: null, loading: true, err: '' })
    try {
      const d = await api.documentDetail(id)
      setView({ doc: d, loading: false, err: '' })
    } catch (e) {
      setView({ doc: null, loading: false, err: (e as Error).message })
    }
  }

  async function ingest() {
    if (!docId || !title || !text) return
    setIngBusy(true)
    setIngMsg(null)
    try {
      const r = await api.ingest({ document_id: docId.trim(), title: title.trim(), text, kb_id: curKb })
      setIngMsg({ kind: 'ok', text: `已入库 ${r.chunks} 个片段（${stateLabel(r.status)}）` })
      setText('')
      loadDocs()
      setImportOpen(false)
    } catch (e) {
      setIngMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setIngBusy(false)
    }
  }

  async function removeDoc(id: string) {
    setDelBusy(id)
    try {
      await api.deleteDocument(id)
      loadDocs()
    } catch (e) {
      setDocErr((e as Error).message)
    } finally {
      setDelBusy('')
    }
  }

  async function search() {
    if (!query.trim()) return
    setSearching(true)
    setSearchErr('')
    try {
      setResult(await api.search(query.trim(), curKb))
    } catch (e) {
      setSearchErr((e as Error).message)
    } finally {
      setSearching(false)
    }
  }

  const visibleProvenance = result?.provenance.map((p) => p.trim()).filter(Boolean) ?? []

  return (
    <div className="grid" style={{ gap: 18 }}>
      {confirmEl}
      <FlowChain current="knowledge" />
      <PageHeader
        title="知识库"
        desc="这一步负责导入：先建库再导文档。资料进库后才能被检索和引用，直接决定对话回答的质量。"
        actions={
          <>
            <Button onClick={() => setNewKbOpen(true)}>新建知识库</Button>
            <Button tone="primary" disabled={!can('kb:ingest')} onClick={openImportDrawer}>
              导入文档
            </Button>
          </>
        }
      />

      <div className="knowledge-control">
        <div className="knowledge-control-head">
          <div className="knowledge-control-copy">
            <span className="knowledge-control-kicker">当前状态</span>
            <span className="knowledge-control-title">{kbHint}</span>
            <span className="knowledge-control-sub muted">右侧检索是快速校验，底下文档列表是内容管理，对话页则是最终验证。</span>
          </div>
          <Link className={`btn ${currentDocCount > 0 ? 'primary' : ''}`} to="/chat">
            去对话验证
          </Link>
        </div>

        <div className="knowledge-control-row">
          <div className="kb-switcher-head knowledge-control-kbhead">
            <div>
              <div className="kb-switcher-label">知识库切换</div>
              <div className="kb-switcher-hint small muted">
                当前库：{currentBase?.name ?? '默认知识库'} · {currentDocCount} 份文档
              </div>
            </div>
            {curKb !== 'default' && (
              <Button
                tone="danger"
                className="kb-switcher-danger"
                onClick={() => deleteKb(curKb, bases.find((b) => b.kb_id === curKb)?.name ?? '')}
              >
                <Trash2 size={14} />
                删除当前库
              </Button>
            )}
          </div>
          <div className="kb-switcher-tabs knowledge-control-tabs">
            {bases.map((b) => {
              const active = curKb === b.kb_id
              const count = typeof b.doc_count === 'number' ? b.doc_count : 0
              return (
                <button
                  key={b.kb_id}
                  type="button"
                  className={`kb-tab ${active ? 'active' : ''}`}
                  onClick={() => setCurKb(b.kb_id)}
                  title={b.description || undefined}
                >
                  <span className="kb-tab-name">{b.name}</span>
                  <span className="kb-tab-count">{count}</span>
                </button>
              )
            })}
          </div>
        </div>

        <details className="kb-param-details">
          <summary className="link small" style={{ cursor: 'pointer', fontWeight: 600 }}>
            高级设置：检索参数（候选数 / 关键词召回 / 精排条数）
          </summary>
          <div className="knowledge-control-row knowledge-control-config">
            <div className="kb-config-grid">
              <label className="kb-config-field">
                <span>候选数</span>
                <input type="number" min={1} max={100} value={cfgTopK} onChange={(e) => setCfgTopK(e.target.value)} />
              </label>
              <label className="kb-config-field">
                <span>关键词召回</span>
                <input type="number" min={1} max={200} value={cfgBm25} onChange={(e) => setCfgBm25(e.target.value)} />
              </label>
              <label className="kb-config-field">
                <span>精排条数</span>
                <input type="number" min={1} max={20} value={cfgRerank} onChange={(e) => setCfgRerank(e.target.value)} />
              </label>
            </div>
            <div className="kb-config-actions">
              <Button disabled={cfgBusy} onClick={saveKbConfig}>{cfgBusy ? '保存中…' : '保存'}</Button>
              {kbMsg && (
                <div className="kb-config-msg">
                  {kbMsg.kind === 'ok' ? <SuccessBox message={kbMsg.text} /> : <ErrorBox message={kbMsg.text} />}
                </div>
              )}
            </div>
          </div>
          <div className="kb-param-hint compact">
            {RETRIEVAL_PARAM_DESC.map(([k, v]) => (
              <div key={k} className="kb-param-row">
                <code className="kb-param-key">{k}</code>
                <span className="muted small">{v}</span>
              </div>
            ))}
          </div>
        </details>
      </div>

      <div className="knowledge-tabs">
        <button type="button" className={`knowledge-tab${tab === 'docs' ? ' active' : ''}`} onClick={() => setTab('docs')}>
          文档管理{docs ? ` · ${docs.length}` : ''}
        </button>
        <button type="button" className={`knowledge-tab${tab === 'search' ? ' active' : ''}`} onClick={() => setTab('search')}>
          检索预览
        </button>
      </div>

      {tab === 'docs' ? (
        <Card title={`已入库文档（${docs?.length ?? '…'}）`} className="knowledge-card">
          {docErr && <div className="mb"><ErrorBox message={docErr} /></div>}
          {docs === null ? (
            <TableSkeleton rows={5} cols={5} />
          ) : docs.length === 0 ? (
            <EmptyState
              title="还没有文档"
              desc="这一步只做一件事：导入第一份资料。导入后就能在「检索预览」试搜，再去对话页问同一个问题看引用。"
              actions={
                <div className="empty-state-actions">
                  <Button tone="primary" disabled={!can('kb:ingest')} onClick={openImportDrawer}>
                    导入文档
                  </Button>
                  <Link className="btn" to="/chat">去对话验证</Link>
                </div>
              }
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {docs.map((d) => (
                <div key={d.document_id} style={{ background: '#fff', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
                  <div className="row spread">
                    <div>
                      <div className="small" style={{ fontWeight: 600 }}>{d.title}</div>
                      <div className="muted mono" style={{ fontSize: 11 }}>{d.document_id}</div>
                    </div>
                    <Badge status={d.status} />
                  </div>
                  <div className="row mt" style={{ justifyContent: 'space-between' }}>
                    <span className="small muted">{d.chunk_count ?? '—'} 片段 · {fmtTime(d.created_at)}</span>
                    <div className="row" style={{ gap: 6 }}>
                      <Button disabled={view?.loading} onClick={() => openDoc(d.document_id)}>查看</Button>
                      <Button tone="danger" disabled={delBusy === d.document_id} onClick={() => confirm('删除文档', `确定删除「${d.title}」及其全部内容吗？此操作不可撤销。`, () => removeDoc(d.document_id), { danger: true, confirmText: '删除' })}>
                        删除
                      </Button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      ) : (
        <>
          <Card title="检索预览" className="knowledge-card">
            <div className="row">
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && search()}
                placeholder="搜索知识库…"
              />
              <Button tone="primary" disabled={searching || !query.trim()} onClick={search}>
                {searching ? '搜索中…' : '搜索'}
              </Button>
            </div>
            {searchErr && <div className="mt"><ErrorBox message={searchErr} /></div>}
          </Card>

          <Card title="检索结果" className="knowledge-card">
            {searching ? (
              <Loading />
            ) : result === null ? (
              <EmptyState
                title="还没有开始检索"
                desc="在上方输入问题后，这里会显示命中片段、分数和引用来源。你也可以先去对话页看同一个问题的引用表现。"
                actions={
                  <div className="empty-state-actions">
                    <Link className="btn" to="/chat">
                      去对话验证
                    </Link>
                  </div>
                }
              />
            ) : result.hits.length === 0 ? (
              <EmptyState
                title="这次没有命中"
                desc="可以换个问法，或者先调大候选数和关键词召回，再看看是否能把相关片段拉进来。"
                actions={
                  <div className="empty-state-actions">
                    <Button tone="primary" onClick={search}>
                      再搜一次
                    </Button>
                    <Link className="btn" to="/chat">
                      去对话验证
                    </Link>
                  </div>
                }
              />
            ) : (
              <>
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>文档</th>
                      <th>章节</th>
                      <th className="num">分</th>
                      <th>片段</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.hits.map((h: KBHit, i) => (
                      <tr key={i}>
                        <td className="mono small">{h.document_id}</td>
                        <td className="small">{h.section}</td>
                        <td className="num mono">{h.score}</td>
                        <td className="small muted">{highlight(h.text.slice(0, 80), query)}…</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {visibleProvenance.length > 0 && (
                  <details className="knowledge-citations mt">
                    <summary className="knowledge-citations-summary small muted">
                      <ChevronDown size={14} className="knowledge-citations-icon" />
                      <span>引用来源（{visibleProvenance.length}）</span>
                    </summary>
                    <div className="knowledge-citations-list">
                      {visibleProvenance.map((item) => (
                        <span key={item} className="chat-tool" style={{ cursor: 'default' }}>
                          {item}
                        </span>
                      ))}
                    </div>
                  </details>
                )}
              </>
            )}
          </Card>
        </>
      )}

      <Drawer title="新建知识库" open={newKbOpen} onClose={() => setNewKbOpen(false)} width={440}>
        <Field label="名称">
          <input value={newKbName} onChange={(e) => setNewKbName(e.target.value)} placeholder="如：产品手册" autoFocus />
        </Field>
        <Field label="描述（可选）">
          <textarea value={newKbDesc} onChange={(e) => setNewKbDesc(e.target.value)} placeholder="这个知识库用来放什么" style={{ minHeight: 60 }} />
        </Field>
        <div className="row">
          <Button tone="primary" disabled={!newKbName.trim()} onClick={createKb}>创建</Button>
          <Button onClick={() => setNewKbOpen(false)}>取消</Button>
        </div>
      </Drawer>

      <Drawer title="导入文档" open={importOpen} onClose={() => setImportOpen(false)} width={560}>
          <div className="mb" style={{ fontWeight: 600 }}>手动录入（Markdown）</div>
          <Field label="文档ID">
            <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="doc-1" />
          </Field>
          <Field label="标题">
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="退货政策" />
          </Field>
          <Field label="正文（Markdown，输入实时预览）">
            <textarea value={text} onChange={(e) => { setText(e.target.value); setPreview(null) }} placeholder="## 退款到账时间\n退款 3-5 个工作日到账。" style={{ minHeight: 120 }} />
            {text.trim() && (
              <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px', marginTop: 6, background: '#fff' }}>
                <ReactMarkdown>{text}</ReactMarkdown>
              </div>
            )}
          </Field>
          <div className="row">
            <Button disabled={previewBusy || !text.trim()} onClick={doPreview}>{previewBusy ? '清洗中…' : '清洗预览'}</Button>
            <Button tone="primary" disabled={ingBusy || !docId || !title || !text} onClick={ingest}>
              {ingBusy ? '入库中…' : '入库'}
            </Button>
            {ingMsg && (ingMsg.kind === 'ok' ? <SuccessBox message={ingMsg.text} /> : <ErrorBox message={ingMsg.text} />)}
          </div>
          {preview && (
            <div className="mt" style={{ background: '#f8fafc', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
              <div className="small muted mb">清洗后（{preview.cleaned.length} 字，约 {preview.chunks} 段）</div>
              <div className="small" style={{ whiteSpace: 'pre-wrap', maxHeight: 140, overflow: 'auto' }}>{preview.cleaned}</div>
            </div>
          )}

          <div className="mt" style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
            <div className="mb" style={{ fontWeight: 600 }}>上传文件（TXT / Markdown / PDF / CSV / Excel）</div>
            <Field label="标题（可选，留空用文件名）">
              <input value={upTitle} onChange={(e) => setUpTitle(e.target.value)} placeholder="产品手册" />
            </Field>
            <Upload.Dragger
              multiple={false}
              showUploadList={false}
              accept=".txt,.md,.markdown,.pdf,.csv,.xlsx,.xls"
              customRequest={async ({ file, onProgress, onSuccess, onError }) => {
                try {
                  const f = file as File
                  if (f.size > MAX_UPLOAD_BYTES) {
                    setUpMsg({ kind: 'err', text: `文件超过 ${(MAX_UPLOAD_BYTES / 1024 / 1024).toFixed(0)}MB 上限` })
                    onError?.(new Error('too large'))
                    return
                  }
                  const r = await chunkedUpload(f, upTitle.trim() || undefined, curKb, (pct) => {
                    setUpPct(pct)
                    onProgress?.({ percent: pct })
                  })
                  setUpMsg({ kind: 'ok', text: `已上传 ${f.name} → ${r.chunks} 个片段` })
                  setUpTitle('')
                  setUpPct(100)
                  loadDocs()
                  onSuccess?.(r)
                } catch (e) {
                  setUpMsg({ kind: 'err', text: (e as Error).message })
                  onError?.(e as Error)
                } finally {
                  setTimeout(() => setUpPct(null), 1500)
                }
              }}
            >
              <p style={{ margin: 0, padding: '22px 0', textAlign: 'center' }}>
                点击或拖拽文件到此区域上传（分片 + 断点续传）
              </p>
            </Upload.Dragger>
            {upPct !== null && upPct > 0 && (
              <div className="mt">
                <Progress percent={upPct} size="small" status={upPct >= 100 ? 'success' : 'active'} />
              </div>
            )}
            {upMsg && <div className="mt">{upMsg.kind === 'ok' ? <SuccessBox message={upMsg.text} /> : <ErrorBox message={upMsg.text} />}</div>}
          </div>
      </Drawer>

      {view && (
        <Modal
          title={view.loading ? '加载中…' : view.doc ? `文档：${view.doc.title}（${view.doc.document_id}）` : '文档详情'}
          onClose={() => setView(null)}
        >
          {view.err && <div className="mb"><ErrorBox message={view.err} /></div>}
          {view.loading ? (
            <Loading />
          ) : view.doc ? (
            <div>
              <div className="row mb">
                <Badge status={view.doc.status} />
                {view.doc.source_uri && <span className="small muted">来源：{view.doc.source_uri}</span>}
                <span className="small muted">{view.doc.chunks.length} 个片段</span>
              </div>
              {view.doc.chunks.length === 0 ? (
                <Empty text="该文档还没有可展示的片段" />
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                  {view.doc.chunks.map((c) => (
                    <div key={c.chunk_id} style={{ background: '#f8fafc', border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
                      <div className="row" style={{ marginBottom: 4 }}>
                        <span className="mono small" style={{ color: 'var(--primary)' }}>#{c.seq}</span>
                        {c.section && <span className="small" style={{ fontWeight: 600 }}>{c.section}</span>}
                        <span className="small muted">{c.token_count} Token</span>
                      </div>
                      <div className="small" style={{ whiteSpace: 'pre-wrap' }}>{c.text}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : null}
        </Modal>
      )}
    </div>
  )
}
