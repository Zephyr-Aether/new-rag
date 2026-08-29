import { clearToken, get, post, put, del, setToken, sha256Hex } from './http'

import type { AuthToken, HealthHA, Meta, UserRow } from '../api/types'
export const authApi = {
// 认证（§27 JWT）：密码先 SHA-256 再提交，避免明文传输
  login: async (tenantId: string, userId: string, password = '') => {
    const pwd = password ? await sha256Hex(password) : ''
    const r = await post<AuthToken>('/auth/token', { tenant_id: tenantId, user_id: userId, password: pwd })
    setToken(r.access_token)
    return r
  },
  logout: () => clearToken(),
  authMe: () => get<{ user_id: string; tenant_id: string; roles: string[]; allowed: string[]; denied: string[] }>('/auth/me'),
  changePassword: async (oldRaw: string, newRaw: string) => {
    const r = await post<{ ok: boolean }>('/auth/password', {
      old_password: oldRaw ? await sha256Hex(oldRaw) : '',
      new_password: await sha256Hex(newRaw),
    })
    return r
  },
  users: () => get<{ users: UserRow[] }>('/users'),
  userCreate: async (body: { user_id: string; email?: string; display_name?: string; password?: string; role_ids?: string[] }) =>
    post<{ ok: boolean; id: string }>('/users', {
      ...body,
      password: body.password ? await sha256Hex(body.password) : '',
    }),
  userUpdate: async (id: string, body: { display_name?: string; email?: string; enabled?: boolean; password?: string; role_ids?: string[] }) =>
    put<{ ok: boolean; id: string }>(`/users/${encodeURIComponent(id)}`, {
      ...body,
      password: body.password ? await sha256Hex(body.password) : '',
    }),
  userDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/users/${encodeURIComponent(id)}`),
  tenants: () => get<{ tenants: { id: string; name: string }[] }>('/tenants'),
  tenantCreate: async (body: { tenant_id?: string; name: string; admin_user_id: string; admin_email?: string; admin_password?: string }) =>
    post<{ ok: boolean; tenant_id: string; admin_user_id: string }>('/tenants', {
      ...body,
      admin_password: body.admin_password ? await sha256Hex(body.admin_password) : '',
    }),
  secrets: () => get<{ secrets: { ref: string }[] }>('/secrets'),
  secretSet: (ref: string, value: string) => post<{ ok: boolean; ref: string }>('/secrets', { ref, value }),
  secretDelete: (ref: string) => del<{ ok: boolean; deleted: string }>(`/secrets/${encodeURIComponent(ref)}`),
  roles: () =>
    get<{ roles: { id: string; name: string; description: string; users: string[] }[] }>('/roles'),
  roleCreate: (body: { name: string; description?: string }) => post<{ id: string; name: string }>('/roles', body),
  roleUpdate: (id: string, body: { name?: string; description?: string }) =>
    put<{ ok: boolean; id: string }>(`/roles/${encodeURIComponent(id)}`, body),
  roleDelete: (id: string) => del<{ ok: boolean; deleted: string }>(`/roles/${encodeURIComponent(id)}`),
  roleAddUser: (roleId: string, userId: string) =>
    post<{ ok: boolean; role_id: string; user_id: string }>(`/roles/${encodeURIComponent(roleId)}/users`, { user_id: userId }),
  roleRemoveUser: (roleId: string, userId: string) =>
    del<{ ok: boolean }>(`/roles/${encodeURIComponent(roleId)}/users/${encodeURIComponent(userId)}`),
  // 健康 / 元数据
  health: () => get<HealthHA>('/health/ha'),
  meta: () => get<Meta>('/meta'),
}
