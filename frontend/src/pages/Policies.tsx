import { useEffect, useState } from 'react'
import { useRequest } from 'ahooks'
import { Drawer } from 'antd'
import { api } from '../api'
import { Badge, Button, Card, Empty, ErrorBox, Field, PermissionDenied, SuccessBox, TableSkeleton } from '../components/ui'
import { PageHeader } from '../components/Page'
import { useConfirm } from '../components/Confirm'
import { usePermissions } from '../hooks/usePermissions'

interface Policy {
  id: string
  user_id: string | null
  role_id: string | null
  name: string
  effect: string
  action: string
  resource: string
  enabled: boolean
}

export default function Policies() {
  const { can } = usePermissions()
  const { confirm, confirmEl } = useConfirm()
  const { data, loading, error, refresh } = useRequest(() =>
    Promise.all([api.policies(), api.roles(), api.policyMeta()]),
    { onError: (e) => { if ((e as Error & { status?: number }).status === 403) setDenied(true) } },
  )
  const rows = data?.[0].policies ?? null
  const roles = data?.[1].roles ?? []
  const [myPerms, setMyPerms] = useState<{ allowed: string[]; denied: string[] } | null>(null)
  const [denied, setDenied] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  const [busy, setBusy] = useState('')
  // 新增策略抽屉
  const [policyOpen, setPolicyOpen] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [action, setAction] = useState('')
  const [resource, setResource] = useState('*')
  const [effect, setEffect] = useState('ALLOW')
  const [userId, setUserId] = useState('')
  const [roleId, setRoleId] = useState('')
  // 角色
  const [newRole, setNewRole] = useState('')
  const [assign, setAssign] = useState<{ roleId: string; user: string } | null>(null)
  // 策略表单下拉数据（/policies/meta）
  const actions = data?.[2].actions ?? []
  const resources = data?.[2].resources ?? []
  const [resourceCustom, setResourceCustom] = useState(false)
  // 角色编辑
  const [roleEditOpen, setRoleEditOpen] = useState(false)
  const [editRoleId, setEditRoleId] = useState('')
  const [editRoleName, setEditRoleName] = useState('')
  const [editRoleDesc, setEditRoleDesc] = useState('')
  const [editRoleRename, setEditRoleRename] = useState(false)
  const [roleMsg, setRoleMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)

  useEffect(() => {
    refresh()
    api.authMe().then((r) => setMyPerms({ allowed: r.allowed ?? [], denied: r.denied ?? [] })).catch(() => setMyPerms(null))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openNew() {
    setEditingId(null)
    setAction('')
    setResource('*')
    setResourceCustom(false)
    setEffect('ALLOW')
    setUserId('')
    setRoleId('')
    setMsg(null)
    setPolicyOpen(true)
  }

  function editPolicy(p: Policy) {
    setEditingId(p.id)
    setAction(p.action)
    setEffect(p.effect)
    setUserId(p.user_id ?? '')
    setRoleId(p.role_id ?? '')
    setResource(p.resource ?? '*')
    setResourceCustom(!(p.resource && resources.some((r) => r.resource === p.resource)))
    setMsg(null)
    setPolicyOpen(true)
  }

  async function savePolicy() {
    if (!action.trim()) return
    setBusy('create')
    setMsg(null)
    const body = {
      action: action.trim(),
      resource: resource.trim() || '*',
      effect,
      user_id: userId.trim() || undefined,
      role_id: roleId || undefined,
    }
    try {
      if (editingId) await api.policyUpdate(editingId, body)
      else await api.policyCreate(body)
      setMsg({ kind: 'ok', text: editingId ? '策略已更新' : '已新增策略' })
      setPolicyOpen(false)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  async function removePolicy(id: string) {
    setBusy(id)
    try {
      await api.policyDelete(id)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    } finally {
      setBusy('')
    }
  }

  async function createRole() {
    if (!newRole.trim()) return
    try {
      await api.roleCreate({ name: newRole.trim() })
      setNewRole('')
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  function openRoleEdit() {
    setEditRoleId('')
    setEditRoleName('')
    setEditRoleDesc('')
    setEditRoleRename(false)
    setRoleMsg(null)
    setRoleEditOpen(true)
  }

  function selectRoleForEdit(id: string) {
    setEditRoleId(id)
    setEditRoleRename(false)
    setEditRoleName('')
    const r = roles.find((x) => x.id === id)
    setEditRoleDesc(r?.description ?? '')
  }

  async function saveRole() {
    if (!editRoleId || (editRoleRename && !editRoleName.trim())) return
    const body = editRoleRename
      ? { name: editRoleName.trim(), description: editRoleDesc }
      : { description: editRoleDesc }
    try {
      await api.roleUpdate(editRoleId, body)
      setRoleMsg({ kind: 'ok', text: '角色已更新' })
      setRoleEditOpen(false)
      refresh()
    } catch (e) {
      setRoleMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  async function deleteRole(id: string) {
    try {
      await api.roleDelete(id)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  async function doAssign(roleId: string, user: string) {
    try {
      await api.roleAddUser(roleId, user.trim())
      setAssign(null)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  async function removeUser(roleId: string, user: string) {
    try {
      await api.roleRemoveUser(roleId, user)
      refresh()
    } catch (e) {
      setMsg({ kind: 'err', text: (e as Error).message })
    }
  }

  const scopeLabel = (p: Policy) => {
    if (p.user_id) return <span className="mono">{p.user_id}（用户级）</span>
    if (p.role_id) return <span className="mono">{roles.find((r) => r.id === p.role_id)?.name ?? p.role_id}（角色级）</span>
    return <span className="muted">租户级</span>
  }

  if (denied) {
    return (
      <div>
        <PageHeader title="权限策略" desc="租户 / 角色 / 用户级别的权限规则；默认拒绝，DENY 优先" />
        <PermissionDenied />
      </div>
    )
  }

  return (
    <div>
      {confirmEl}
      <PageHeader title="权限策略" desc="租户 / 角色 / 用户级别的权限规则；默认拒绝，DENY 优先" />
      {error && <div className="mb"><ErrorBox message={(error as Error).message} /></div>}

      {myPerms && (
        <Card title="我的权限（当前登录用户）" className="mb">
          <div className="small muted mb">允许</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
            {myPerms.allowed.length ? (
              myPerms.allowed.map((a) => (
                <span key={a} className="mono small" style={{ background: '#ecfdf3', color: 'var(--success)', borderRadius: 6, padding: '2px 8px' }}>
                  {a}
                </span>
              ))
            ) : (
              <span className="small muted">无（default-deny）</span>
            )}
          </div>
          {myPerms.denied.length > 0 && (
            <>
              <div className="small muted mb">被拒绝</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {myPerms.denied.map((a) => (
                  <span key={a} className="mono small" style={{ background: '#fef2f2', color: 'var(--danger)', borderRadius: 6, padding: '2px 8px' }}>
                    {a}
                  </span>
                ))}
              </div>
            </>
          )}
        </Card>
      )}

      <Card title={`策略列表（${rows?.length ?? '…'}）`}>
        <div className="row mb">
          <Button tone="primary" disabled={!can('policy:manage')} onClick={openNew}>
            新增策略
          </Button>
          {msg && (msg.kind === 'ok' ? <SuccessBox message={msg.text} /> : <ErrorBox message={msg.text} />)}
        </div>
        {loading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : (rows ?? []).length === 0 ? (
          <Empty text="暂无策略" />
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>作用域</th>
                <th>动作</th>
                <th>资源</th>
                <th>效果</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {(rows ?? []).map((p) => (
                <tr key={p.id}>
                  <td className="small">{scopeLabel(p)}</td>
                  <td className="mono small">{p.action}</td>
                  <td className="mono small muted">{p.resource}</td>
                  <td>
                    <Badge status={p.effect === 'ALLOW' ? 'PASS' : 'FAIL'}>{p.effect === 'ALLOW' ? '允许' : '拒绝'}</Badge>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <Button disabled={!can('policy:manage')} onClick={() => editPolicy(p)}>编辑</Button>
                      <Button tone="danger" disabled={busy === p.id || !can('policy:manage')} onClick={() => confirm('删除权限策略', `确定删除策略「${p.name || p.id}」吗？对应权限将立即失效，此操作不可撤销。`, () => removePolicy(p.id), { danger: true, confirmText: '删除' })}>删除</Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <div className="mt">
        <Card title="角色（RBAC）">
          <div className="row mb">
            <input value={newRole} onChange={(e) => setNewRole(e.target.value)} placeholder="新角色名" style={{ maxWidth: 180 }} />
            <Button disabled={!newRole.trim() || !can('policy:manage')} onClick={createRole}>新建角色</Button>
            <Button disabled={!can('policy:manage')} onClick={openRoleEdit}>编辑角色</Button>
          </div>
          {roles.length === 0 ? (
            <Empty text="还没有角色" />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {roles.map((r) => (
                <div key={r.id} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 12px' }}>
                  <div className="row spread">
                    <div>
                      <span className="small" style={{ fontWeight: 600 }}>{r.name}</span>
                      {r.description && <span className="small muted"> · {r.description}</span>}
                    </div>
                    <Button tone="danger" disabled={!can('policy:manage')} onClick={() => confirm('删除角色', `确定删除角色「${r.id}」吗？将同时移除该角色下的所有用户与权限。`, () => deleteRole(r.id), { danger: true, confirmText: '删除角色' })}>删除角色</Button>
                  </div>
                  <div className="mt" style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    {r.users.map((u) => (
                      <span key={u} className="mono small" style={{ background: '#f1f5f9', borderRadius: 6, padding: '2px 8px' }}>
                        {u} <a className="link" onClick={() => removeUser(r.id, u)} style={{ marginLeft: 4 }}>×</a>
                      </span>
                    ))}
                    {assign?.roleId === r.id ? (
                      <span className="row" style={{ gap: 4 }}>
                        <input
                          value={assign.user} onChange={(e) => setAssign({ ...assign, user: e.target.value })}
                          placeholder="user_id" style={{ width: 120 }}
                          onKeyDown={(e) => e.key === 'Enter' && doAssign(r.id, assign.user)}
                        />
                        <Button disabled={!assign.user.trim()} onClick={() => doAssign(r.id, assign.user)}>添加</Button>
                      </span>
                    ) : (
                      <Button disabled={!can('policy:manage')} onClick={() => setAssign({ roleId: r.id, user: '' })}>添加用户</Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Drawer title={editingId ? '编辑策略' : '新增策略'} open={policyOpen} onClose={() => setPolicyOpen(false)}>
        <Field label="动作">
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            {action === '' && <option value="" disabled>请选择动作</option>}
            {(action && !actions.some((a) => a.action === action)
              ? [...actions, { action, name: action }]
              : actions
            ).map((a) => (
              <option key={a.action} value={a.action}>{a.name}（{a.action}）</option>
            ))}
          </select>
        </Field>
        <Field label="资源">
          <select value={resourceCustom ? '__custom' : resource} onChange={(e) => {
            const v = e.target.value
            if (v === '__custom') setResourceCustom(true)
            else { setResourceCustom(false); setResource(v) }
          }}>
            {resources.map((r) => (
              <option key={r.resource} value={r.resource}>{r.name ? `${r.name}（${r.resource}）` : r.resource}</option>
            ))}
            <option value="__custom">自定义…</option>
          </select>
          {resourceCustom && (
            <input value={resource} onChange={(e) => setResource(e.target.value)} placeholder="自定义资源，如 agent-abc / kb:123" />
          )}
        </Field>
        <Field label="效果">
          <select value={effect} onChange={(e) => setEffect(e.target.value)}>
            <option value="ALLOW">ALLOW（允许）</option>
            <option value="DENY">DENY（拒绝，优先）</option>
          </select>
        </Field>
        <Field label="角色（可选）">
          <select value={roleId} onChange={(e) => setRoleId(e.target.value)}>
            <option value="">（不限角色）</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
          </select>
        </Field>
        <Field label="用户（可选，留空=租户/角色级）">
          <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user-x" />
        </Field>
        <Button tone="primary" disabled={busy === 'create' || !action.trim()} onClick={savePolicy}>
          {busy === 'create' ? '保存中…' : '保存'}
        </Button>
      </Drawer>

      <Drawer title="编辑角色" open={roleEditOpen} onClose={() => setRoleEditOpen(false)}>
        <Field label="角色名">
          <select value={editRoleRename ? '__rename' : editRoleId} onChange={(e) => {
            const v = e.target.value
            if (v === '__rename') { setEditRoleRename(true); setEditRoleName('') }
            else if (v) selectRoleForEdit(v)
          }}>
            <option value="">请选择角色</option>
            {roles.map((r) => (
              <option key={r.id} value={r.id}>{r.name}</option>
            ))}
            <option value="__rename">重命名…</option>
          </select>
          {editRoleRename && (
            <input value={editRoleName} onChange={(e) => setEditRoleName(e.target.value)} placeholder="新角色名" />
          )}
        </Field>
        <Field label="描述">
          <input value={editRoleDesc} onChange={(e) => setEditRoleDesc(e.target.value)} placeholder="角色描述" />
        </Field>
        {roleMsg && (roleMsg.kind === 'ok' ? <SuccessBox message={roleMsg.text} /> : <ErrorBox message={roleMsg.text} />)}
        <Button tone="primary" disabled={!editRoleId || (editRoleRename && !editRoleName.trim())} onClick={saveRole}>保存</Button>
      </Drawer>
    </div>
  )
}
