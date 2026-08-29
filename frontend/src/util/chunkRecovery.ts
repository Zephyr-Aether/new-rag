const CHUNK_RELOAD_FLAG = '__agent_platform_chunk_reload_at__'
const CHUNK_RELOAD_COOLDOWN_MS = 15000

const RECOVERABLE_CHUNK_ERROR_RE = /Failed to fetch dynamically imported module|Loading chunk [\d]+ failed|Importing a module script failed|Cannot read properties of (?:undefined|null) \(reading 'default'\)|Cannot destructure property 'default' of .* as it is (?:undefined|null)/i

function lastReloadAt(): number {
  const raw = sessionStorage.getItem(CHUNK_RELOAD_FLAG)
  if (!raw) return 0
  const n = Number(raw)
  return Number.isFinite(n) ? n : 0
}

function canRetryNow(): boolean {
  const last = lastReloadAt()
  return last === 0 || Date.now() - last > CHUNK_RELOAD_COOLDOWN_MS
}

export function isRecoverableChunkError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return RECOVERABLE_CHUNK_ERROR_RE.test(message)
}

export function tryReloadChunkPage(): boolean {
  if (!canRetryNow()) return false
  sessionStorage.setItem(CHUNK_RELOAD_FLAG, String(Date.now()))
  window.location.reload()
  return true
}

export function tryRecoverChunkError(error: unknown): boolean {
  if (!isRecoverableChunkError(error)) return false
  return tryReloadChunkPage()
}
