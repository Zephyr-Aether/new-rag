import { useCallback, useEffect, useRef, useState } from 'react'
import { Graph } from '@antv/g6'
import { api } from '../api'
import { Badge, Button, Card, ErrorBox, Field, SuccessBox } from '../components/ui'
import { EmptyState, PageHeader } from '../components/Page'

interface Fact {
  subject: string
  predicate: string
  object: string
  confidence?: number
  status?: string
  source_doc?: string
}

function FactGraph({ facts, onNodeClick }: { facts: Fact[]; onNodeClick: (name: string) => void }) {
  const containerRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const nodes: string[] = []
    const add = (name: string) => {
      if (name && !nodes.includes(name)) nodes.push(name)
    }
    facts.forEach((f) => {
      add(f.subject)
      add(f.object)
    })
    const graph = new Graph({
      container: el,
      data: {
        nodes: nodes.map((n) => ({ id: n, data: { label: n } })),
        edges: facts.map((f, i) => ({
          id: `e${i}`,
          source: f.subject,
          target: f.object,
          data: { label: f.predicate },
        })),
      },
      layout: { type: 'force', preventOverlap: true, linkDistance: 130, nodeSpacing: 40 },
      node: {
        style: {
          size: 30,
          fill: '#dbeafe',
          stroke: '#2563eb',
          lineWidth: 1.5,
          labelText: (d: unknown) => (d as { data?: { label?: string } }).data?.label ?? '',
          labelFontSize: 11,
          labelFill: '#1f2430',
          labelPlacement: 'bottom',
        },
      },
      edge: {
        style: {
          stroke: '#cbd5e1',
          lineWidth: 1,
          labelText: (d: unknown) => (d as { data?: { label?: string } }).data?.label ?? '',
          labelFontSize: 9,
          labelFill: '#64748b',
          labelPlacement: 'center',
        },
      },
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
    })
    // G6 v5 类型定义不含节点点击的 target，运行时 evt.target 是节点
    graph.on('node:click', (evt: unknown) => {
      const e = evt as { target?: { id?: string } }
      const id = e.target?.id
      if (id) onNodeClick(id)
    })
    // 确保容器尺寸已计算（卡片可能刚挂载宽度未就绪）
    const raf = requestAnimationFrame(() => graph.render())
    return () => {
      cancelAnimationFrame(raf)
      graph.destroy()
    }
  }, [facts, onNodeClick])
  return <div ref={containerRef} style={{ width: '100%', height: 460 }} />
}

