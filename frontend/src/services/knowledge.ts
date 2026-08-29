import { get, post, put, del, http } from './http'

import type { KBSearch, KbBase } from '../api/types'
export const knowledgeApi = {
// Knowledge
  kbBases: () => get<{ bases: KbBase[] }>('/knowledge/bases'),  kbCreate: (name: string, description = '') => post<{ kb_id: string; name: string }>('/knowledge/bases', { name, description }),
  kbRename: (id: string, name: string) => put<{ kb_id: string; name: string }>(`/knowledge/bases/${encodeURIComponent(id)}`, { name }),
  kbConfig: (id: string, config: { top_k?: number; bm25_top_k?: number; rerank_n?: number }) =>
    put<{ kb_id: string; retrieval_config: { top_k?: number; bm25_top_k?: number; rerank_n?: number } }>(
      `/knowledge/bases/${encodeURIComponent(id)}/config`,
      config,
    ),
  kbDelete: (id: string) => del<{ kb_id: string; deleted: boolean }>(`/knowledge/bases/${encodeURIComponent(id)}`),
  ingest: (body: { document_id: string; title: string; text: string; kb_id?: string }) =>
    post<{ document_id: string; chunks: number; status: string }>('/knowledge/documents', body),
  previewClean: (text: string) => post<{ cleaned: string; chunks: number; characters: number }>('/knowledge/preview', { text }),
  uploadInit: (body: { filename: string; size: number; chunk_size?: number; title?: string; kb_id?: string }) =>
    post<{ upload_id: string; chunk_size: number; total_chunks: number }>('/knowledge/upload/init', body),
  uploadChunk: (uploadId: string, index: number, blob: Blob) => {
    const fd = new FormData()
    fd.append('file', blob)
    return http.request<{ upload_id: string; received: number }>({ url: `/knowledge/upload/${uploadId}/chunks/${index}`, method: 'POST', data: fd }).then((r) => r.data)
  },
  uploadStatus: (uploadId: string) =>
    get<{ upload_id: string; uploaded: number[]; total_chunks: number }>(`/knowledge/upload/${uploadId}/status`),
  uploadComplete: (uploadId: string) =>
    post<{ document_id: string; title: string; chunks: number; status: string; kb_id?: string }>(`/knowledge/upload/${uploadId}/complete`),
  uploadDocument: (file: File, title?: string, kbId?: string) => {    const fd = new FormData()
    fd.append('file', file)
    if (title) fd.append('title', title)
    if (kbId) fd.append('kb_id', kbId)
    return http
      .request<{ document_id: string; title: string; chunks: number; status: string; kb_id: string }>({
        url: '/knowledge/documents/upload',
        method: 'POST',
        data: fd,
      })
      .then((r) => r.data)
  },
  search: (query: string, kbId?: string) =>
    post<KBSearch>('/knowledge/search', { query, rerank_n: 5, kb_id: kbId ?? undefined }),
  documents: (kbId?: string) =>
    get<{ rows: { document_id: string; title: string; source_uri: string; status: string; created_at?: string; chunk_count?: number }[]; total: number }>(
      `/knowledge/documents${kbId ? `?kb_id=${encodeURIComponent(kbId)}` : ''}`,
    ),
  documentDetail: (id: string) =>
    get<{ document_id: string; title: string; source_uri: string; status: string; created_at?: string; chunks: { chunk_id: string; seq: number; section: string; text: string; token_count: number }[] }>(
      `/knowledge/documents/${encodeURIComponent(id)}`,
    ),
  deleteDocument: (id: string) => del<{ document_id: string; deleted: boolean }>(`/knowledge/documents/${encodeURIComponent(id)}`),
}
