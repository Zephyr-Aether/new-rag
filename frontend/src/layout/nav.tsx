import { Link } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ChevronLeft, Home, LayoutGrid, ShieldCheck } from 'lucide-react'

export type NavItem = {
  key: string
  icon?: ReactNode
  label: string
  perm?: string         // 需具备的权限动作（usePermissions.can）才显示
  showWhen?: string[]   // 分组级：任一权限具备即可显示整组
  adminOnly?: boolean   // 分组级：仅管理员（拥有管理员角色）可见
  children?: NavItem[]
}

// 侧栏按功能分组：首页 + 工作区（主流程）+ 管理（仅管理员可见，默认折叠，不抢第一眼）
export const MENU_ITEMS: NavItem[] = [
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
    adminOnly: true,
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

/** 路径 → 需要展开的祖先分组 key 链（含嵌套子菜单）。 */
export const GROUP_CHAIN_OF_PATH: Record<string, string[]> = {}
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

/** 按权限裁剪导航：无权限条目不显示；adminOnly 分组仅管理员可见；子项全被裁掉的分组整体隐藏。 */
export function filterNavItems(items: NavItem[], can: (a: string) => boolean, isAdmin: boolean): NavItem[] {
  const out: NavItem[] = []
  for (const item of items) {
    if (item.adminOnly && !isAdmin) continue
    if (item.showWhen && !item.showWhen.some(can)) continue
    if (item.perm && !can(item.perm)) continue
    if (item.children) {
      const kids = filterNavItems(item.children, can, isAdmin)
      if (kids.length === 0) continue
      out.push({ ...item, children: kids })
    } else {
      out.push(item)
    }
  }
  return out
}

function allKeys(items: NavItem[]): string[] {
  return items.flatMap((i) => (i.key ? [String(i.key), ...(i.children ? allKeys(i.children) : [])] : []))
}

/** 把当前 pathname 映射到菜单项 key：详情页（/runs/123 -> /runs）前缀匹配。 */
export function selectedKeyOf(pathname: string): string {
  const keys = allKeys(ALL_NAV)
  if (keys.includes(pathname)) return pathname
  const matched = keys
    .filter((k) => k.startsWith('/') && pathname.startsWith(`${k}/`))
    .sort((a, b) => b.length - a.length)
  return matched[0] ?? pathname
}

export function crumbsOf(path: string, onBack?: () => void): { title: ReactNode }[] {
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
