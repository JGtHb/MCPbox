import { resolve } from 'path'
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load env vars from project root .env (where MCPBOX_BACKEND_PORT lives)
  const env = loadEnv(mode, resolve(process.cwd(), '..'), '')
  const backendPort = env.MCPBOX_BACKEND_PORT || '8123'
  const backendUrl = `http://127.0.0.1:${backendPort}`

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 3000,
      proxy: {
        '/api': { target: backendUrl, changeOrigin: true },
        '/auth': { target: backendUrl, changeOrigin: true },
        '/health': { target: backendUrl, changeOrigin: true },
        '/mcp': { target: backendUrl, changeOrigin: true },
      },
    },
  }
})
