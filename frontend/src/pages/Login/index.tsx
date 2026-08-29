import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/api'
import { DEMO_LOGIN } from '@/constants/product'
import { fillDemoLogin, getLoginDraft, persistLoginIdentity } from '@/util/loginDraft'
import { Button, Card, ErrorBox, Field, PasswordInput } from '@/components/ui'
import { History, Sparkles } from 'lucide-react'

export default function Login() {
  const navigate = useNavigate()
  const draft = getLoginDraft()
  const [tenant, setTenant] = useState(draft.tenant)
  const [user, setUser] = useState(draft.user)
  const [password, setPassword] = useState(draft.password)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (busy || !tenant.trim() || !user.trim()) return
    setBusy(true)
    setErr('')
    try {
      await api.login(tenant.trim(), user.trim(), password)
      persistLoginIdentity(tenant, user)
      navigate('/', { replace: true })
    } catch (ex) {
      setErr((ex as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #eef2f7, #e2e8f0)',
        padding: 24,
      }}
    >
      <div style={{ width: 360 }}>
        <div className="brand-loading" style={{ justifyContent: 'center', marginBottom: 14, color: 'var(--text)' }}>
          <span className="brand-dot" />
          <span>Agent 发布与治理平台</span>
        </div>
        <Card title="登录">
          <form onSubmit={submit}>
            <Field label="组织标识">
              <input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="输入组织标识" autoFocus />
            </Field>
            <Field label="用户名">
              <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="输入用户名" />
            </Field>
            <Field label="密码">
              <PasswordInput
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入密码"
                autoComplete="current-password"
              />
            </Field>
            <div className="login-actions">
              <Button type="button" onClick={() => {
                const demo = fillDemoLogin()
                setTenant(demo.tenant)
                setUser(demo.user)
                setPassword(demo.password)
              }}>
                <Sparkles size={14} />
                一键填充示例账号
              </Button>
              <Button type="button" onClick={() => {
                const last = getLoginDraft()
                setTenant(last.tenant)
                setUser(last.user)
                setPassword('')
              }}>
                <History size={14} />
                恢复上次租户
              </Button>
            </div>
            <p className="small muted" style={{ marginTop: 10 }}>
              体验账号：{DEMO_LOGIN.tenant} / {DEMO_LOGIN.user} / {DEMO_LOGIN.password}
            </p>
            {err && <div className="mb"><ErrorBox message={err} /></div>}
            <Button tone="primary" type="submit" disabled={busy || !tenant.trim() || !user.trim()}>
              {busy ? '登录中…' : '登录'}
            </Button>
            <p className="small muted" style={{ marginTop: 14, textAlign: 'center' }}>
              © Agent 发布与治理平台
            </p>
          </form>
        </Card>
      </div>
    </div>
  )
}
