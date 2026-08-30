import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ReleaseOrder, Version } from '@/services'
import { Badge, Button, Card, Field, Loading } from '@/components'
import { RadioGroup, RadioGroupItem } from '@/components/radio-group'
import { Switch } from '@/components/switch'
import { Input } from '@/components/input'
import { Textarea } from '@/components/textarea'
import { FlowChain, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { useMeta } from '../useMeta'
import { toast } from '@/toast'

type Mode = 'standard' | 'gray' | 'rollback'

const MODE_LABEL: Record<Mode, string> = {
  standard: '标准发布',
  gray: '灰度发布',
  rollback: '回滚单',
}
const VERSION_TONE: Record<string, { status: string; label: string }> = {
  DRAFT: { status: 'DRAFT', label: '草稿' },
  ACTIVE: { status: 'ACTIVE', label: '已上线' },
  GRAY: { status: 'GRAY', label: '灰度中' },
  DISABLED: { status: 'DISABLED', label: '已停用' },
}

export default function ReleaseOrderCreate() {
  const { meta } = useMeta()
  const navigate = useNavigate()
  const { confirm, confirmEl } = useConfirm()
  const agentId = meta?.agent_id ?? ''

  const [versions, setVersions] = useState<Version[] | null>(null)
  const [orders, setOrders] = useState<ReleaseOrder[] | null>(null)
  const [busy, setBusy] = useState('')

  const [mode, setMode] = useState<Mode>('standard')
  // 目标版本：'new' 新建草稿，number 选择已有版本
  const [target, setTarget] = useState<number | 'new'>('new')
  const [autoContract, setAutoContract] = useState(true)
  const [autoRegression, setAutoRegression] = useState(false)
  const [autoCanary, setAutoCanary] = useState(false)

  // 新建草稿表单
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState('')
  const [tools, setTools] = useState('calc.add')
  const [kv, setKv] = useState('0')

  const ordered = useMemo(() => (versions ? [...versions].sort((a, b) => b.version - a.version) : []), [versions])
  const drafts = ordered.filter((v) => v.status === 'DRAFT')
  const rollbackTargets = ordered.filter((v) => v.status !== 'DRAFT')
  const openOrder = (orders ?? []).find((o) => o.status === 'open') ?? null
  const lastRelease = ordered.find((v) => v.status === 'ACTIVE')

  // 默认选最新 DRAFT；新建草稿预填最近成功发布配置
  useEffect(() => {
    if (!versions || versions.length === 0) return
    if (drafts.length > 0) setTarget(drafts[0].version)
    const cfg = lastRelease?.config
    if (cfg) {
      setPrompt(String(cfg.system_prompt ?? ''))
      setModel(String(cfg.model ?? ''))
      setTools(Array.isArray(cfg.tools) ? (cfg.tools as string[]).join(', ') : 'calc.add')
      setKv(String(cfg.knowledge_version ?? '0'))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [versions])

  useEffect(() => {
    if (!agentId) return
    api.versions(agentId).then((v) => setVersions(v.versions)).catch(() => setVersions([]))
    api.releaseOrderList(agentId).then((o) => setOrders(o.orders)).catch(() => setOrders([]))
  }, [agentId])

  // 发布方式切换时，确保目标版本与模式匹配
  useEffect(() => {
    if (mode === 'gray' && (typeof target !== 'number' || !drafts.some((d) => d.version === target))) {
      if (drafts[0]) setTarget(drafts[0].version)
    }
    if (mode === 'rollback' && (typeof target !== 'number' || !rollbackTargets.some((d) => d.version === target))) {
      if (rollbackTargets[0]) setTarget(rollbackTargets[0].version)
    }
    if (mode === 'standard' && typeof target !== 'number' && drafts[0]) setTarget(drafts[0].version)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode])

  if (!meta) return <Loading />

  const selected = typeof target === 'number' ? ordered.find((v) => v.version === target) ?? null : null
  const isNewDraft = target === 'new'
  const maxOrderNo = Math.max(0, ...(orders ?? []).map((o) => o.order_no))
  const previewOrderNo = maxOrderNo + 1
  const hasDraftCandidates = drafts.length > 0

  const autoChecks = [
    autoContract && '契约',
    autoRegression && '回归',
    autoCanary && 'canary',
  ].filter(Boolean)
  const targetLabel = isNewDraft ? `新建草稿（基于 ${lastRelease ? `v${lastRelease.version}` : '默认'}）` : selected ? `v${selected.version}` : '—'

  const nextStepLabel =
    mode === 'rollback'
      ? '执行回滚'
      : mode === 'gray'
        ? '灰度放量'
        : autoContract
          ? (autoRegression ? '回归评测' : '契约检查')
          : '创建草稿'
  const riskHints: string[] = []
  if (openOrder) riskHints.push(`存在进行中的发布单 #${openOrder.order_no}，创建新单会终止它。`)
  if (mode === 'rollback') riskHints.push('回滚会停止当前版本，流量切到目标版本。')
  if (selected?.status === 'ACTIVE') riskHints.push('该版本已是当前生效版本，重复发布前请确认。')
  if (mode === 'gray' && !hasDraftCandidates) riskHints.push('没有草稿版本，无法灰度发布，请先用标准发布创建草稿。')

  function openConfirm() {
    confirm(
      '创建发布单',
      <ul className="release-confirm-list">
        <li><b>目标版本</b>：{targetLabel}</li>
        <li><b>覆盖当前进行中</b>：{openOrder ? `是（将终止 #${openOrder.order_no}）` : '无进行中单'}</li>
        <li><b>自动跑检查</b>：{autoChecks.length ? autoChecks.join('、') : '不自动执行'}</li>
      </ul>,
      () => void submit(),
      { confirmText: openOrder ? '新建并终止旧单' : '创建发布单', danger: !!openOrder },
    )
  }

  async function submit() {
    if (!agentId) return
    setBusy('create')
    let order: Awaited<ReturnType<typeof api.releaseOrderCreate>>
    try {
      order = await api.releaseOrderCreate(agentId)
    } catch (e) {
      toast((e as Error).message, 'err')
      setBusy('')
      return
    }
    try {
      if (mode === 'rollback') {
        if (selected) {
          await api.rollback(agentId, selected.version)
          await api.releaseFlowRecord(agentId, { version: selected.version, step: 'release', summary: `回滚到 v${selected.version}`, ok: true })
          await api.releaseFlowNode(agentId, 'release', { version: selected.version }, 'done')
        }
      } else if (mode === 'gray') {
        if (selected) {
          await api.gray(agentId, selected.version, 10)
          await api.releaseFlowRecord(agentId, { version: selected.version, step: 'gray', summary: `灰度放量 v${selected.version} 10%`, ok: true })
          await api.releaseFlowNode(agentId, 'gray', { version: selected.version }, 'release')
          if (autoCanary) await api.canaryEvaluate(agentId).catch(() => undefined)
        }
      } else {
        // 标准发布
        let targetVersion = selected?.version ?? 0
        const draftConfig = {
          system_prompt: selected ? String(selected.config.system_prompt ?? '') : prompt.trim(),
          model: selected ? String(selected.config.model ?? '') : model.trim(),
          tools: selected ? (Array.isArray(selected.config.tools) ? (selected.config.tools as string[]).join(', ') : '') : tools,
          kv: selected ? String(selected.config.knowledge_version ?? '0') : kv.trim() || '0',
        }
        if (!selected) {
          const v = await api.createVersion(agentId, {
            system_prompt: draftConfig.system_prompt,
            model: draftConfig.model || undefined,
            config: { tools: draftConfig.tools.split(',').map((s) => s.trim()).filter(Boolean), knowledge_version: draftConfig.kv },
          })
          targetVersion = v.version
        }
        await api.releaseFlowRecord(agentId, { version: targetVersion, step: 'draft', summary: `创建草稿 v${targetVersion}`, ok: true })
        await api.releaseFlowNode(agentId, 'draft', draftConfig, 'contract')
        if (autoContract) {
          const c = await api.contractCheck(agentId, targetVersion)
          const blocked = c.blocked
          const passed = c.checks.filter((x) => x.status === 'pass').length
          const failed = c.checks.filter((x) => x.status === 'fail').length
          await api.releaseFlowRecord(agentId, {
            version: targetVersion, step: 'contract',
            summary: `v${targetVersion} 契约检查：${passed} 通过 / ${failed} 失败`, ok: !blocked,
            detail: c.checks.filter((x) => x.status !== 'pass').map((x) => `${x.id}: ${x.reason}`).join('；') || undefined,
          })
          await api.releaseFlowNode(agentId, 'contract', { total: c.checks.length, passed, failed }, blocked ? 'contract' : 'regression')
          if (!blocked && autoRegression) {
            const r = await api.regression(agentId, targetVersion)
            await api.releaseFlowRecord(agentId, {
              version: targetVersion, step: 'regression',
              summary: `v${targetVersion} 回归：通过率 ${((r.pass_rate ?? 0) * 100).toFixed(0)}%${r.regressed ? '（退化）' : ''}`, ok: !r.regressed,
            })
            await api.releaseFlowNode(agentId, 'regression', { pass_rate: r.pass_rate, regressed: r.regressed }, r.regressed ? 'regression' : 'gray')
          }
        }
      }
    } catch (e) {
      toast((e as Error).message, 'err')
    }
    toast('发布单已创建')
    navigate(`/release/orders/${order.id}`, { replace: true })
  }

  const versionCandidates = mode === 'rollback' ? rollbackTargets : drafts

  return (
    <div className="grid" style={{ gap: 16 }}>
      {confirmEl}
      <FlowChain current="release" />
      <PageHeader title="创建发布单" desc="先选版本、定发布方式与自动检查，创建后直接进入发布流程。" />

      <div className="release-create-layout">
        <div className="release-create-main">
          {/* 1. 目标版本 */}
          <Card title="目标版本">
            {versions === null ? (
              <Loading />
            ) : (
              <>
                <RadioGroup value={String(target)} onValueChange={(v) => setTarget(v === 'new' ? 'new' : Number(v))}>
                  {mode !== 'rollback' && (
                    <RadioGroupItem value="new">新建草稿版本（基于 {lastRelease ? `v${lastRelease.version}` : '默认'}）</RadioGroupItem>
                  )}
                  {versionCandidates.map((v) => {
                    const st = VERSION_TONE[v.status] ?? { status: v.status, label: v.status }
                    return (
                      <RadioGroupItem key={v.version} value={String(v.version)}>
                        <span className="mono">v{v.version}</span>
                        <Badge status={st.status}>{st.label}</Badge>
                      </RadioGroupItem>
                    )
                  })}
                </RadioGroup>
                {versionCandidates.length === 0 && mode !== 'rollback' && (
                  <p className="small muted">没有草稿版本，将从「新建草稿」开始。</p>
                )}
                {mode === 'rollback' && rollbackTargets.length === 0 && (
                  <p className="small muted">没有可回滚的目标版本。</p>
                )}
              </>
            )}
          </Card>

          {/* 版本摘要 / 新建草稿表单 */}
          <Card title={selected ? `v${selected.version} · 版本摘要` : '新建草稿 · 初始配置'}>
            {selected ? (
              <div className="release-create-summary">
                <div className="grid cols-2" style={{ gap: 10 }}>
                  <div className="release-create-field"><span className="small muted">版本号</span><b className="mono">v{selected.version}</b></div>
                  <div className="release-create-field"><span className="small muted">状态</span><Badge status={VERSION_TONE[selected.status]?.status ?? selected.status}>{VERSION_TONE[selected.status]?.label ?? selected.status}</Badge></div>
                  <div className="release-create-field"><span className="small muted">上次发布结果</span><span>{selected.status === 'ACTIVE' ? '已上线' : selected.status === 'DRAFT' ? '尚未发布' : '已停用 / 回滚'}</span></div>
                  <div className="release-create-field"><span className="small muted">模型</span><span>{selected.model || '默认'}</span></div>
                  <div className="release-create-field"><span className="small muted">工具集</span><span className="mono small">{Array.isArray(selected.config.tools) ? (selected.config.tools as string[]).join(', ') : '—'}</span></div>
                  <div className="release-create-field"><span className="small muted">knowledge</span><span className="mono small">{String(selected.config.knowledge_version ?? '—')}</span></div>
                </div>
                <p className="small muted mt">配置摘要来自版本本身；创建后按发布方式走对应链路。</p>
              </div>
            ) : (
              <div className="release-create-config">
                <Field label="系统提示词">
                  <Textarea value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="新的系统提示词" className="min-h-[90px]" />
                </Field>
                <div className="grid cols-3" style={{ gap: 12 }}>
                  <Field label="模型">
                    <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="默认回落" />
                  </Field>
                  <Field label="工具集（逗号分隔）">
                    <Input value={tools} onChange={(e) => setTools(e.target.value)} />
                  </Field>
                  <Field label="knowledge_version">
                    <Input value={kv} onChange={(e) => setKv(e.target.value)} />
                  </Field>
                </div>
              </div>
            )}
          </Card>

          {/* 2. 发布方式 */}
          <Card title="发布方式">
            <RadioGroup value={mode} onValueChange={(v) => setMode(v as Mode)}>
              <RadioGroupItem value="standard">标准发布</RadioGroupItem>
              <RadioGroupItem value="gray" disabled={!hasDraftCandidates}>
                灰度发布 {!hasDraftCandidates && <span className="text-muted-foreground">（需先有草稿版本）</span>}
              </RadioGroupItem>
              <RadioGroupItem value="rollback">回滚单</RadioGroupItem>
            </RadioGroup>
          </Card>

          {/* 3. 自动执行 */}
          <Card title="是否自动执行">
            <div className="grid gap-3">
              <label className="release-auto-row">
                <span>契约检查</span>
                <Switch checked={autoContract} onCheckedChange={setAutoContract} disabled={mode !== 'standard'} />
              </label>
              <label className="release-auto-row">
                <span>回归评测（契约通过后）</span>
                <Switch checked={autoRegression} onCheckedChange={setAutoRegression} disabled={mode !== 'standard' || !autoContract} />
              </label>
              <label className="release-auto-row">
                <span>Canary 检查（灰度发布时）</span>
                <Switch checked={autoCanary} onCheckedChange={setAutoCanary} disabled={mode !== 'gray'} />
              </label>
              {mode === 'standard' && <p className="small muted">标准发布自动跑契约/回归；canary 在进入灰度后运行。</p>}
            </div>
          </Card>

          {/* 动作按钮 */}
          <div className="row" style={{ gap: 10 }}>
            <Button tone="primary" disabled={busy === 'create' || (mode === 'gray' && !selected)} onClick={openConfirm}>
              {busy === 'create' ? '创建中…' : openOrder ? '新建并终止旧单' : '创建发布单'}
            </Button>
            <Button disabled={busy === 'create'} onClick={() => navigate('/release')}>取消</Button>
          </div>
        </div>

        {/* 右侧发布预览 */}
        <aside className="release-create-preview">
          <Card title="发布预览">
            <div className="release-preview-item"><span className="small muted">单号</span><b className="mono">#{previewOrderNo}</b></div>
            <div className="release-preview-item"><span className="small muted">目标版本</span><b>{targetLabel}</b></div>
            <div className="release-preview-item"><span className="small muted">发布方式</span><b>{MODE_LABEL[mode]}</b></div>
            <div className="release-preview-item"><span className="small muted">默认下一步</span><b>{nextStepLabel}</b></div>
            {riskHints.length > 0 && (
              <div className="release-preview-risk">
                {riskHints.map((r, i) => (
                  <div key={i} className="small">{r}</div>
                ))}
              </div>
            )}
          </Card>
        </aside>
      </div>
    </div>
  )
}
