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
}

export interface SessionItem {
  id: string
  title: string
  status: string
  message_count: number
  last_content: string
}
