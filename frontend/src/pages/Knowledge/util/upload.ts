import { api } from '@/services'

export const CHUNK_SIZE = 1024 * 1024 // 1MB 分片

/** 分片上传 + 断点续传 + 进度：init → 查已传分片 → 逐片传 → complete。 */
export async function chunkedUpload(
  file: File,
  title: string | undefined,
  kbId: string,
  onProgress: (pct: number) => void,
) {
  const init = await api.uploadInit({ filename: file.name, size: file.size, chunk_size: CHUNK_SIZE, title, kb_id: kbId })
  const { upload_id, chunk_size, total_chunks } = init
  let uploaded: number[] = []
  try {
    uploaded = (await api.uploadStatus(upload_id)).uploaded ?? []
  } catch {
    uploaded = []
  }
  const have = new Set(uploaded)
  for (let i = 0; i < total_chunks; i++) {
    if (have.has(i)) continue // 断点续传：跳过已上传分片
    const start = i * chunk_size
    const blob = file.slice(start, Math.min(start + chunk_size, file.size))
    await api.uploadChunk(upload_id, i, blob)
    onProgress(Math.round(((i + 1) / total_chunks) * 100))
  }
  return api.uploadComplete(upload_id)
}
