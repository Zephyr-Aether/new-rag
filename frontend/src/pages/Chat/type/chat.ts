/** Chat 页共享类型。 */

export interface ToolCallView {
  tool_ref: string
  ok?: boolean
}

export interface ChatMsg {
  id: number
  mid?: string
  role: 'user' | 'assistant'
  content: string
  tools?: ToolCallView[]
  docs?: string[]
  state?: string
  runId?: string
  running?: boolean
  /** 流式被用户中断（停止）或连接中断，内容不完整。 */
  interrupted?: boolean
  /** 幂等键：该用户消息对应的 run 请求（重试复用，重新生成换新）。 */
  clientRunId?: string
  /** 网络/接口失败可「重试」（复用同一 client_run_id，服务端去重）。 */
  retriable?: boolean
  /** 失败原因（独立字段，渲染失败摘要卡片用，不污染正文 content）。 */
  error?: string
  /** 用户反馈：good / bad（已提交后禁用）。 */
  feedback?: string
}

export interface SessionItem {
  id: string
  title: string
  status: string
  message_count: number
  last_content: string
  created_at?: string
}
