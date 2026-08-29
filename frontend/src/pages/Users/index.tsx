import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useRequest } from 'ahooks'
import { Pagination } from '@/components/pagination'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/sheet'
import { api, UserRow } from '@/services'
import { Badge, Button, Card, Field, PasswordInput, PermissionDenied, TableSkeleton } from '@/components'
import { EmptyState, PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'
import { toast } from '@/toast'

const PAGE_SIZE = 10

type AcctType = 'user' | 'admin' | 'custom'

/** 账户类型 → 角色模板：按角色名关键词识别「基础/管理员」，底层仍是角色，不新增 is_admin 字段。 */
const ADMIN_KEYWORDS = ['admin', '管理员']
const BASE_KEYWORDS = ['member', 'user', '成员', '用户', '基础', '普通']
function roleMatches(name: string, keywords: string[]) {
  const n = (name || '').toLowerCase()
  return keywords.some((k) => n.includes(k.toLowerCase()))
}

function userTypeOf(u: UserRow, adminRoles: { id: string }[], baseRoles: { id: string }[]): AcctType {
  const ids = u.role_ids ?? []
  if (ids.some((id) => adminRoles.some((r) => r.id === id))) return 'admin'
  if (ids.length === 0 || ids.every((id) => baseRoles.some((r) => r.id === id))) return 'user'
  return 'custom'
}
const ACCT_LABEL: Record<AcctType, string> = { user: '基础成员', admin: '管理员', custom: '自定义' }
const ACCT_BADGE_STATUS: Record<AcctType, string> = { user: 'READY', admin: 'PASS', custom: 'DRAFT' }

export default function Users() {
  const { can } = usePermissions()
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, refresh } = useRequest(
    () => Promise.all([api.users(), api.roles(), api.tenants()]),
    { onError: (e) => { if ((e as Error & { status?: number }).status === 403) setDenied(true) } },
  )
  const rows = data?.[0].users ?? null
  const roles = data?.[1].roles ?? []
  const adminRoles = roles.filter((r) => roleMatches(r.name, ADMIN_KEYWORDS))
  const baseRoles = roles.filter((r) => roleMatches(r.name, BASE_KEYWORDS))
  const [denied, setDenied] = useState(false)
  const [busy, setBusy] = useState('')
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<UserRow | null>(null)
  const [userId, setUserId] = useState('')
  const [email, setEmail] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [roleIds, setRoleIds] = useState<string[]>([])
  const [acctType, setAcctType] = useState<AcctType>('user')
  const [userPage, setUserPage] = useState(1)
  const [tenantPage, setTenantPage] = useState(1)
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
    setAcctType('user')
    setRoleIds(baseRoles.map((r) => r.id))
    setOpen(true)
  }

  function openEdit(u: UserRow) {
    const ids = u.role_ids ?? []
    const hasAdmin = ids.some((id) => adminRoles.some((r) => r.id === id))
    const allBase = ids.length > 0 && ids.every((id) => baseRoles.some((r) => r.id === id))
    setEditing(u)
    setUserId(u.id)
    setEmail(u.email)
    setDisplayName(u.display_name)
    setPassword('')
    setEnabled(u.enabled)
    setAcctType(hasAdmin ? 'admin' : allBase ? 'user' : 'custom')
    setRoleIds(ids)
    setOpen(true)
  }

  function selectAcct(t: AcctType) {
    setAcctType(t)
    if (t === 'user') setRoleIds(baseRoles.map((r) => r.id))
    else if (t === 'admin') setRoleIds(adminRoles.map((r) => r.id))
    // custom：保留当前已选角色，不做自动改写
  }

  async function save() {
    if (!userId.trim()) return
    setBusy('save')
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
      toast(editing ? '用户已更新' : '用户已创建')
      setOpen(false)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy('')
    }
  }

  async function toggleEnabled(u: UserRow) {
    setBusy(u.id)
    try {
      await api.userUpdate(u.id, { enabled: !u.enabled })
      toast(u.enabled ? '用户已禁用' : '用户已启用')
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    } finally {
      setBusy('')
    }
  }

  async function remove(u: UserRow) {
    setBusy(u.id)
    try {
      await api.userDelete(u.id)
      toast('用户已删除')
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
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
    try {
      await api.tenantCreate({
        name: tName.trim(),
        tenant_id: tId.trim() || undefined,
        admin_user_id: tAdmin.trim(),
        admin_password: tAdminPwd || undefined,
      })
      toast('租户已创建')
      setTName('')
      setTId('')
      setTAdmin('')
      setTAdminPwd('')
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
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
          <PasswordInput
            value={tAdminPwd}
            onChange={(e) => setTAdminPwd(e.target.value)}
            placeholder="管理员密码"
            autoComplete="new-password"
            wrapperStyle={{ maxWidth: 140 }}
          />
          <Button tone="primary" disabled={tBusy || !tName.trim() || !tAdmin.trim()} onClick={createTenant}>
            {tBusy ? '创建中…' : '创建租户'}
          </Button>
        </div>
        {tenants.length > 0 && (
          <>
            <table className="tbl">
              <thead>
                <tr>
                  <th>租户 ID</th>
                  <th>名称</th>
                </tr>
              </thead>
              <tbody>
                {tenants.slice((tenantPage - 1) * PAGE_SIZE, tenantPage * PAGE_SIZE).map((t) => (
                  <tr key={t.id}>
                    <td className="mono small">{t.id}</td>
                    <td className="small">{t.name}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {tenants.length > PAGE_SIZE && (
              <div className="row mt" style={{ justifyContent: 'flex-end' }}>
                <Pagination current={tenantPage} pageSize={PAGE_SIZE} total={tenants.length} onChange={setTenantPage} />
              </div>
            )}
          </>
        )}
      </Card>

      <Card title={`用户（${rows?.length ?? '…'}）`}>
        <div className="row mb">
          <Button tone="primary" disabled={!can('policy:manage')} onClick={openNew}>新建用户</Button>
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
                <th>账户类型</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).slice((userPage - 1) * PAGE_SIZE, userPage * PAGE_SIZE).map((u) => (
                <tr key={u.id}>
                  <td className="mono small">
                    {u.id}
                  </td>
                  <td className="small">{u.email}</td>
                  <td className="small">{u.display_name || '—'}</td>
                  <td className="small">
                    <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
                      <Badge status={ACCT_BADGE_STATUS[userTypeOf(u, adminRoles, baseRoles)]}>
                        {ACCT_LABEL[userTypeOf(u, adminRoles, baseRoles)]}
                      </Badge>
                      {u.must_change_password && <Badge status="WARN">待改密</Badge>}
                    </div>
                  </td>
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
        {(rows?.length ?? 0) > PAGE_SIZE && (
          <div className="row mt" style={{ justifyContent: 'flex-end' }}>
            <Pagination current={userPage} pageSize={PAGE_SIZE} total={rows?.length ?? 0} onChange={setUserPage} />
          </div>
        )}
      </Card>

      <Sheet open={open} onOpenChange={(o) => !o && setOpen(false)}>
      <SheetContent side="right" className="w-[480px] max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{editing ? `编辑用户 ${editing.id}` : '新建用户'}</SheetTitle>
        </SheetHeader>
        <div className="px-4">
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
          <PasswordInput
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="新密码"
            autoComplete="new-password"
          />
        </Field>
        {editing && (
          <Field label="启用">
            <select value={enabled ? '1' : '0'} onChange={(e) => setEnabled(e.target.value === '1')}>
              <option value="1">启用</option>
              <option value="0">禁用</option>
            </select>
          </Field>
        )}
        <Field label="账户类型">
          <div className="acct-type-grid">
            {([
              { t: 'user', title: '基础成员', desc: '可对话、使用知识库、评测与发布' },
              { t: 'admin', title: '管理员', desc: '用户管理、权限策略等治理能力' },
              { t: 'custom', title: '自定义', desc: '手动挑选下方角色' },
            ] as { t: AcctType; title: string; desc: string }[]).map((c) => (
              <button key={c.t} type="button" className={`acct-card${acctType === c.t ? ' on' : ''}`} onClick={() => selectAcct(c.t)}>
                <b>{c.title}</b>
                <span>{c.desc}</span>
              </button>
            ))}
          </div>
        </Field>
        {acctType === 'admin' && (
          <div className="acct-hint admin">
            将获得用户管理、权限策略等管理能力。
            {adminRoles.length === 0 && (
              <span> 当前还没有「管理员」角色，<Link to="/policies">去权限策略创建</Link>。</span>
            )}
          </div>
        )}
        {acctType === 'user' && (
          <div className="acct-hint">
            将获得基础使用能力。
            {baseRoles.length > 0 && <span> 默认勾选：{baseRoles.map((r) => r.name).join('、')}。</span>}
          </div>
        )}
        {(acctType === 'user' || acctType === 'admin') && roleIds.length > 0 && (
          <div className="acct-roles">已应用：{roleIds.map((id) => roles.find((r) => r.id === id)?.name).filter(Boolean).join('、')}</div>
        )}
        {acctType === 'custom' && (
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
        )}
        <Button tone="primary" disabled={busy === 'save' || !userId.trim()} onClick={save}>
          {busy === 'save' ? '保存中…' : '保存'}
        </Button>
              </div>
      </SheetContent>
    </Sheet>
    </div>
  )
}
