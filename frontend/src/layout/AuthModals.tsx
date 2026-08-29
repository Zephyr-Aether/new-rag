import { useState } from 'react'
import { api } from '../services'
import { Button, ErrorBox, Field, Modal, PasswordInput } from '../components'
import { DEMO_LOGIN } from '../constants'
import { fillDemoLogin, getLoginDraft, persistLoginIdentity } from '../util'
import { History, Sparkles } from 'lucide-react'

interface LoginResult {
  must_change_password?: boolean
}

export function LoginModal({
  onClose,
  onLoggedIn,
}: {
  onClose: () => void
  onLoggedIn: (r: LoginResult, currentPassword: string) => void
}) {
  const draft = getLoginDraft()
  const [tenant, setTenant] = useState(draft.tenant)
  const [user, setUser] = useState(draft.user)
  const [password, setPassword] = useState('')
  const [authErr, setAuthErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function doLogin() {
    setBusy(true)
    setAuthErr('')
    try {
      const r = await api.login(tenant.trim(), user.trim(), password)
      persistLoginIdentity(tenant, user)
      onLoggedIn(r, password)
    } catch (e) {
      setAuthErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="登录" onClose={onClose}>
      <Field label="租户">
        <input value={tenant} onChange={(e) => setTenant(e.target.value)} placeholder="tenant" />
      </Field>
      <Field label="用户">
        <input value={user} onChange={(e) => setUser(e.target.value)} placeholder="user" />
      </Field>
      <Field label="密码">
        <PasswordInput
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="密码（体验账号 admin123）"
          autoComplete="current-password"
          onKeyDown={(e) => e.key === 'Enter' && doLogin()}
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
      <p className="small muted" style={{ margin: '6px 0 14px' }}>
        体验账号：{DEMO_LOGIN.tenant} / {DEMO_LOGIN.user} / {DEMO_LOGIN.password}
      </p>
      {authErr && <div className="mb"><ErrorBox message={authErr} /></div>}
      <Button tone="primary" disabled={busy} onClick={doLogin}>
        {busy ? '登录中…' : '登录'}
      </Button>
    </Modal>
  )
}

export function ChangePasswordModal({
  currentPassword,
  onChanged,
}: {
  currentPassword: string
  onChanged: () => void
}) {
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdErr, setPwdErr] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)

  async function doChangePassword() {
    if (newPwd.length < 6) { setPwdErr('新密码至少 6 位'); return }
    if (newPwd !== confirmPwd) { setPwdErr('两次输入不一致'); return }
    setPwdBusy(true)
    setPwdErr('')
    try {
      await api.changePassword(currentPassword, newPwd)
      setNewPwd('')
      setConfirmPwd('')
      onChanged()
    } catch (e) {
      setPwdErr((e as Error).message)
    } finally {
      setPwdBusy(false)
    }
  }

  return (
    <Modal title="首次登录需修改密码" onClose={() => { /* 强制，不可关闭 */ }}>
      <p className="small muted mb">为安全起见，请设置您自己的密码。</p>
      <Field label="新密码（至少 6 位）">
        <PasswordInput
          value={newPwd}
          onChange={(e) => setNewPwd(e.target.value)}
          placeholder="新密码"
          autoComplete="new-password"
        />
      </Field>
      <Field label="确认新密码">
        <PasswordInput
          value={confirmPwd}
          onChange={(e) => setConfirmPwd(e.target.value)}
          placeholder="再输入一次"
          autoComplete="new-password"
          onKeyDown={(e) => e.key === 'Enter' && doChangePassword()}
        />
      </Field>
      {pwdErr && <div className="mb"><ErrorBox message={pwdErr} /></div>}
      <Button tone="primary" disabled={pwdBusy} onClick={doChangePassword}>
        {pwdBusy ? '提交中…' : '修改密码'}
      </Button>
    </Modal>
  )
}
