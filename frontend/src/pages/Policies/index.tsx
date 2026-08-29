import { useEffect, useState } from 'react'
import { useRequest } from 'ahooks'
import { Pagination } from '@/components/pagination'
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/sheet'
import { api } from '@/services'
import { Button, Card, Empty, ErrorBox, Field, PermissionDenied, SuccessBox, TableSkeleton } from '@/components'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/select'
import { RadioGroup, RadioGroupItem } from '@/components/radio-group'
import { PageHeader } from '@/components/Page'
import { useConfirm } from '@/components/Confirm'
import { usePermissions } from '@/hooks/usePermissions'
import { toast } from '@/toast'

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

const PAGE_SIZE = 10
const POLICY_STEPS = ['范围', '对象', '权限', '效果', '摘要']

/** 权限动作 → 中文语义（我的权限明细用）。 */
const PERM_LABELS: Record<string, string> = {
  '*': '全部权限',
  'agent:use': '使用 Agent',
  'run:create': '发起任务',
  'tool:execute': '调用工具',
  'model:configure': '配置模型',
  'data:purge': '数据清理',
  'release:publish': '发布版本',
  'policy:manage': '管理权限策略',
  'config:write': '写配置',
  'flags:write': '管理功能开关',
  'cost:reconcile': '成本对账',
  'release:ops': '发布运维',
  'release:version:create': '创建版本',
  'queue:ops': '任务队列运维',
  'kb:ingest': '导入知识',
  'memory:write': '写入记忆',
  'eval:write': '录入评测',
  'graph:write': '关系图谱写入',
}
function permLabel(p: string) {
  return PERM_LABELS[p] ?? p
}

const effectLabel = (effect: string) => (effect === 'ALLOW' ? '允许' : effect === 'DENY' ? '拒绝' : effect)

