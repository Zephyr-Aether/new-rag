import { Component, Suspense, useEffect, useMemo, useState } from 'react'
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Breadcrumb, Layout as AntLayout, Menu } from 'antd'
import type { MenuProps } from 'antd'
import type { ReactNode } from 'react'

// antd v6 顶层 Layout 的 TS 类型缺静态成员，运行时存在，断言后解构
const { Sider, Header, Content } = AntLayout as unknown as {
  Sider: (p: Record<string, unknown> & { children?: ReactNode }) => ReactNode
  Header: (p: Record<string, unknown> & { children?: ReactNode }) => ReactNode
  Content: (p: Record<string, unknown> & { children?: ReactNode }) => ReactNode
}
import { ChevronLeft, Home, LayoutGrid, MessageSquare, ShieldCheck } from 'lucide-react'
import { api, getToken, HealthHA, ModelConfig } from '../api'
import { onUnauthorized } from '../request'
import { Badge, Button, ErrorBox, Field, PageSkeleton, Modal, PasswordInput } from '../components/ui'
import { PageError } from '../components/Page'
import { useConfirm } from '../components/Confirm'
import { usePermissions } from '../hooks/usePermissions'
import Onboarding, { isOnboardingDone } from '../components/Onboarding'
import { subscribeToast, ToastItem } from '../toast'
import { DEMO_LOGIN } from '../constants/product'
import { fillDemoLogin, getLoginDraft, persistLoginIdentity } from '../util/loginDraft'
import { History, Sparkles } from 'lucide-react'

const CHUNK_RELOAD_FLAG = '__agent_platform_chunk_reload__'

function isChunkLoadError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return /Failed to fetch dynamically imported module|Loading chunk [\d]+ failed|Importing a module script failed/i.test(message)
}

class RouteErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error) {
    if (!isChunkLoadError(error)) return
    if (sessionStorage.getItem(CHUNK_RELOAD_FLAG)) return
    sessionStorage.setItem(CHUNK_RELOAD_FLAG, '1')
    window.location.reload()
  }

  render() {
    if (this.state.error) {
      const message = isChunkLoadError(this.state.error)
        ? '页面资源加载失败，可能是版本更新或网络波动。'
        : this.state.error.message || '页面渲染失败，请重试。'

      return (
        <PageError
          message={message}
          retry={() => window.location.reload()}
        />
      )
    }

    return this.props.children
  }
}

type NavItem = {
  key: string
  icon?: ReactNode
  label: string
  perm?: string         // 需具备的权限动作（usePermissions.can）才显示
  showWhen?: string[]   // 分组级：任一权限具备即可显示整组
  children?: NavItem[]
}

// 侧栏按功能分组：首页 + 工作区（主流程）+ 管理（仅管理员可见，默认折叠，不抢第一眼）
const MENU_ITEMS: NavItem[] = [
  { key: '/', icon: <Home />, label: '首页' },
  {
    key: 'workspace-group',
    icon: <LayoutGrid />,
    label: '工作区',
    children: [
      { key: '/knowledge', label: '知识库' },
      { key: '/chat', label: '对话' },
      { key: '/evaluation', label: '评测' },
      { key: '/release', label: '发布' },
      { key: '/runs', label: '任务记录' },
    ],
  },
  {
    key: 'admin-group',
    icon: <ShieldCheck />,
    label: '管理',
    showWhen: ['queue:ops', 'data:purge', 'policy:manage', 'config:write'],
    children: [
      { key: '/users', label: '用户管理', perm: 'policy:manage' },
      { key: '/policies', label: '权限策略', perm: 'policy:manage' },
      { key: '/audit', label: '操作记录' },
      { key: '/queue', label: '任务队列', perm: 'queue:ops' },
      { key: '/events', label: '事件' },
      { key: '/data', label: '数据生命周期', perm: 'data:purge' },
      { key: '/settings', label: '配置中心', perm: 'config:write' },
      { key: '/model', label: '模型健康' },
      { key: '/cost', label: '成本' },
      { key: '/tools', label: '工具' },
      { key: '/approvals', label: '审批' },
      { key: '/memory', label: '历史记忆' },
      { key: '/graph', label: '关系图谱' },
    ],
  },
]
// 侧栏全量导航：面包屑/展开链/选中态共用
const ALL_NAV = MENU_ITEMS

/** 路径 → 需要展开的祖先分组 key 链（含嵌套的「知识」子菜单）。 */
const GROUP_CHAIN_OF_PATH: Record<string, string[]> = {}
function buildGroupChains(items: NavItem[], ancestors: string[]): void {
  for (const item of items) {
    if (!item.children) continue
    const self = [...ancestors, String(item.key)]
    for (const child of item.children) {
      if (child.children) buildGroupChains([child], self)
      else GROUP_CHAIN_OF_PATH[String(child.key)] = self
    }
  }
}
buildGroupChains(ALL_NAV, [])

