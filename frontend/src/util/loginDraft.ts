import { DEMO_LOGIN } from '@/constants/product'

const LAST_LOGIN_TENANT_KEY = 'agent_platform_last_login_tenant'
const LAST_LOGIN_USER_KEY = 'agent_platform_last_login_user'

function readItem(key: string): string {
  try {
    return localStorage.getItem(key) || ''
  } catch {
    return ''
  }
}

function writeItem(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    // ignore storage failures in private mode / quota edge cases
  }
}

export function getLoginDraft(): { tenant: string; user: string; password: string } {
  return {
    tenant: readItem(LAST_LOGIN_TENANT_KEY) || DEMO_LOGIN.tenant,
    user: readItem(LAST_LOGIN_USER_KEY) || DEMO_LOGIN.user,
    password: '',
  }
}

export function fillDemoLogin(): { tenant: string; user: string; password: string } {
  return { ...DEMO_LOGIN }
}

export function persistLoginIdentity(tenant: string, user: string): void {
  writeItem(LAST_LOGIN_TENANT_KEY, tenant.trim())
  writeItem(LAST_LOGIN_USER_KEY, user.trim())
}
