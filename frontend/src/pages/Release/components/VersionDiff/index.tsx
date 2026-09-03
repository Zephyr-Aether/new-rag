import { useMemo, useState } from 'react'
import { diffLines } from 'diff'
import { Badge, Card, fmtTime, stateLabel } from '@/components'
import { Version } from '@/services'

/** 发布 P2：版本差异视图 —— 当前 vs 上一稳定版本，只高亮变化项，判断「这版值不值得发」。 */
export default function VersionDiff({ versions }: { versions: Version[] }) {
  const sorted = useMemo(() => [...versions].sort((a, b) => b.version - a.version), [versions])
  const stable = sorted.find((v) => v.status === 'ACTIVE') ?? sorted[1] ?? sorted[0]
  const [baseId, setBaseId] = useState<number | ''>(stable ? stable.version : '')
  const [curId, setCurId] = useState<number | ''>(sorted[0] ? sorted[0].version : '')

  const base = sorted.find((v) => v.version === baseId) ?? null
  const cur = sorted.find((v) => v.version === curId) ?? null
  if (!base || !cur) return null

  const modelChanged = base.model !== cur.model
  const toolsBase = Array.isArray(base.config.tools) ? (base.config.tools as string[]) : []
  const toolsCur = Array.isArray(cur.config.tools) ? (cur.config.tools as string[]) : []
  const addedTools = toolsCur.filter((t) => !toolsBase.includes(t))
  const removedTools = toolsBase.filter((t) => !toolsCur.includes(t))
  const kvChanged = String(base.config.knowledge_version ?? '0') !== String(cur.config.knowledge_version ?? '0')

  const promptParts = diffLines(base.system_prompt ?? '', cur.system_prompt ?? '')
  const addedLines = promptParts.filter((p) => p.added && p.value.trim()).length
  const removedLines = promptParts.filter((p) => p.removed && p.value.trim()).length
  const hasChange = addedLines > 0 || removedLines > 0 || modelChanged || addedTools.length > 0 || removedTools.length > 0 || kvChanged

  // 风险提示：行为级变更（model / tools）或 prompt 改动较大 → 建议回归评测
  const risky = modelChanged || addedTools.length > 0 || removedTools.length > 0 || addedLines + removedLines > 8

  const opts = sorted.map((v) => v.version)

  return (
    <Card title="版本差异（决策视图）" className="mt">
      <div className="row mb" style={{ gap: 10, flexWrap: 'wrap' }}>
        <label className="small">对比</label>
        <select value={baseId} onChange={(e) => setBaseId(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">—（空）—</option>
          {opts.map((v) => (
            <option key={v} value={v}>v{v}</option>
          ))}
        </select>
        <span className="small muted">→</span>
        <select value={curId} onChange={(e) => setCurId(e.target.value === '' ? '' : Number(e.target.value))}>
          {opts.map((v) => (
            <option key={v} value={v}>v{v}</option>
          ))}
        </select>
        {hasChange && cur.status !== 'ACTIVE' && (
          <span style={{ marginLeft: 'auto' }}>
            <Badge status={risky ? 'HIGH_RISK_WRITE' : 'OK'}>{risky ? '有行为变更 · 建议回归' : '无行为变更'}</Badge>
          </span>
        )}
      </div>

      {!hasChange ? (
        <div className="empty">两个版本没有可检测的差异（prompt / model / tools / knowledge 一致）。</div>
      ) : (
        <div className="version-diff-grid">
          <div className="version-diff-col">
            <div className="version-diff-head">
              <span className="mono">v{base.version} · {stateLabel(base.status)}</span>
              <span className="small muted">{fmtTime(base.created_at)}</span>
            </div>
            <DiffRows
              side="base"
              left={base.system_prompt ?? ''}
              right={cur.system_prompt ?? ''}
              kv={String(base.config.knowledge_version ?? '0')}
              tools={toolsBase}
            />
          </div>
          <div className="version-diff-col">
            <div className="version-diff-head">
              <span className="mono">v{cur.version} · {stateLabel(cur.status)}</span>
              <span className="small muted">{fmtTime(cur.created_at)}</span>
            </div>
            <DiffRows
              side="cur"
              left={base.system_prompt ?? ''}
              right={cur.system_prompt ?? ''}
              kv={String(cur.config.knowledge_version ?? '0')}
              tools={toolsCur}
            />
          </div>
        </div>
      )}

      {(modelChanged || addedTools.length || removedTools.length || kvChanged) && (
        <div className="version-diff-meta mt" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {modelChanged && <div className="small"><b>模型变更</b>：{base.model || '默认'} → {cur.model || '默认'}</div>}
          {addedTools.length > 0 && <div className="small"><b className="version-diff-add">新增工具</b>：{addedTools.join('、')}</div>}
          {removedTools.length > 0 && <div className="small"><b className="version-diff-del">移除工具</b>：{removedTools.join('、')}</div>}
          {kvChanged && <div className="small"><b>知识版本</b>：v{String(base.config.knowledge_version ?? 0)} → v{String(cur.config.knowledge_version ?? 0)}</div>}
        </div>
      )}

      {risky && (
        <div className="version-diff-risk mt">行为存在变更（模型 / 工具 / 大段提示词）。建议先跑回归评测，确认没有质量回退再放量。</div>
      )}
    </Card>
  )
}

function DiffRows({ side, left, right, kv, tools }: {
  side: 'base' | 'cur'
  left: string
  right: string
  kv: string
  tools: string[]
}) {
  // base 侧只显示被删/未变行；cur 侧只显示新增/未变行，形成左右对照
  const rows: { type: 'add' | 'del' | 'ctx'; text: string }[] = []
  for (const p of diffLines(left ?? '', right ?? '')) {
    const type: 'add' | 'del' | 'ctx' = p.added ? 'add' : p.removed ? 'del' : 'ctx'
    const lines = p.value.replace(/\n$/, '').split('\n')
    for (const text of lines) {
      if (side === 'base' && type === 'add') continue
      if (side === 'cur' && type === 'del') continue
      rows.push({ type, text })
    }
  }
  const changed = rows.some((r) => r.type !== 'ctx')
  return (
    <div className="version-diff-block">
      <div className="version-diff-label">系统提示词{changed && <span className="version-diff-changed">· 有改动</span>}</div>
      <pre className="version-diff-pre">
        {rows.map((r, i) => (
          <div key={i} className={`version-diff-line ${r.type}`}>{r.text || ' '}</div>
        ))}
      </pre>
      <div className="version-diff-meta">工具：{tools.length ? tools.join('、') : '—'} · 知识：v{kv}</div>
    </div>
  )
}
