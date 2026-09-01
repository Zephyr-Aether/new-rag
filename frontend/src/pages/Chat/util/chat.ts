/** 归一化换行/转义：模型输出里的字面 \n 变成真实换行。 */
export function normalizeContent(text: string) {
  return (text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
}

/** 流式渲染时若 ``` 未闭合，补一个闭合 fence，避免未闭合代码块把后续内容吞进代码框造成跳动。 */
export function closeUnclosedFence(text: string) {
  const fences = (text.match(/```/g) || []).length
  return fences % 2 === 1 ? `${text}\n\`\`\`` : text
}

/**
 * 历史预算：控制发给后端的上下文体积。服务端已有 token 级摘要压缩（§5.6），
 * 这里只做粗粒度裁剪（消息数 + 字符数双上限），避免请求体无限膨胀。
 * 返回从完整一轮开始的列表：开头若被截断成裸 assistant（其 user 被裁掉），去掉以免上下文残缺。
 */
export function budgetHistory(
  messages: { role: string; content: string }[],
  { maxMessages = 40, maxChars = 20000 }: { maxMessages?: number; maxChars?: number } = {},
) {
  const recent = messages.slice(-maxMessages)
  const kept: typeof recent = []
  let total = 0
  for (let i = recent.length - 1; i >= 0; i--) {
    total += recent[i].content.length
    if (total > maxChars && kept.length > 0) break
    kept.unshift(recent[i])
  }
  while (kept.length && kept[0].role !== 'user') kept.shift()
  return kept
}