export default function GraphPage() {
  const [query, setQuery] = useState('')
  const [facts, setFacts] = useState<Fact[] | null>(null)
  const [entity, setEntity] = useState('')
  const [entityFacts, setEntityFacts] = useState<{ entity: string; canonical: string | null; facts: Fact[] } | null>(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [subj, setSubj] = useState('')
  const [pred, setPred] = useState('')
  const [obj, setObj] = useState('')
  // 抽取 / 消歧
  const [extractDoc, setExtractDoc] = useState('')
  const [extractText, setExtractText] = useState('')
  const [mergeFrom, setMergeFrom] = useState('')
  const [mergeInto, setMergeInto] = useState('')

  async function search() {
    if (!query.trim()) return
    setBusy(true)
    setErr('')
    try {
      const r = await api.graphQuery(query.trim())
      setFacts(r.facts)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const lookup = useCallback(
    async (name?: string) => {
      const target = (name ?? entity).trim()
      if (!target) return
      setBusy(true)
      setErr('')
      try {
        const r = await api.graphEntity(target)
        setEntityFacts(r)
        setEntity(target)
      } catch (e) {
        setErr((e as Error).message)
      } finally {
        setBusy(false)
      }
    },
    [entity],
  )

  async function addFact() {
    if (!subj || !pred || !obj) return
    setBusy(true)
    setMsg(null)
    try {
      await api.addGraphFact({ subject: subj.trim(), predicate: pred.trim(), object: obj.trim() })
      setMsg({ kind: 'ok', text: '事实已写入' })
      setSubj('')
      setPred('')
      setObj('')
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function extract() {
    if (!extractText.trim()) return
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.graphExtract({
        document_id: extractDoc.trim() || `doc-${Date.now().toString(36)}`,
        text: extractText.trim(),
      })
      setMsg({ kind: 'ok', text: `抽取完成：新增 ${r.added} 条事实` })
      setExtractText('')
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function merge() {
    if (!mergeFrom.trim() || !mergeInto.trim()) return
    setBusy(true)
    setMsg(null)
    try {
      await api.graphMerge(mergeFrom.trim(), mergeInto.trim())
      setMsg({ kind: 'ok', text: `已把「${mergeFrom}」合并进「${mergeInto}」` })
      setMergeFrom('')
      setMergeInto('')
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  const renderFacts = (rows: Fact[]) =>
    rows.length === 0 ? (
      <EmptyState
        title="还没匹配到事实"
        desc="先检索实体，或者右侧写入 / 抽取事实，再回来看看命中内容。"
      />
    ) : (
      <table className="tbl">
        <thead>
          <tr>
            <th>主体</th>
            <th>谓词</th>
            <th>客体</th>
            <th>置信</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((f, i) => (
            <tr key={i}>
              <td className="mono small">{f.subject}</td>
              <td className="mono small muted">{f.predicate}</td>
              <td className="mono small">{f.object}</td>
              <td className="num">{f.confidence ?? '—'}</td>
              <td><Badge status={f.status ?? 'ACTIVE'} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    )

  return (
    <div>
      <PageHeader title="关系图谱" desc="查看实体之间的关系：Agent 从文档中抽取出的知识关联" />
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
      <div>
        <Card title="关系查询">
          <div className="row">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && search()}
              placeholder="检索知识图谱…"
            />
            <Button tone="primary" disabled={busy} onClick={search}>
              {busy ? '查询中…' : '查询'}
            </Button>
          </div>
        </Card>
        {err && <div className="mt"><ErrorBox message={err} /></div>}

        <div className="mt">
          <Card title={facts && facts.length > 0 ? `关系图（${facts.length} 条事实，点节点查实体）` : '关系图'}>
            {facts && facts.length > 0 ? (
              <FactGraph facts={facts} onNodeClick={lookup} />
            ) : (
              <EmptyState
                title="还没有关系图"
                desc="先在上方检索实体，或在右侧写入/抽取事实；这里会用关系图可视化展示实体间的关系。"
              />
            )}
          </Card>
        </div>

        <div className="mt">
          <Card title="命中事实">
            {facts === null ? (
              <EmptyState
                title="还没有开始检索"
                desc="输入一句查询后，这里会列出命中的主体、谓词和客体。"
              />
            ) : (
              renderFacts(facts)
            )}
          </Card>
        </div>

        <div className="mt">
          <Card title="实体详情">
            <div className="row">
              <input
                value={entity}
                onChange={(e) => setEntity(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && lookup()}
                placeholder="实体名，如 用户A"
              />
              <Button disabled={busy} onClick={() => lookup()}>查看</Button>
            </div>
            {entityFacts ? (
              <div className="mt">
                <p className="small muted">规范名：{entityFacts.canonical ?? entityFacts.entity}</p>
                {renderFacts(entityFacts.facts)}
              </div>
            ) : (
              <div className="mt">
                <EmptyState
                  title="还没有查看实体"
                  desc="输入一个实体名，先看它的规范名和关联事实，再决定要不要合并。"
                />
              </div>
            )}
          </Card>
        </div>

        <div className="mt">
          <Card title="图谱工作流">
            <div className="graph-guide-list">
              <div className="graph-guide-item">
                <div className="graph-guide-k">1. 先检索</div>
                <div className="graph-guide-v">用上方关键字定位实体，命中的事实会落到左侧图谱和列表里。</div>
              </div>
              <div className="graph-guide-item">
                <div className="graph-guide-k">2. 再查看</div>
                <div className="graph-guide-v">点图上的节点，或者手工输入实体名，快速看规范名和关联关系。</div>
              </div>
              <div className="graph-guide-item">
                <div className="graph-guide-k">3. 最后整理</div>
                <div className="graph-guide-v">右侧可以直接写入、抽取和合并，把碎片事实收敛成规范图谱。</div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      <div>
        <Card title="写入事实">
          <Field label="主体">
            <input value={subj} onChange={(e) => setSubj(e.target.value)} placeholder="用户A" />
          </Field>
          <Field label="谓词">
            <input value={pred} onChange={(e) => setPred(e.target.value)} placeholder="负责" />
          </Field>
          <Field label="客体">
            <input value={obj} onChange={(e) => setObj(e.target.value)} placeholder="退款流程" />
          </Field>
          <Button tone="primary" disabled={busy || !subj || !pred || !obj} onClick={addFact} className="mt">写入</Button>
          {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
        </Card>

        <Card title="从文档抽取事实（LLM/规则）" className="mt">
          <Field label="文档ID（可选，留空自动生成）">
            <input value={extractDoc} onChange={(e) => setExtractDoc(e.target.value)} />
          </Field>
          <Field label="文本（抽事实并入库，带溯源）">
            <textarea value={extractText} onChange={(e) => setExtractText(e.target.value)} placeholder="用户A 负责退款流程。退款流程依赖支付系统。" style={{ minHeight: 80 }} />
          </Field>
          <Button tone="primary" disabled={busy || !extractText.trim()} onClick={extract} className="mt">抽取</Button>
        </Card>

        <Card title="实体消歧（合并到规范名）" className="mt">
          <Field label="被合并实体">
            <input value={mergeFrom} onChange={(e) => setMergeFrom(e.target.value)} placeholder="用户A" />
          </Field>
          <Field label="规范实体名（合并目标）">
            <input value={mergeInto} onChange={(e) => setMergeInto(e.target.value)} placeholder="张三" />
          </Field>
          <Button disabled={busy || !mergeFrom.trim() || !mergeInto.trim()} onClick={merge} className="mt">合并</Button>
        </Card>
      </div>
      </div>
    </div>
  )
}
