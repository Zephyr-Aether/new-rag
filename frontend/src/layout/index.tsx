import { Suspense, useEffect, useMemo, useState } from 'react'
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
import { MessageSquare } from 'lucide-react'
import { api, getToken, HealthHA, ModelConfig } from '../services'
import { onUnauthorized } from '../request'
import { Badge, Button, PageSkeleton } from '../components'
import { useConfirm } from '../components/Confirm'
import { usePermissions } from '../hooks/usePermissions'
import Onboarding, { isOnboardingDone } from '../components/Onboarding'
import { Toaster } from 'sonner'
import { getLoginDraft } from '../util'
import RouteErrorBoundary from './RouteErrorBoundary'
import { ChangePasswordModal, LoginModal } from './AuthModals'
import { crumbsOf, filterNavItems, GROUP_CHAIN_OF_PATH, MENU_ITEMS, NavItem, selectedKeyOf } from './nav'

function formatModelLabel(cfg: ModelConfig | null): string {
  if (!cfg) return ''
  const parts = [cfg.provider, cfg.model].filter((part): part is string => Boolean(part && part.trim()))
  return parts.join(' · ')
}

export default function AppLayout() {
  const { confirm, confirmEl } = useConfirm()
  const { can, isAdmin } = usePermissions()
  const items = useMemo(() => filterNavItems(MENU_ITEMS, can, isAdmin), [can, isAdmin])
  const menuProps = useMemo(() => {
    const toProps = (list: NavItem[]): NonNullable<MenuProps['items']> =>
      list.map((i) => {
        const kids = i.children && i.children.length > 0 ? toProps(i.children) : undefined
        return kids ? { key: i.key, icon: i.icon, label: i.label, children: kids } : { key: i.key, icon: i.icon, label: i.label }
      })
    return toProps(items)
  }, [items])
  const [collapsed, setCollapsed] = useState(false)
  const [health, setHealth] = useState<HealthHA | null>(null)
  const [modelCfg, setModelCfg] = useState<ModelConfig | null>(null)
  const [kbCount, setKbCount] = useState(0)
  const location = useLocation()
  const navigate = useNavigate()
  const [authed, setAuthed] = useState(Boolean(getToken()))
  const [loginOpen, setLoginOpen] = useState(false)
  const [showOnboarding, setShowOnboarding] = useState(() => !isOnboardingDone())
  // 首次登录强制改密（must_change_password）
  const [mustChange, setMustChange] = useState(false)
  const [currentPassword, setCurrentPassword] = useState('')
  const modelLabel = formatModelLabel(modelCfg)
  const modelChipLabel = !modelCfg ? '模型·未就绪' : modelCfg.is_mock ? '模型·模拟' : '模型·已接入'
  const modelChipTitle = modelLabel ? `模型接入状态：${modelLabel}` : '模型接入状态暂不可用'
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null))
    // 顶栏全局平台状态：模型接入 + 知识就绪度
    api.modelConfig().then(setModelCfg).catch(() => setModelCfg(null))
    api.kbBases().then((r) => setKbCount(r.bases.length)).catch(() => setKbCount(0))
  }, [])

  // 401：清会话并弹登录框
  useEffect(() => {
    return onUnauthorized(() => {
      setAuthed(false)
      setMustChange(false)
      setCurrentPassword('')
      setLoginOpen(true)
    })
  }, [])

  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const chain = GROUP_CHAIN_OF_PATH[selectedKeyOf(location.pathname)] ?? []
    return chain.includes('workspace-group') ? chain : [...chain, 'workspace-group']
  })
  useEffect(() => {
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
                <span className="small muted">{getLoginDraft().user}@{getLoginDraft().tenant}</span>
                <Button
                onClick={() =>
                  confirm('退出登录', '确定要退出登录吗？', () => {
                    api.logout()
                    setAuthed(false)
                    setMustChange(false)
                    setCurrentPassword('')
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
              <Link to="/settings" className="health-chip" title={modelChipTitle}>
                <i className={`health-dot ${modelCfg ? (modelCfg.is_mock ? 'warn' : 'ok') : ''}`} />
                {modelChipLabel}
              </Link>
              <Link to="/knowledge" className="health-chip" title="知识库状态 — 点击进入知识工作区">
                <i className={`health-dot ${kbCount > 0 ? 'ok' : ''}`} />
                知识{kbCount > 0 ? `·${kbCount} 库` : '·未导入'}
              </Link>
              <span className="small muted" title={health?.instance_id ?? undefined}>{health?.instance_id ? health.instance_id.slice(0, 8) : '…'}</span>
              <Badge status={health?.ready ? 'READY' : 'DOWN'} />
            </div>
          </div>
        </Header>
        <Content style={{ padding: 'var(--sp-page, 12px)', overflowY: 'auto', overflowX: 'hidden' }}>
          <RouteErrorBoundary key={location.pathname}>
            <Suspense fallback={<div className="route-loading"><PageSkeleton rows={4} cols={4} /></div>}>
              <Outlet />
            </Suspense>
          </RouteErrorBoundary></Content>
            </AntLayout>

      <Toaster position="top-right" richColors />

      <Onboarding open={showOnboarding} onClose={() => setShowOnboarding(false)} />

      {loginOpen && (
        <LoginModal
          onClose={() => setLoginOpen(false)}
          onLoggedIn={(r, pwd) => {
            setAuthed(true)
            setLoginOpen(false)
            setCurrentPassword(pwd)
            setMustChange(Boolean(r.must_change_password))
          }}
        />
      )}
      {mustChange && (
        <ChangePasswordModal
          currentPassword={currentPassword}
          onChanged={() => setMustChange(false)}
        />
      )}
    </AntLayout>
  )
}
