/** Knowledge 页共享类型。 */

export interface DocRow {
  document_id: string
  title: string
  source_uri: string
  status: string
  created_at?: string
  chunk_count?: number
}

export interface DocDetail {
  document_id: string
  title: string
  source_uri: string
  status: string
  created_at?: string
  chunks: { chunk_id: string; seq: number; section: string; text: string; token_count: number }[]
}
