import { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { usePermissions } from '../../hooks/usePermissions'
import { PageSkeleton } from '../'

/** 管理区域判定动作：与顶栏「管理」下拉的显隐条件一致（有其一即视为管理员）。 */
const ADMIN_ACTIONS = ['queue:ops', 'data:purge', 'policy:manage', 'config:write']

/** 路由级管理门禁：无管理员权限直接渲染 403 提示，普通用户不能进入管理路由。 */
export default function AdminGate({ children }: { children: ReactNode }) {
  const { perms, loading } = usePermissions()
  const allowed = ADMIN_ACTIONS.some((a) => perms.allowed.includes(a) || perms.allowed.includes('*'))

  if (loading) {
    return (
      <div className="route-loading">
        <PageSkeleton rows={3} cols={4} />
      </div>
    )
  }

  if (!allowed) {
    return (
      <div className="error-state">
        <div className="error-state-title">需要管理员权限</div>
        <div className="error-state-desc">这里是管理员功能区域，当前账号没有访问权限。如有需要，请联系管理员为你的角色授权。</div>
        <Link className="btn primary" to="/">回首页</Link>
      </div>
    )
  }

  return <>{children}</>
}
