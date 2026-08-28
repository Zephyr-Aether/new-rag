import { useEffect, useState } from 'react'
import { useRequest } from 'ahooks'
import { Link } from 'react-router-dom'
import { Eye, EyeOff } from 'lucide-react'
import { api } from '../api'
import { Badge, Button, Card, ErrorBox, Field, SuccessBox } from '../components/ui'
import { PageHeader } from '../components/Page'
import Onboarding, { resetOnboarding } from '../components/Onboarding'
import { toast } from '../toast'
import { usePermissions } from '../hooks/usePermissions'

export default function ConfigCenter() {
  const [ckey, setCkey] = useState('max_steps')
  const [cval, setCval] = useState('20')
  const [config, setConfig] = useState<{ key: string; value: unknown; version: number | null } | null>(null)
  const [fkey, setFkey] = useState('new_flow')
  const [fpct, setFpct] = useState('10')
  const [flagOn, setFlagOn] = useState<boolean | null>(null)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [onboardingOpen, setOnboardingOpen] = useState(false)
  const [form, setForm] = useState({ provider: 'mock', model: '', base_url: '', api_key: '' })
  const [saving, setSaving] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const { can } = usePermissions()
  // 密钥管理（§6.5 加密落库）
  const [secRef, setSecRef] = useState('')
  const [secValue, setSecValue] = useState('')
  const [secBusy, setSecBusy] = useState(false)
  const [secErr, setSecErr] = useState('')

  const { data: cfg, refresh: refreshCfg } = useRequest(() => api.modelConfig())
  const { data: secData, refresh: refreshSecrets } = useRequest(() => api.secrets())
  const secrets = secData?.secrets ?? []
  const modelReady = !!cfg && !cfg.is_mock
  const configHint = !cfg
    ? { text: '正在读取模型与密钥状态，先等全局配置回包。', cta: '看模型健康', to: '/model' }
    : cfg.is_mock
      ? { text: '当前还是 mock 模式，建议先接真实模型，再把版本配置和 flag 固定下来。', cta: '去接入模型', to: '/settings' }
      : secrets.length === 0
        ? { text: '模型已经接入，接下来建议把密钥和版本配置整理好，方便对话、任务和发布共享。', cta: '看模型健康', to: '/model' }
        : { text: '模型、密钥和全局配置都已就绪，接下来可以继续收拢版本配置与放量规则。', cta: '看模型健康', to: '/model' }

  useEffect(() => {
    if (cfg) setForm((f) => ({ ...f, provider: cfg.provider, model: cfg.model, base_url: cfg.base_url }))
  }, [cfg])

  async function saveModel() {
    setSaving(true)
    try {
      const r = await api.modelConfigSet({
        provider: form.provider,
        model: form.model.trim(),
        base_url: form.base_url.trim(),
        api_key: form.api_key.trim(),
      })
      toast(r.is_mock ? '已保存（mock 模式）' : `已保存并切换到 ${r.provider} / ${r.model}`)
      refreshCfg()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setSaving(false)
    }
  }

  async function addSecret() {
    if (!secRef.trim() || !secValue) return
    setSecBusy(true)
    setSecErr('')
    try {
      await api.secretSet(secRef.trim(), secValue)
      setSecRef('')
      setSecValue('')
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

  async function readConfig() {
    setBusy(true)
    setErr('')
    try {
      setConfig(await api.configGet(ckey.trim()))
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function writeConfig() {
    setBusy(true)
    setMsg(null)
    try {
      let parsed: unknown = cval
      try {
        parsed = JSON.parse(cval)
      } catch {
        parsed = cval // 非 JSON 按字符串
      }
      const r = await api.configSet({ key: ckey.trim(), value: parsed })
      setMsg({ kind: 'ok', text: `配置已写入，version=${r.version}` })
      setConfig(await api.configGet(ckey.trim()))
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  async function setFlag() {
    setBusy(true)
    setMsg(null)
    try {
      const pct = Math.max(0, Math.min(100, Number(fpct) || 0))
      await api.flagSet({ key: fkey.trim(), rules: { percentage: pct }, enabled: true })
      setMsg({ kind: 'ok', text: `Flag ${fkey} 已设置（${pct}%）` })
      setFlagOn(await api.flagGet(fkey.trim()).then((r) => r.enabled))
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader
        title="配置 / Feature Flag"
        desc="模型接入、版本化配置、Feature Flag 和密钥都在这里；这里改动会同步影响对话、任务和发布。"
        actions={
          <>
            <Link className="btn" to="/model">看模型健康</Link>
            <Button
              onClick={() => {
                resetOnboarding()
                setOnboardingOpen(true)
              }}
            >
              重新看快速开始
            </Button>
          </>
        }
      />

      <div className="home-hint">
        <div className="home-hint-copy">
          <span className="home-hint-kicker">当前状态</span>
          <span>{configHint.text}</span>
          <span className="small muted" style={{ color: 'inherit' }}>模型 {cfg ? (cfg.is_mock ? '模拟' : '已接入') : '加载中'}，密钥 {secrets.length} 个。</span>
        </div>
        <Link className="btn primary" to={configHint.to}>{configHint.cta}</Link>
      </div>

      <Card title="模型接入">
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
              <Field label="模型（如 gpt-4o-mini / deepseek-chat）">
                <input value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} placeholder="mock-model" />
              </Field>
              <Field label="base_url（OpenAI 兼容端点）">
                <input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com/v1" />
              </Field>
              <Field label="API key（可选，留空保持不变）">
                <div style={{ position: 'relative' }}>
                  <input
                    type={showKey ? 'text' : 'password'}
                    value={form.api_key}
                    onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                    placeholder="sk-…"
                    autoComplete="off"
                    style={{ paddingRight: 34 }}
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((v) => !v)}
                    title={showKey ? '隐藏' : '显示'}
                    style={{
                      position: 'absolute',
                      right: 6,
                      top: '50%',
                      transform: 'translateY(-50%)',
                      display: 'inline-flex',
                      padding: 2,
                      border: 'none',
                      background: 'none',
                      color: 'var(--text-3)',
                      cursor: 'pointer',
                    }}
                  >
                    {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
                  </button>
                </div>
              </Field>
              <Button tone="primary" disabled={saving || !form.provider || !can('model:configure')} onClick={saveModel}>
                {saving ? '保存中…' : '保存并应用'}
              </Button>
            </div>
            <div>
              <div className="row">
                <span>当前 <Badge status={cfg.is_mock ? 'MOCK' : 'READY'} /> {cfg.provider} · {cfg.model}</span>
                <span className="small muted">API key：{cfg.has_key ? '已配置' : '未配置'}</span>
              </div>
              <p className="small muted mt mb">
                API key 可在此填写并持久化，或从 <code>.env</code> 的 <code>APP_LLM_API_KEY</code> 读取。
                保存后即时生效；「模型健康」页可看各模型状态与熔断器。
              </p>
              {modelReady ? (
                <div style={{ background: '#f0fdf4', padding: 12, borderRadius: 8, fontSize: 13 }}>
                  真实模型已经接入，可以直接去「对话」或「任务运行」页验证结果；如果出现错误率升高，再回到「模型健康」做流量调整。
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
      <div className="mt">
      <div className="grid cols-2" style={{ alignItems: 'start' }}>
      <div>
        <Card title="版本化配置（只增不改，回滚=读指定版本）">
          <div className="row">
            <input value={ckey} onChange={(e) => setCkey(e.target.value)} placeholder="key，如 max_steps" style={{ flex: 1 }} />
            <Button disabled={busy} onClick={readConfig}>读取</Button>
          </div>
          <div className="mt">
            <Field label="值（JSON 或字符串）">
              <input value={cval} onChange={(e) => setCval(e.target.value)} />
            </Field>
            <Button tone="primary" disabled={busy || !ckey.trim() || !can('config:write')} onClick={writeConfig}>写入新版本</Button>
          </div>
          {config && (
            <div className="mt small">
              <p>
                <span className="muted">当前值：</span>
                <code>{JSON.stringify(config.value)}</code> <span className="muted">（version {config.version ?? '—'}）</span>
              </p>
            </div>
          )}
        </Card>
        {err && <div className="mt"><ErrorBox message={err} /></div>}
        {msg && <div className="mt">{msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />}</div>}
      </div>

      <Card title="Feature Flag（按百分比放量）">
        <Field label="flag key">
          <input value={fkey} onChange={(e) => setFkey(e.target.value)} />
        </Field>
        <Field label="放量百分比">
          <input type="number" min={0} max={100} value={fpct} onChange={(e) => setFpct(e.target.value)} />
        </Field>
        <Button tone="primary" disabled={busy || !fkey.trim() || !can('flags:write')} onClick={setFlag}>设置并启用</Button>
        {flagOn !== null && (
          <p className="mt small">
            当前命中：<Badge status={flagOn ? 'ACTIVE' : 'FAILED'} /> {flagOn ? '放量中' : '未放量'}
          </p>
        )}
      </Card>

      <Card title="密钥（加密落库，供 Secret Reference 注入）">
        <div className="row mb">
          <input value={secRef} onChange={(e) => setSecRef(e.target.value)} placeholder="ref，如 llm.key" style={{ flex: 1 }} />
          <input value={secValue} onChange={(e) => setSecValue(e.target.value)} placeholder="值" style={{ flex: 1 }} />
          <Button tone="primary" disabled={secBusy || !secRef.trim() || !secValue || !can('policy:manage')} onClick={addSecret}>
            保存
          </Button>
        </div>
        {secErr && <div className="mb"><ErrorBox message={secErr} /></div>}
        {secrets.length === 0 ? (
          <span className="small muted">暂无密钥</span>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {secrets.map((s) => (
              <div key={s.ref} className="row spread">
                <span className="mono small">{s.ref}</span>
                <Button disabled={secBusy} onClick={() => removeSecret(s.ref)}>删除</Button>
              </div>
            ))}
          </div>
        )}
      </Card>
      </div>
      </div>
      <Onboarding open={onboardingOpen} onClose={() => setOnboardingOpen(false)} />
    </div>
  )
}