const verdictLabel = (verdict: string) => (verdict === 'ALLOW' ? '允许执行' : verdict === 'DENY' ? '拒绝执行' : '无规则命中 · 默认拒绝')

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
  const [pstep, setPstep] = useState(0)
  // 角色编辑
  const [roleEditOpen, setRoleEditOpen] = useState(false)
  const [editRoleId, setEditRoleId] = useState('')
  const [editRoleName, setEditRoleName] = useState('')
  const [editRoleDesc, setEditRoleDesc] = useState('')
  const [editRoleRename, setEditRoleRename] = useState(false)
  const [roleMsg, setRoleMsg] = useState<{ kind: 'ok' | 'err'; text: string } | null>(null)
  // 页面 Tab + 策略筛选
  const [tab, setTab] = useState<'policy' | 'role' | 'check'>('policy')
  const [filter, setFilter] = useState('')
  const [effectFilter, setEffectFilter] = useState('')
  const [policyPage, setPolicyPage] = useState(1)
  // 权限预览
  const [ckSubject, setCkSubject] = useState('')
  const [ckAction, setCkAction] = useState('')
  const [ckResource, setCkResource] = useState('*')

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
    setScope('tenant')
    setPstep(0)
    setPolicyOpen(true)
  }

  function editPolicy(p: Policy) {
    setEditingId(p.id)
    setAction(p.action)
    setEffect(p.effect)
    setUserId(p.user_id ?? '')
    setRoleId(p.role_id ?? '')
    setScope(p.user_id ? 'user' : p.role_id ? 'role' : 'tenant')
    setResource(p.resource ?? '*')
    setResourceCustom(!(p.resource && resources.some((r) => r.resource === p.resource)))
    setPstep(0)
    setPolicyOpen(true)
  }

  async function savePolicy() {
    if (!action.trim()) return
    setBusy('create')
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
      toast(editingId ? '策略已更新' : '已新增策略')
      setPolicyOpen(false)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
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
      toast((e as Error).message, 'err')
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
      toast((e as Error).message, 'err')
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
      toast((e as Error).message, 'err')
    }
  }

  async function doAssign(roleId: string, user: string) {
    try {
      await api.roleAddUser(roleId, user.trim())
      setAssign(null)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    }
  }

  async function removeUser(roleId: string, user: string) {
    try {
      await api.roleRemoveUser(roleId, user)
      refresh()
    } catch (e) {
      toast((e as Error).message, 'err')
    }
  }

  const scopeLabel = (p: Policy) => {
    if (p.user_id) return <span className="mono">{p.user_id}（用户级）</span>
    if (p.role_id) return <span className="mono">{roles.find((r) => r.id === p.role_id)?.name ?? p.role_id}（角色级）</span>
    return <span className="muted">租户级</span>
  }

  const scopeTag = (p: Policy) => {
    if (p.user_id) return <span className="policy-scope user">用户</span>
    if (p.role_id) return <span className="policy-scope role">角色</span>
    return <span className="policy-scope tenant">租户</span>
  }

  const filteredPolicies = (rows ?? []).filter((p) => {
    const q = filter.trim().toLowerCase()
    if (q && !`${p.action} ${p.resource}`.toLowerCase().includes(q)) return false
    if (effectFilter && p.effect !== effectFilter) return false
    return true
  })

  /** 人话摘要：把配置翻译成一句可核对的自然语言。 */
  const policySummary = (() => {
    const who = userId.trim()
      ? `用户 ${userId.trim()}`
      : roleId
        ? `角色「${roles.find((r) => r.id === roleId)?.name ?? roleId}」`
        : '租户全部成员'
    return `${effect === 'ALLOW' ? '允许' : '拒绝'}${who}对资源 ${resource.trim() || '*'} 执行 ${action || '…'}`
  })()

  /** 冲突提示：同 action+resource 已有相反效果时提醒。 */
  const conflictHint = (() => {
    if (!action.trim()) return null
    const overlap = (rows ?? []).filter(
      (p) => p.action === action.trim() && (p.resource === (resource.trim() || '*') || resource.trim() === '*') && p.id !== editingId,
    )
    if (overlap.length === 0) return null
    const opp = overlap.some((p) => p.effect !== effect)
    return opp
      ? `已存在对 ${action.trim()} 的相反效果规则（${overlap.map((p) => effectLabel(p.effect)).join(' / ')}），本规则可能与它冲突，拒绝优先。`
      : `已存在 ${overlap.length} 条同类规则（${overlap.map((p) => effectLabel(p.effect)).join(' / ')}），本次为追加。`
  })()

  const checkResult = (() => {
    if (!ckAction.trim()) return null
    const matches = (rows ?? []).filter((p) => {
      const subjectOk = ckSubject.trim()
        ? p.user_id === ckSubject.trim() || roles.find((r) => r.id === p.role_id && r.users.includes(ckSubject.trim()))
        : true
      const actionOk = p.action === ckAction.trim()
      const resourceOk = p.resource === (ckResource.trim() || '*') || p.resource === '*'
      return subjectOk && actionOk && resourceOk
    })
    const deny = matches.find((p) => p.effect === 'DENY')
    const allow = matches.find((p) => p.effect === 'ALLOW')
    return { allow: !!allow && !deny, matches, verdict: deny ? 'DENY' : allow ? 'ALLOW' : 'DEFAULT_DENY' }
  })()

  const [scope, setScope] = useState<'tenant' | 'role' | 'user'>('tenant')
  function selectScope(s: 'tenant' | 'role' | 'user') {
    setScope(s)
    if (s === 'tenant') { setUserId(''); setRoleId('') }
    else if (s === 'role') { setUserId('') }
    else { setRoleId('') }
  }
  const canNextPolicy = pstep === 0
    ? true
    : pstep === 1
      ? scope === 'tenant' ? true : scope === 'role' ? !!roleId : !!userId.trim()
      : pstep === 2
        ? !!action.trim() && !!resource.trim()
        : true

  if (denied) {
    return (
      <div>
        <PageHeader title="权限策略" desc="租户、角色、用户级权限规则；默认拒绝，拒绝优先" />
        <PermissionDenied />
      </div>
    )
  }

  return (
    <div>
      {confirmEl}
      <PageHeader title="权限策略" desc="租户、角色、用户级权限规则；默认拒绝，拒绝优先" />
      {error && <div className="mb"><ErrorBox message={(error as Error).message} /></div>}

      {myPerms && (
        <div className="policy-mybar mb">
          <div className="policy-mybar-head">
            <span className="policy-mybar-label">当前身份</span>
            <span className="small">
              {myPerms.allowed.includes('*')
                ? '管理员 · 全部权限'
                : `可配置权限 · ${myPerms.allowed.length} 项允许${myPerms.denied.length ? ` / ${myPerms.denied.length} 项被拒` : ''}`}
            </span>
          </div>
          <details className="policy-mybar-detail">
            <summary>查看明细</summary>
            <div className="small muted" style={{ lineHeight: 1.7, marginTop: 6 }}>
              <div>允许：{myPerms.allowed.length ? myPerms.allowed.map(permLabel).join('、') : '无（默认拒绝）'}</div>
              {myPerms.denied.length > 0 && <div>被拒绝：{myPerms.denied.map(permLabel).join('、')}</div>}
            </div>
          </details>
        </div>
      )}

      <div className="policy-tabs mb">
        <button type="button" className={`policy-tab${tab === 'policy' ? ' on' : ''}`} onClick={() => setTab('policy')}>策略</button>
        <button type="button" className={`policy-tab${tab === 'role' ? ' on' : ''}`} onClick={() => setTab('role')}>角色</button>
        <button type="button" className={`policy-tab${tab === 'check' ? ' on' : ''}`} onClick={() => setTab('check')}>权限预览</button>
      </div>

      {tab === 'policy' && (
      <Card title={`策略列表（${filteredPolicies.length}）`}>
        <div className="row mb">
          <Button tone="primary" disabled={!can('policy:manage')} onClick={openNew}>
            新增策略
          </Button>
          <input
            value={filter} onChange={(e) => { setFilter(e.target.value); setPolicyPage(1) }}
            placeholder="按 action / 资源筛选" style={{ maxWidth: 200 }}
          />
          <select value={effectFilter} onChange={(e) => { setEffectFilter(e.target.value); setPolicyPage(1) }}>
            <option value="">全部效果</option>
            <option value="ALLOW">允许</option>
            <option value="DENY">拒绝</option>
          </select>
                  </div>
        {loading ? (
          <TableSkeleton rows={5} cols={4} />
        ) : filteredPolicies.length === 0 ? (
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
              {filteredPolicies.slice((policyPage - 1) * PAGE_SIZE, policyPage * PAGE_SIZE).map((p) => (
                <tr key={p.id}>
                  <td className="small">
                    {scopeTag(p)}
                    <span className="policy-scope-name">{scopeLabel(p)}</span>
                  </td>
                  <td className="mono small">{p.action}</td>
                  <td className="mono small muted">{p.resource}</td>
                  <td>
                    <span className={`policy-effect ${p.effect === 'ALLOW' ? 'allow' : 'deny'}`}>
                      {p.effect === 'ALLOW' ? '允许' : '拒绝'}
                    </span>
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
        {filteredPolicies.length > PAGE_SIZE && (
          <div className="row mt" style={{ justifyContent: 'flex-end' }}>
            <Pagination current={policyPage} pageSize={PAGE_SIZE} total={filteredPolicies.length} onChange={setPolicyPage} />
          </div>
        )}
      </Card>
      )}

      {tab === 'role' && (
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
      )}

      {tab === 'check' && (
      <Card title="权限预览">
        <div className="small muted mb">选一个用户/角色和一个动作，直接看「能不能做」，并展示命中的规则来源。</div>
        <div className="grid cols-3" style={{ gap: 12 }}>
          <Field label="用户 / 角色">
            <select value={ckSubject} onChange={(e) => setCkSubject(e.target.value)}>
              <option value="">（租户级）</option>
              <optgroup label="用户">
                {(rows ?? []).map((p) => p.user_id).filter((u): u is string => !!u).map((u) => (
                  <option key={`u-${u}`} value={u}>{u}</option>
                ))}
              </optgroup>
              <optgroup label="角色">
                {roles.map((r) => (
                  <option key={`r-${r.id}`} value={r.id}>{r.name}</option>
                ))}
              </optgroup>
            </select>
          </Field>
          <Field label="动作">
            <select value={ckAction} onChange={(e) => setCkAction(e.target.value)}>
              <option value="">选择动作</option>
              {actions.map((a) => (
                <option key={a.action} value={a.action}>{a.name}（{a.action}）</option>
              ))}
            </select>
          </Field>
          <Field label="资源">
            <input value={ckResource} onChange={(e) => setCkResource(e.target.value)} placeholder="* 或 document" />
          </Field>
        </div>
        {checkResult && (
          <div className={`policy-check-result ${checkResult.allow ? 'ok' : 'no'}`}>
            <div className="policy-check-verdict">
              结果：{verdictLabel(checkResult.verdict)}
            </div>
            {checkResult.matches.length > 0 ? (
              <div className="small muted mt">命中规则：{checkResult.matches.map((m) => `${effectLabel(m.effect)} ${m.action} ${m.resource}${m.role_id ? `（角色 ${roles.find((r) => r.id === m.role_id)?.name ?? m.role_id}）` : m.user_id ? `（用户 ${m.user_id}）` : '（租户）'}`).join('；')}</div>
            ) : (
              <div className="small muted mt">没有命中任何规则，按默认拒绝处理。</div>
            )}
          </div>
        )}
      </Card>
      )}

      <Sheet open={policyOpen} onOpenChange={(o) => !o && setPolicyOpen(false)}>
      <SheetContent side="right" className="w-[480px] max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{editingId ? '编辑策略' : '新增策略'}</SheetTitle>
        </SheetHeader>
        <div className="px-4">
        <div className="policy-steps mb">
          {POLICY_STEPS.map((s, i) => (
            <div key={s} className={`policy-step${i === pstep ? ' on' : ''}${i < pstep ? ' done' : ''}`}>
              <span className="policy-step-dot">{i < pstep ? '✓' : i + 1}</span>
              <span>{s}</span>
            </div>
          ))}
        </div>

        {pstep === 0 && (
          <div>
            <div className="small muted mb">这条规则作用在谁身上？</div>
            <RadioGroup value={scope} onValueChange={(v) => selectScope(v as 'tenant' | 'role' | 'user')}>
              <RadioGroupItem value="tenant">租户级 <span className="text-muted-foreground">整个租户的所有成员</span></RadioGroupItem>
              <RadioGroupItem value="role">角色级 <span className="text-muted-foreground">某个角色下的所有用户</span></RadioGroupItem>
              <RadioGroupItem value="user">用户级 <span className="text-muted-foreground">某个具体用户</span></RadioGroupItem>
            </RadioGroup>
          </div>
        )}
        {pstep === 1 && (
          <div>
            {scope === 'user' && (
              <Field label="用户">
                <input value={userId} onChange={(e) => setUserId(e.target.value)} placeholder="user-x" autoFocus />
              </Field>
            )}
            {scope === 'role' && (
              <Field label="角色">
                <Select value={roleId || undefined} onValueChange={setRoleId}>
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="选择角色" />
                  </SelectTrigger>
                  <SelectContent>
                    {roles.map((r) => (
                      <SelectItem key={r.id} value={r.id}>{r.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
            {scope === 'tenant' && <p className="small muted">已选租户级，作用范围为整个租户。</p>}
          </div>
        )}
        {pstep === 2 && (
          <div>
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
          </div>
        )}
        {pstep === 3 && (
          <div>
            <div className="small muted mb">允许还是拒绝？（DENY 优先，命中即拒绝）</div>
            <div className="policy-scope-grid">
              {([
                { v: 'ALLOW', title: '允许', desc: '放行该动作', cls: 'allow' },
                { v: 'DENY', title: '拒绝', desc: '拦截该动作（优先）', cls: 'deny' },
              ] as const).map((o) => (
                <button key={o.v} type="button" className={`policy-scope-opt ${o.cls}${effect === o.v ? ' on' : ''}`} onClick={() => setEffect(o.v)}>
                  <b>{o.title}</b>
                  <span>{o.desc}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {pstep === 4 && (
          <div>
            {conflictHint && <div className="policy-conflict small">{conflictHint}</div>}
            <div className="policy-summary">人话摘要：{policySummary}</div>
            <div className="small muted">确认无误后提交，这条规则会立即生效。</div>
          </div>
        )}

        <div className="row mt" style={{ justifyContent: 'space-between' }}>
          <Button disabled={pstep === 0} onClick={() => setPstep(pstep - 1)}>上一步</Button>
          {pstep < 4 ? (
            <Button tone="primary" disabled={!canNextPolicy} onClick={() => setPstep(pstep + 1)}>下一步</Button>
          ) : (
            <Button tone="primary" disabled={busy === 'create' || !action.trim()} onClick={savePolicy}>
              {busy === 'create' ? '保存中…' : '提交策略'}
            </Button>
          )}
        </div>
              </div>
      </SheetContent>
    </Sheet>

      <Sheet open={roleEditOpen} onOpenChange={(o) => !o && setRoleEditOpen(false)}>
      <SheetContent side="right" className="w-[480px] max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle>编辑角色</SheetTitle>
        </SheetHeader>
        <div className="px-4">
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
              </div>
      </SheetContent>
    </Sheet>
    </div>
  )
}