/** 按权限裁剪导航：无权限条目不显示；子项全被裁掉的分组整体隐藏。 */
function filterNavItems(items: NavItem[], can: (a: string) => boolean): NavItem[] {
  const out: NavItem[] = []
  for (const item of items) {
    if (item.showWhen && !item.showWhen.some(can)) continue
    if (item.perm && !can(item.perm)) continue
    if (item.children) {
      const kids = filterNavItems(item.children, can)
      if (kids.length === 0) continue
      out.push({ ...item, children: kids })
    } else {
      out.push(item)
    }
  }
  return out
}

function crumbsOf(path: string, onBack?: () => void): { title: ReactNode }[] {
  const backCrumb = onBack
    ? [{
        title: (
          <button type="button" className="breadcrumb-back" onClick={onBack}>
            <ChevronLeft size={14} />
            <span>返回</span>
          </button>
        ),
      }]
    : []

  if (path.startsWith('/runs/')) {
    return [
      ...backCrumb,
      { title: <Link to="/runs">运行·任务</Link> },
      { title: '任务详情' },
    ]
  }
  function walk(items: NavItem[], trail: NavItem[]): NavItem[] | null {
    for (const item of items) {
      if (item.children) {
        const hit = walk(item.children, [...trail, item])
        if (hit) return hit
      } else if (item.key === path || path.startsWith(`${item.key}/`)) {
        return [...trail, item]
      }
    }
    return null
  }
  const chain = walk(ALL_NAV, [])
  if (!chain || chain.length === 0) return [...backCrumb, { title: '首页' }]
  return chain.map((n, i) => {
    const last = i === chain.length - 1
    return {
      title: !last && n.key.startsWith('/') ? <Link to={n.key}>{n.label}</Link> : String(n.label),
    }
  })
}

function allKeys(items: NavItem[]): string[] {
  return items.flatMap((i) => (i.key ? [String(i.key), ...(i.children ? allKeys(i.children) : [])] : []))
}

/** 把当前 pathname 映射到菜单项 key：详情页（/runs/123 -> /runs）前缀匹配，保证子项/父级都被选中。 */
function selectedKeyOf(pathname: string): string {
  const keys = allKeys(ALL_NAV)
  if (keys.includes(pathname)) return pathname
  const matched = keys
    .filter((k) => k.startsWith('/') && pathname.startsWith(`${k}/`))
    .sort((a, b) => b.length - a.length)
  return matched[0] ?? pathname
}

