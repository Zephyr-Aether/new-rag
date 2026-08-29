// services：http 请求层，按模块拆分后在此聚合为 api（消费方统一 import { api } from '@/services'）
import { authApi } from './auth'
import { runsApi } from './runs'
import { releaseApi } from './release'
import { knowledgeApi } from './knowledge'
import { toolsApi } from './tools'
import { eventsApi } from './events'
import { evalApi } from './eval'
import { miscApi } from './misc'

export * from '../api/types'
export { getToken, setToken, clearToken, MAX_UPLOAD_BYTES } from './http'

export const api = {
  ...authApi,
  ...runsApi,
  ...releaseApi,
  ...knowledgeApi,
  ...toolsApi,
  ...eventsApi,
  ...evalApi,
  ...miscApi,
}
