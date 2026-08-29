// HTTP 请求层：axios 实例 + 通用请求方法（services 各模块共用）
import { getToken, handleUnauthorized, http, setToken, clearToken } from '../request'
export { http }

export { getToken, setToken, clearToken, handleUnauthorized }

export const request = <T>(path: string, method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE' = 'GET', data?: unknown) =>
  http.request<T>({ url: path, method, data }).then((r) => r.data)

export const get = <T>(path: string) => request<T>(path)
export const post = <T>(path: string, body?: unknown) => request<T>(path, 'POST', body)
export const put = <T>(path: string, body?: unknown) => request<T>(path, 'PUT', body)
export const patch = <T>(path: string, body?: unknown) => request<T>(path, 'PATCH', body)
export const del = <T>(path: string) => request<T>(path, 'DELETE')

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024

export async function sha256Hex(str: string): Promise<string> {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str))
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, '0')).join('')
}
