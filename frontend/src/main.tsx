import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import './styles.css'

const CHUNK_RELOAD_FLAG = '__agent_platform_chunk_reload__'

function shouldReloadForChunkError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return /Failed to fetch dynamically imported module|Loading chunk [\d]+ failed|Importing a module script failed/i.test(message)
}

function setupChunkRecovery() {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault()
    if (sessionStorage.getItem(CHUNK_RELOAD_FLAG)) return
    sessionStorage.setItem(CHUNK_RELOAD_FLAG, '1')
    window.location.reload()
  })

  window.addEventListener('unhandledrejection', (event) => {
    if (!shouldReloadForChunkError(event.reason)) return
    if (sessionStorage.getItem(CHUNK_RELOAD_FLAG)) return
    sessionStorage.setItem(CHUNK_RELOAD_FLAG, '1')
    window.location.reload()
  })
}

setupChunkRecovery()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <App />
    </HashRouter>
  </React.StrictMode>,
)