export default function AppLayout() {
  const { confirm, confirmEl } = useConfirm()
  const { can } = usePermissions()
  const items = useMemo(() => filterNavItems(MENU_ITEMS, can), [can])
  const menuProps = useMemo(() => {
    // 递归映射：支持「知识」这类嵌套子菜单（二级分组的 children 也要保留）
    const toProps = (list: NavItem[]): NonNullable<MenuProps['items']> =>
      list.map((i) => {
        const kids = i.children && i.children.length > 0 ? toProps(i.children) : undefined
        return kids ? { key: i.key, icon: i.icon, label: i.label, children: kids } : { key: i.key, icon: i.icon, label: i.label }
      })
    return toProps(items)
  }, [items])
  const [health, setHealth] = useState<HealthHA | null>(null)
  const [modelCfg, setModelCfg] = useState<ModelConfig | null>(null)
  const [kbCount, setKbCount] = useState(0)
  const location = useLocation()
  const navigate = useNavigate()
  const [collapsed, setCollapsed] = useState(false)
  const [authed, setAuthed] = useState(Boolean(getToken()))
  const [tenant, setTenant] = useState(() => getLoginDraft().tenant)
  const [user, setUser] = useState(() => getLoginDraft().user)
  const [password, setPassword] = useState('')
  const [authErr, setAuthErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [showOnboarding, setShowOnboarding] = useState(() => !isOnboardingDone())
  // 首次登录强制改密（must_change_password）
  const [mustChange, setMustChange] = useState(false)
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [pwdErr, setPwdErr] = useState('')
  const [pwdBusy, setPwdBusy] = useState(false)
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    // 顶栏全局平台状态：模型接入 + 知识就绪度
    api.modelConfig().then(setModelCfg).catch(() => setModelCfg(null))
    api.kbBases().then((r) => setKbCount(r.bases.length)).catch(() => setKbCount(0))
    const unsub = subscribeToast(setToasts)
    return unsub
  }, [])

  // 401：清会话并弹登录框
  useEffect(() => {
    return onUnauthorized(() => {
      setAuthed(false)
      setLoginOpen(true)
    })
  }, [])

  async function doLogin() {
    setBusy(true)
    setAuthErr('')
    try {
      const r = await api.login(tenant.trim(), user.trim(), password)
      persistLoginIdentity(tenant, user)
      setAuthed(true)
      setLoginOpen(false)
      if (r.must_change_password) setMustChange(true)
    } catch (e) {
      setAuthErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function doChangePassword() {
    if (newPwd.length < 6) { setPwdErr('新密码至少 6 位'); return }
    if (newPwd !== confirmPwd) { setPwdErr('两次输入不一致'); return }
    setPwdBusy(true)
    setPwdErr('')
    try {
      await api.changePassword(password, newPwd)
      setMustChange(false)
      setNewPwd('')
      setConfirmPwd('')
    } catch (e) {
      setPwdErr((e as Error).message)
    } finally {
      setPwdBusy(false)
    }
  }

  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const chain = GROUP_CHAIN_OF_PATH[selectedKeyOf(location.pathname)] ?? []
    // 工作区默认展开，管理保持折叠（不抢第一眼）
    return chain.includes('workspace-group') ? chain : [...chain, 'workspace-group']
  })
  useEffect(() => {
    // 导航到子菜单时自动展开祖先分组；工作区常开
    const chain = GROUP_CHAIN_OF_PATH[selectedKeyOf(location.pathname)] ?? []
    setOpenKeys((prev) => Array.from(new Set([...prev, ...chain, 'workspace-group'])))
  }, [location.pathname])

  return (
    <AntLayout style={{ minHeight: '100vh', height: '100vh', overflow: 'hidden' }}>
      {confirmEl}
      <Sider collapsible collapsed={collapsed} onCollapse={setCollapsed} breakpoint="lg" width={220}>
        <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
          <div className="ant-brand">
            <MessageSquare size={18} />
            <span className={collapsed ? 'hide' : ''}>Agent 发布与治理平台</span>
          </div>
          <div style={{ flex: 1, overflowY: 'auto', overflowX: 'hidden', minHeight: 0 }}>
            <Menu
              theme="dark"
              mode="inline"
              items={menuProps}
              selectedKeys={[selectedKeyOf(location.pathname)]}
              openKeys={openKeys}
              onOpenChange={setOpenKeys}
              onClick={({ key }) => {
                if (key.startsWith('/')) navigate(key)
              }}
            />
          </div>
        </div>
      </Sider>
      <AntLayout>
        <Header
          className="topbar"
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <div className="topbar-left">
            {location.pathname !== '/' && (
              <Breadcrumb
                items={crumbsOf(location.pathname, () => {
                  if (window.history.length > 1) navigate(-1)
                  else navigate('/')
                })}
              />
            )}
          </div>
          <div className="topbar-right">
            {authed ? (
              <>
                <span className="small muted">{user}@{tenant}</span>
                <Button
                  onClick={() =>
                    confirm('退出登录', '确定要退出登录吗？', () => {
                      api.logout()
                      setAuthed(false)
                      navigate('/login', { replace: true })
                    }, { danger: true, confirmText: '退出' })
                  }
                >
                  登出
                </Button>
              </>
            ) : (
              <>
                <Button tone="primary" onClick={() => navigate('/login')}>登录</Button>
              </>
            )}
            <div className="health">
              <Link to="/settings" className="health-chip" title="模型接入状态 — 点击去配置">
                <i className={`health-dot ${modelCfg ? (modelCfg.is_mock ? 'warn' : 'ok') : ''}`} />
                模型{modelCfg ? (modelCfg.is_mock ? '·模拟' : '·已接入') : ''}
              </Link>
              <Link to="/knowledge" className="health-chip" title="知识库状态 — 点击进入知识工作区">
                <i className={`health-dot ${kbCount > 0 ? 'ok' : ''}`} />
                知识{ kbCount > 0 ? `·${kbCount} 库` : '·未导入' }
              </Link>
              <span className="small muted" title={health?.instance_id ?? undefined}>{health?.instance_id ? health.instance_id.slice(0, 8) : '…'}</span>
              <Badge status={health?.ready ? 'READY' : 'DOWN'} />
            </div>
          </div>
        </Header>
        <Content style={{ padding: 24, overflow: 'auto' }}>
          <RouteErrorBoundary key={location.pathname}>
            <Suspense fallback={<div className="route-loading"><PageSkeleton rows={4} cols={4} /></div>}>
              <Outlet />
            </Suspense>
          </RouteErrorBoundary>
        </Content>
      </AntLayout>

      <div className="toast-wrap">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>

      <Onboarding open={showOnboarding} onClose={() => setShowOnboarding(false)} />

      {loginOpen && (
        <Modal title="登录" onClose={() => setLoginOpen(false)}>
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
      )}

      {mustChange && (
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
      )}
    </AntLayout>
  )
}
