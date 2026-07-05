import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBase = (env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')
  const devPort = Number(env.VITE_DEV_PORT || 5173)
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  const onlyofficeTarget = env.VITE_ONLYOFFICE_PROXY_TARGET || 'http://127.0.0.1:8080'
  const onlyofficeKeepPrefix = env.VITE_ONLYOFFICE_PROXY_KEEP_PREFIX === 'true'
  const proxyBase = apiBase.startsWith('/') ? apiBase : '/api'
  const proxy = {
    [proxyBase]: {
      target: proxyTarget,
      changeOrigin: true,
    },
    '/ds': {
      target: onlyofficeTarget,
      changeOrigin: true,
      ws: true,
      rewrite: onlyofficeKeepPrefix ? undefined : (path) => path.replace(/^\/ds/, ''),
    },
  }

  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: Number.isFinite(devPort) ? devPort : 5173,
      proxy,
    },
    preview: {
      proxy,
    },
  }
})
