import { useEffect, useState } from 'react'
import { useRequest } from 'ahooks'
import { Drawer } from 'antd'
import { api, UserRow } from '../api'
import { Badge, Button, Card, ErrorBox, Field, PermissionDenied, SuccessBox, TableSkeleton } from '../components/ui'
import { EmptyState, PageHeader } from '../components/Page'
import { useConfirm } from '../components/Confirm'
import { usePermissions } from '../hooks/usePermissions'

export default function Users() {
  const { can } = usePermissions()
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, refresh } = useRequest(
    () => Promise.all([api.users(), api.roles(), api.tenants()]),
    { onError: (e) => { if ((e as Error & { status?: number }).status === 403) setDenied(true) } },
  )
  const rows = data?.[0].users ?? null
  const roles = data?.[1].roles ?? []
  const [denied, setDenied] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [userId, setUserId] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [roleIds, setRoleIds] = useState<string[]>([])
  // 租户 onboarding
  const tenants = data?.[2].tenants ?? []
  const [tName, setTName] = useState('')
  const [tId, setTId] = useState('')
  const [tAdmin, setTAdmin] = useState('')
  const [tAdminPwd, setTAdminPwd] = useState('')
  const [tBusy, setTBusy] = useState(false)

  useEffect(() => {
    refresh()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openNew() {
    setEditing(null)
    setUserId('')
    setEmail('')
    setDisplayName('')
    setPassword('')
    setEnabled(true)
    setRoleIds([])
    setMsg(null)
    setOpen(true)
  }

  function openEdit(u: UserRow) {
    setEditing(u)
    setUserId(u.id)
    setEmail(u.email)
    setDisplayName(u.display_name)
    setPassword('')
    setEnabled(u.enabled)
    setRoleIds(u.role_ids ?? [])
    setMsg(null)
    setOpen(true)
  }

  async function save() {
    if (!userId.trim()) return
    setBusy('save')
    setMsg(null)
    try {
      if (editing) {
        await api.userUpdate(editing.id, {
          display_name: displayName.trim(),
          email: email.trim(),
          enabled,
          password: password || undefined,
          role_ids: roleIds,
        })
      } else {
        await api.userCreate({
          user_id: userId.trim(),
          email: email.trim(),
          display_name: displayName.trim(),
          password: password || undefined,
          role_ids: roleIds,
        })
      }
      setMsg({ kind: 'ok', text: editing ? '用户已更新' : '用户已创建' })
      setOpen(false)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  async function toggleEnabled(u: UserRow) {
    setBusy(u.id)
    try {
      await api.userUpdate(u.id, { enabled: !u.enabled })
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  async function remove(u: UserRow) {
    setBusy(u.id)
    try {
      await api.userDelete(u.id)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  function toggleRole(id: string) {
    setRoleIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  }

  if (denied) {
    return (
      <div>
        <PageHeader title="用户管理" desc="创建租户与组织，管理租户内的用户和密码" />
        <PermissionDenied />
      </div>
    )
  }

  async function createTenant() {
    if (!tName.trim() || !tAdmin.trim()) return
    setTBusy(true)
    setMsg(null)
    try {
      await api.tenantCreate({
        name: tName.trim(),
        tenant_id: tId.trim() || undefined,
        admin_user_id: tAdmin.trim(),
        admin_password: tAdminPwd || undefined,
      })
      setMsg({ kind: 'ok', text: '租户已创建' })
      setTName('')
      setTId('')
      setTAdmin('')
      setTAdminPwd('')
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setTBusy(false)
    }
  }

  return (
    <div>
      {confirmEl}
      <PageHeader title="用户管理" desc="创建租户与组织，管理租户内的用户和密码" />
      <Card title="租户（onboarding）" className="mb">
        <div className="home-hint" style={{ marginBottom: 12 }}>
          <div className="home-hint-copy">
            <span className="home-hint-kicker">建议顺序</span>
            <span>先建租户，再建角色，最后创建用户并分配角色。这样新用户登录后不会一头雾水。</span>
          </div>
        </div>
        <div className="row mb">
          <input value={tName} onChange={(e) => setTName(e.target.value)} placeholder="租户名" style={{ maxWidth: 160 }} />
          <input value={tId} onChange={(e) => setTId(e.target.value)} placeholder="租户 ID（留空自动）" style={{ maxWidth: 170 }} />
          <input value={tAdmin} onChange={(e) => setTAdmin(e.target.value)} placeholder="初始管理员 user_id" style={{ maxWidth: 170 }} />
          <input type="password" value={tAdminPwd} onChange={(e) => setTAdminPwd(e.target.value)} placeholder="管理员密码" style={{ maxWidth: 140 }} />
          <Button tone="primary" disabled={tBusy || !tName.trim() || !tAdmin.trim()} onClick={createTenant}>
            {tBusy ? '创建中…' : '创建租户'}
          </Button>
        </div>
        {tenants.length > 0 && (
          <div className="small" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {tenants.map((t) => (
              <span key={t.id} className="mono small" style={{ background: '#f1f5f9', borderRadius: 6, padding: '2px 8px' }}>
                {t.name} · {t.id}
              </span>
            ))}
          </div>
        )}
      </Card>

      <Card title={`用户（${rows?.length ?? '…'}）`}>
        <div className="row mb">
          <Button tone="primary" disabled={!can('policy:manage')} onClick={openNew}>新建用户</Button>
          {msg && (msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />)}
        </div>
        {loading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : (rows ?? []).length === 0 ? (
          <EmptyState
            title="还没有用户"
            desc="先创建一个租户和角色，再新建第一个用户。"
            action={openNew}
            actionLabel="新建用户"
          />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>显示名</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((u) => (
                <tr key={u.id}>
                  <td className="mono small">
                    {u.id}
                    {u.must_change_password && <span className="small" style={{ color: 'var(--warning)' }}> · 待改密</span>}
                  </td>
                  <td className="small">{u.email}</td>
                  <td className="small">{u.display_name || '—'}</td>
                  <td><Badge status={u.enabled ? 'PASS' : 'DISABLED'}>{u.enabled ? '启用' : '禁用'}</Badge></td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <Button disabled={busy === u.id} onClick={() => openEdit(u)}>编辑</Button>
                      <Button disabled={busy === u.id} onClick={() => toggleEnabled(u)}>{u.enabled ? '禁用' : '启用'}</Button>
                      <Button tone="danger" disabled={busy === u.id} onClick={() => confirm('删除用户', `确定删除用户「${u.display_name || u.id}」吗？此操作不可撤销。`, () => remove(u), { danger: true, confirmText: '删除' })}>删除</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Drawer title={editing ? `编辑用户 ${editing.id}` : '新建用户'} open={open} onClose={() => setOpen(false)}>
        <Field label="用户 ID">
          <input value={userId} disabled={!!editing} onChange={(e) => setUserId(e.target.value)} placeholder="user-abc" />
        </Field>
        <Field label="邮箱">
          <input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@example.com" />
        </Field>
        <Field label="显示名">
          <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="张三" />
        </Field>
        <Field label={editing ? '重置密码（留空不改）' : '密码'}>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="新密码" />
        </Field>
        {editing && (
          <Field label="启用">
            <select value={enabled ? '1' : '0'} onChange={(e) => setEnabled(e.target.value === '1')}>
              <option value="1">启用</option>
              <option value="0">禁用</option>
            </select>
          </Field>
        )}
        <Field label="角色">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {roles.length === 0 && <span className="small muted">暂无角色（可到「权限策略」页创建）</span>}
            {roles.map((r) => (
              <label key={r.id} className="small" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={roleIds.includes(r.id)} onChange={() => toggleRole(r.id)} />
                {r.name}
              </label>
            ))}
          </div>
        </Field>
        <Button tone="primary" disabled={busy === 'save' || !userId.trim()} onClick={save}>
          {busy === 'save' ? '保存中…' : '保存'}
        </Button>
      </Drawer>
    </div>
  )
}
