import { useEffect, useState } from 'react'
import { useRequest } from 'ahooks'
import { Link } from 'react-router-dom'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/sheet'
import { Slider } from '@/components/slider'
import { Eye, EyeOff, RefreshCw } from 'lucide-react'
import { api } from '@/services'
import { Badge, Button, Card, ErrorBox, Field, fmtTime } from '@/components'
import { Switch } from '@/components/switch'
import { PageHeader } from '@/components/Page'
import Onboarding, { resetOnboarding } from '@/components/Onboarding'
import { toast } from '@/toast'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'

export default function ConfigCenter() {
  const { can } = usePermissions()
  const { confirm, confirmEl } = useConfirm()

  // —— 版本化配置 ——
  const [ckey, setCkey] = useState('max_steps')
  const [cval, setCval] = useState('20')
  const [config, setConfig] = useState<{ key: string; value: unknown; version: number | null } | null>(null)
  const [histVal, setHistVal] = useState<{ key: string; value: unknown; version: number | null } | null>(null)
  const [versions, setVersions] = useState<{ version: number; value: unknown; created_at?: string }[]>([])

  // —— Feature Flag ——
  const [fkey, setFkey] = useState('new_flow')
  const [fpct, setFpct] = useState('10')
  const [flagOn, setFlagOn] = useState<boolean | null>(null)
  const [flagEnabled, setFlagEnabled] = useState(true)
  const [flagLoading, setFlagLoading] = useState(false)

  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [onboardingOpen, setOnboardingOpen] = useState(false)

  // —— 模型接入 ——
  const [form, setForm] = useState({ provider: 'mock', model: '', base_url: '', api_key: '' })
  const [saving, setSaving] = useState(false)
  const [showKey, setShowKey] = useState(false)

  // —— 密钥管理 ——
  const [secOpen, setSecOpen] = useState(false)
  const [secRef, setSecRef] = useState('')
  const [secValue, setSecValue] = useState('')
  const [secBusy, setSecBusy] = useState(false)
  const [secErr, setSecErr] = useState('')

  const { data: cfg, refresh: refreshCfg } = useRequest(() => api.modelConfig())
  const { data: secData, refresh: refreshSecrets } = useRequest(() => api.secrets())
  const secrets = secData?.secrets ?? []
  const modelReady = !!cfg && !cfg.is_mock

  useEffect(() => {
    if (cfg) setForm((f) => ({ ...f, provider: cfg.provider, model: cfg.model, base_url: cfg.base_url }))
  }, [cfg])

  useEffect(() => {
    void syncFlagState(fkey.trim())
    // 仅初始化时同步一次，避免在输入过程中频繁请求。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const formDirty = cfg && (form.provider !== cfg.provider || form.model.trim() !== (cfg.model ?? '') || form.base_url.trim() !== (cfg.base_url ?? ''))

  async function saveModel() {
    setSaving(true)
    try {
      const r = await api.modelConfigSet({
        provider: form.provider,
        model: form.model.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim(),
      })
      toast(r.is_mock ? '已切到 mock 模式（本地确定性）' : `已切到真实模型：${r.provider} / ${r.model}`)
      setForm((f) => ({ ...f, api_key: '' }))
      refreshCfg()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setSaving(false)
    }
  }

  // —— 配置历史 / 回滚 ——
  async function readConfig() {
    setBusy(true)
    setErr('')
    try {
      const [c, v] = await Promise.all([api.configGet(ckey.trim()), api.configVersions(ckey.trim())])
      setConfig(c)
      setVersions(v.versions)
      setHistVal(null)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function writeConfig() {
    setBusy(true)
    try {
      let parsed: unknown = cval
      try {
        parsed = JSON.parse(cval)
      } catch {
        parsed = cval
      }
      const r = await api.configSet({ key: ckey.trim(), value: parsed })
      toast(`已写入新版本 version=${r.version}`)
      await readConfig()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  async function viewVersionBy(v: number) {
    setBusy(true)
    setErr('')
    try {
      setHistVal(await api.configVersionGet(ckey.trim(), v))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function rollbackTo(v: number) {
    if (!histVal) return
    setBusy(true)
    try {
      const r = await api.configSet({ key: ckey.trim(), value: histVal.value })
      toast(`已回滚到 version ${v}，并写入为新版本 version=${r.version}`)
      setConfig(await api.configGet(ckey.trim()))
      setHistVal(null)
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  // —— Feature Flag ——
  async function syncFlagState(key = fkey.trim()) {
    if (!key) {
      setFlagOn(null)
      return
    }
    setFlagLoading(true)
    try {
      const r = await api.flagGet(key)
      setFlagOn(r.enabled)
    } catch {
      setFlagOn(null)
    } finally {
      setFlagLoading(false)
    }
  }

  async function setFlag() {
    setBusy(true)
    try {
      const pct = Math.max(0, Math.min(100, Number(fpct) || 0))
      await api.flagSet({ key: fkey.trim(), rules: { percentage: pct }, enabled: flagEnabled })
      toast(flagEnabled ? `Flag ${fkey} 已启用（放量 ${pct}%）` : `Flag ${fkey} 已保存为停用状态（放量 ${pct}%）`)
      await syncFlagState(fkey.trim())
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy(false)
    }
  }

  // —— 密钥 ——
  async function addSecret() {
    if (!secRef.trim() || !secValue) return
    setSecBusy(true)
    setSecErr('')
    try {
      await api.secretSet(secRef.trim(), secValue)
      setSecRef('')
      setSecValue('')
      setSecOpen(false)
      refreshSecrets()
    } catch (e) {
      setSecErr((e as Error).message)
    } finally {
      setSecBusy(false)
    }
  }

  async function removeSecret(ref: string) {
    setSecBusy(true)
    setSecErr('')
    try {
      await api.secretDelete(ref)
      refreshSecrets()
    } catch (e) {
      setSecErr((e as Error).message)
    } finally {
      setSecBusy(false)
    }
  }

  const pct = Math.max(0, Math.min(100, Number(fpct) || 0))
  const flagStateLabel = flagLoading ? '同步中' : flagOn === null ? '未同步' : flagOn ? '已启用' : '已停用'
  const flagStateTone = flagOn === null ? 'DRAFT' : flagOn ? 'ACTIVE' : 'FAILED'
  const flagActionLabel = flagEnabled ? '启用' : '停用'
  const flagActionTone = flagEnabled ? 'ACTIVE' : 'FAILED'

  return (
    <div>
      {confirmEl}
      <PageHeader
        title="配置控制台"
        desc="模型接入、运行参数、密钥统一在这里；改动即时生效，影响对话、任务与发布。"
        actions={
          <>
            <Link className="btn" to="/model">看模型健康</Link>
            <Button
              onClick={() => {
                resetOnboarding()
                setOnboardingOpen(true)
              }}
            >
              快速开始
            </Button>
          </>
        }
      />

      {/* 状态总览 + 主动作 */}
      <Card className="mb">
        <div className="cc-overview">
          <div className="cc-overview-item">
            <span className="cc-overview-label">模型接入</span>
            <span className="cc-overview-value">{cfg ? (cfg.is_mock ? <Badge status="WARN">模拟</Badge> : <Badge status="PASS">已接入</Badge>) : '…'}</span>
          </div>
          <div className="cc-overview-item">
            <span className="cc-overview-label">版本配置</span>
            <span className="cc-overview-value">{config ? `v${config.version}` : '—'}</span>
          </div>
          <div className="cc-overview-item">
            <span className="cc-overview-label">Feature Flag</span>
            <span className="cc-overview-value">{flagOn === null ? '—' : flagOn ? <Badge status="ACTIVE">放量中</Badge> : <Badge status="FAILED">未启用</Badge>}</span>
          </div>
          <div className="cc-overview-item">
            <span className="cc-overview-label">密钥</span>
            <span className="cc-overview-value">{secrets.length} 个</span>
          </div>
          <div className="cc-overview-action">
            {cfg?.is_mock ? (
              <Button tone="primary" onClick={() => document.getElementById('cc-model')?.scrollIntoView({ behavior: 'smooth' })}>去接模型</Button>
            ) : (
              <Button tone="primary" onClick={() => document.getElementById('cc-config')?.scrollIntoView({ behavior: 'smooth' })}>去写版本配置</Button>
            )}
          </div>
        </div>
      </Card>

      <div className="cc-section-title">基础配置</div>

      {/* 模型接入 */}
      <Card title="模型接入" id="cc-model">
        {!cfg ? (
          <span className="muted small">加载中…</span>
        ) : (
          <div className="grid cols-2">
            <div>
              <Field label="Provider">
                <select value={form.provider} onChange={(e) => setForm({ ...form, provider: e.target.value })}>
                  <option value="mock">mock（本地确定性）</option>
                  <option value="openai">openai（兼容网关）</option>
                </select>
              </Field>
              {form.provider === 'openai' && (
                <>
                  <Field label="模型（如 gpt-4o-mini / deepseek-chat）">
                    <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="gpt-4o-mini" />
                  </Field>
                  <Field label="base_url（OpenAI 兼容端点）">
                    <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com/v1" />
                  </Field>
                  <Field label="API key">
                    <div style={{ position: 'relative' }}>
                      <input
                        type={showKey ? 'text' : 'password'}
                        value={form.api_key}
                        onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                        placeholder="sk-…（留空保持不变）"
                        autoComplete="off"
                        style={{ paddingRight: 34 }}
                      />
                      <button
                        type="button"
                        onClick={() => setShowKey((v) => !v)}
                        title={showKey ? '隐藏' : '显示'}
                        style={{ position: 'absolute', right: 6, top: '50%', transform: 'translateY(-50%)', display: 'inline-flex', padding: 2, border: 'none', background: 'none', color: 'var(--text-3)', cursor: 'pointer' }}
                      >
                        {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
                      </button>
                    </div>
                  </Field>
                </>
              )}
              <div className="row" style={{ gap: 8 }}>
                <Button tone="primary" disabled={saving || !form.provider || !can('model:configure')} onClick={saveModel}>
                  {saving ? '保存中…' : '保存并应用'}
                </Button>
                {formDirty && <span className="cc-dirty">已修改，未保存</span>}
              </div>
            </div>
            <div>
              <div className="row">
                <span>当前 <Badge status={cfg.is_mock ? 'MOCK' : 'READY'} /> {cfg.provider} · {cfg.model || '—'}</span>
                <span className="small muted">API key：{cfg.has_key ? '已配置' : '未配置'}</span>
              </div>
              <p className="small muted mt mb">
                Provider 选 openai 后才会显示模型 / base_url / API key 字段。保存后即时生效，从 mock 切到真实模型会明确提示。
              </p>
              {modelReady ? (
                <div style={{ background: '#f0fdf4', padding: 12, borderRadius: 8, fontSize: 13 }}>
                  真实模型已接入，可直接去「对话」或「任务运行」验证；错误率升高再回「模型健康」调流量。
                </div>
              ) : (
                <div style={{ background: '#f9fafb', padding: 12, borderRadius: 8, fontSize: 13 }}>
                  mock 为本地确定性模型（无需 key，可完整体验）。接真实 LLM：Provider 选 openai，填模型、base_url 与 API key，保存即可。
                </div>
              )}
            </div>
          </div>
        )}
      </Card>

      <div className="cc-section-title">运行配置</div>

      <div className="grid cols-2" style={{ alignItems: 'stretch' }}>
        <Card title="版本配置 · 配置历史" id="cc-config">
          <div className="row">
            <input value={ckey} onChange={(e) => setCkey(e.target.value)} placeholder="key，如 max_steps" style={{ flex: 1 }} />
            <Button disabled={busy} onClick={readConfig}>读取</Button>
          </div>
          {config && (
            <div className="mt small" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="cc-version-current">
                <span className="cc-version-tag">当前</span>
                <code>{JSON.stringify(config.value)}</code>
                <span className="muted">version {config.version ?? '—'}</span>
              </div>
              {versions.length > 0 && (
                <div className="cc-version-list">
                  {versions.map((v) => {
                    const isCurrent = v.version === config.version
                    const isViewing = histVal?.version === v.version
                    return (
                      <div key={v.version} className={`cc-version-row${isCurrent ? ' current' : ''}${isViewing ? ' viewing' : ''}`}>
                        <button type="button" className="cc-version-main" onClick={() => viewVersionBy(v.version)}>
                          <span className="cc-version-num">v{v.version}</span>
                          <code>{JSON.stringify(v.value)}</code>
                        </button>
                        <span className="muted cc-version-time">{v.created_at ? fmtTime(v.created_at) : ''}</span>
                        {isCurrent && <span className="cc-version-tag">当前</span>}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}
          <div className="mt">
            <Field label="写入新值（JSON 或字符串）">
              <input value={cval} onChange={(e) => setCval(e.target.value)} />
            </Field>
            <Button tone="primary" disabled={busy || !ckey.trim() || !can('config:write')} onClick={writeConfig}>写入新版本</Button>
          </div>
          {histVal && (
            <div className="mt cc-version-hist">
              <div className="small">
                <span className="muted">version {histVal.version}：</span>
                <code>{JSON.stringify(histVal.value)}</code>
              </div>
              <Button disabled={busy} onClick={() => rollbackTo(Number(histVal.version ?? 0))}>回滚到此版本</Button>
            </div>
          )}
        </Card>

        <Card title="新功能灰度放量（Feature Flag）">
          <div className="small muted" style={{ marginBottom: 10 }}>
            想给某个新能力/行为做灰度：先开一个「功能开关」，把放量比例从 0% 慢慢提到 100%，观察没问题再全量。开关只影响运行参数，不影响配置历史。
          </div>
          <div className="cc-flag-shell">
            <div className="cc-flag-top">
              <Field label="功能开关名称（Flag Key）">
                <input value={fkey} onChange={(e) => setFkey(e.target.value)} onBlur={() => void syncFlagState(fkey.trim())} />
              </Field>
              <div className="cc-flag-state">
                <div className="cc-flag-state-head">
                  <span className="small muted">当前状态</span>
                  <Button className="cc-flag-refresh" disabled={flagLoading} onClick={() => void syncFlagState()}>
                    <RefreshCw size={14} />
                    刷新
                  </Button>
                </div>
                <div className="cc-flag-state-value">
                  <Badge status={flagStateTone}>{flagStateLabel}</Badge>
                  <span className="small muted">{flagLoading ? '正在同步当前配置' : `当前查看：${fkey.trim() || '未填写'}`}</span>
                </div>
              </div>
            </div>

            <div className="cc-flag-summary">
              <div className="cc-flag-summary-item">
                <span className="cc-flag-summary-label">本次放量</span>
                <span className="cc-flag-summary-value">{pct}%</span>
              </div>
              <div className="cc-flag-summary-item">
                <span className="cc-flag-summary-label">提交动作</span>
                <span className="cc-flag-summary-value"><Badge status={flagActionTone}>{flagActionLabel}</Badge></span>
              </div>
              <div className="cc-flag-summary-item">
                <span className="cc-flag-summary-label">实际命中</span>
                <span className="cc-flag-summary-value">{flagOn === null ? '未同步' : flagOn ? '放量中' : '未放量'}</span>
              </div>
            </div>

            <Field label={`放量 ${pct}%`}>
              <Slider value={pct} min={0} max={100} step={5} onValueChange={(v) => setFpct(String(v))} />
              <div className="cc-range-labels">
                <span>0%</span>
                <span>50%</span>
                <span>100%</span>
              </div>
            </Field>

            <div className="cc-flag-switch">
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={flagEnabled} onCheckedChange={setFlagEnabled} />
                {flagEnabled ? '已启用（真正放量）' : '仅配置，未启用'}
              </label>
            </div>

            <div className="cc-flag-actions">
              <Button tone="primary" disabled={busy || !fkey.trim() || !can('flags:write')} onClick={setFlag}>保存并{flagEnabled ? '启用' : '停用'}</Button>
              <span className="small muted">保存后会立即刷新当前状态。</span>
            </div>
          </div>
        </Card>
      </div>

      {err && <div className="mt"><ErrorBox message={err} /></div>}
      

      <div className="cc-section-title">安全配置</div>

      <Card title="密钥管理 · 凭据仓库">
        <div className="row mb" style={{ justifyContent: 'space-between' }}>
          <span className="small muted">只展示 ref，值加密落库；新增 / 替换走弹窗。</span>
          <Button tone="primary" disabled={!can('policy:manage')} onClick={() => setSecOpen(true)}>新增密钥</Button>
        </div>
        {secErr && <div className="mb"><ErrorBox message={secErr} /></div>}
        {secrets.length === 0 ? (
          <div className="cc-empty">
            还没有密钥。<Button onClick={() => setSecOpen(true)}>新增第一个密钥</Button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {secrets.map((s) => (
              <div key={s.ref} className="row spread" style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '8px 12px' }}>
                <span className="mono small">{s.ref}</span>
                <div className="row" style={{ gap: 6 }}>
                  <Button disabled={secBusy} onClick={() => { navigator.clipboard?.writeText(s.ref) }}>复制 ref</Button>
                  <Button disabled={secBusy} onClick={() => { setSecRef(s.ref); setSecValue(''); setSecErr(''); setSecOpen(true) }}>替换</Button>
                  <Button tone="danger" disabled={secBusy} onClick={() => confirm('删除密钥', `确定删除密钥「${s.ref}」吗？引用它的配置会失效。`, () => removeSecret(s.ref), { danger: true, confirmText: '删除' })}>删除</Button>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Sheet open={secOpen} onOpenChange={(o) => !o && setSecOpen(false)}>
      <SheetContent side="right" className="w-[440px] max-w-[440px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>密钥</SheetTitle>
        </SheetHeader>
        <div className="px-4">
        <Field label="ref（如 llm.key）">
          <input value={secRef} onChange={(e) => setSecRef(e.target.value)} placeholder="llm.key" />
        </Field>
        <Field label="值（仅本次输入，保存后不可再查看）">
          <input value={secValue} onChange={(e) => setSecValue(e.target.value)} placeholder="sk-…" type="password" autoComplete="off" />
        </Field>
        {secErr && <div className="mb"><ErrorBox message={secErr} /></div>}
        <div className="row">
          <Button tone="primary" disabled={secBusy || !secRef.trim() || !secValue} onClick={addSecret}>
            {secBusy ? '保存中…' : '保存'}
          </Button>
          <Button onClick={() => setSecOpen(false)}>取消</Button>
        </div>
              </div>
      </SheetContent>
    </Sheet>

      <Onboarding open={onboardingOpen} onClose={() => setOnboardingOpen(false)} />
    </div>
  )
}
