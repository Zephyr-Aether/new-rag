// HTTP 层：axios 实例 + 拦截器（token 注入 / 401 统一 / 错误规范化）
import axios, { AxiosError } from 'axios'
import { toast } from './toast'

const TOKEN_KEY = 'agent_platform_token'
export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}
export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY)
}

// 401 统一处理：清 token + 通知监听方（如 Layout 弹登录框）。axios 拦截器与原生 fetch 流式都走这里
const unauthorizedHandlers = new Set<() => void>()
export function onUnauthorized(handler: () => void): () => void {
  unauthorizedHandlers.add(handler)
  return () => {
    unauthorizedHandlers.delete(handler)
  }
}

export function handleUnauthorized(): void {
  clearToken()
  unauthorizedHandlers.forEach((h) => h())
  toast('登录已失效，请重新登录', 'err')
}

export const http = axios.create({ timeout: 30000 })

// 请求拦截：注入 Bearer token
http.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截：把后端错误规范化为带 status 的 Error
http.interceptors.response.use(
  (res) => res,
  (error: AxiosError) => {
    const status = error.response?.status
    const data = error.response?.data as
      | { message?: string; detail?: string | { msg?: string }[] }
      | undefined
    let msg = error.message
    if (data?.message) msg = data.message
    else if (typeof data?.detail === 'string') msg = data.detail
    else if (Array.isArray(data?.detail)) msg = data.detail.map((d) => d.msg).filter(Boolean).join('; ')
    const err = new Error(`${status ? `${status}: ` : ''}${msg}`) as Error & { status?: number }
    err.status = status
    if (status === 401) handleUnauthorized()
    return Promise.reject(err)
  },
)
