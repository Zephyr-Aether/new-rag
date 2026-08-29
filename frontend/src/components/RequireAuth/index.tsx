import { Navigate } from 'react-router-dom'
import { getToken } from '../../services'

/** 路由守卫：未登录跳转 /login（受保护区域统一包裹）。 */
export default function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!getToken()) return <Navigate to="/login" replace />
  return <>{children}</>
}
