import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import App from './App'
import './index.css'
import './styles.less'
import { tryRecoverChunkError, tryReloadChunkPage } from './util'

function setupChunkRecovery() {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault()
    tryReloadChunkPage()
  })

  window.addEventListener('unhandledrejection', (event) => {
    tryRecoverChunkError(event.reason)
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
