/** Knowledge 页共享常量。 */

export const RETRIEVAL_PARAM_DESC: [string, string][] = [
  ['top_k', '候选数：从全库召回多少片段参与排序，越大越全'],
  ['bm25_top_k', '关键词召回数：越大召回越多但更慢'],
  ['rerank_n', '精排后取前 N 条进上下文：越小越精'],
]
