import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/agents': 'http://127.0.0.1:8000',
      '/tools': 'http://127.0.0.1:8000',
      '/knowledge': 'http://127.0.0.1:8000',
      '/cost': 'http://127.0.0.1:8000',
      '/events': 'http://127.0.0.1:8000',
      '/queue': 'http://127.0.0.1:8000',
      '/approvals': 'http://127.0.0.1:8000',
      '/evaluations': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/meta': 'http://127.0.0.1:8000',
      '/data': 'http://127.0.0.1:8000',
    },
  },
})
