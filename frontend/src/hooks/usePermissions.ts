import { useEffect, useState } from 'react'
import { api, getToken } from '../api'

/** 前端权限感知：拉取当前用户生效权限，can(action) 判断是否可操作（按 action 显隐/禁用按钮）。 */
export function usePermissions() {
  const [perms, setPerms] = useState<{ allowed: string[]; denied: string[] }>({ allowed: [], denied: [] })

  useEffect(() => {
    let cancelled = false
    api
      .authMe()
      .then((r) => {
        if (!cancelled) setPerms({ allowed: r.allowed ?? [], denied: r.denied ?? [] })
      })
      .catch(() => {
        /* 未登录等场景忽略，按钮默认可用 */
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

  return { can, perms }
}
