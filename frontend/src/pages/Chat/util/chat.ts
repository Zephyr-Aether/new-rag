/** 归一化换行/转义：模型输出里的字面 \n 变成真实换行。 */
export function normalizeContent(text: string) {
  return (text || '')
    .replace(/\r\n/g, '\n')
    .replace(/\\n/g, '\n')
    .replace(/\\r/g, '\r')
    .replace(/\\t/g, '\t')
}
