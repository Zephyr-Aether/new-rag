import { useEffect, useState } from 'react'
import { api, getToken } from '../services'

/** 前端权限感知：拉取当前用户生效权限与角色，can(action) 判断是否可操作（按 action 显隐/禁用按钮）。 */
const ADMIN_KEYWORDS = ['admin', '管理员']
export function usePermissions() {
  const [perms, setPerms] = useState<{ allowed: string[]; denied: string[] }>({ allowed: [], denied: [] })
  const [roles, setRoles] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api
      .authMe()
      .then((r) => {
        if (!cancelled) {
          setPerms({ allowed: r.allowed ?? [], denied: r.denied ?? [] })
          setRoles(r.roles ?? [])
          setLoading(false)
        }
      })
      .catch(() => {
        /* 未登录等场景忽略，按钮默认可用 */
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // token 变化（登录/登出）时重新拉取
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [getToken()])

  const can = (action: string): boolean => {
    if (perms.denied.includes(action)) return false
    return perms.allowed.includes(action) || perms.allowed.includes('*')
  }

  /** 是否是管理员：拥有「管理员」角色（普通用户即便继承租户级权限也不视作管理员）。 */
  const isAdmin = roles.some((n) => ADMIN_KEYWORDS.some((k) => (n || '').toLowerCase().includes(k.toLowerCase())))

  return { can, perms, roles, loading, isAdmin }
}
