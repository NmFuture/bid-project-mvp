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
      // 保留浏览器 Host/端口，供 Document Server 生成可回访的 /cache 绝对地址。
      changeOrigin: false,
      ws: true,
      rewrite: onlyofficeKeepPrefix ? undefined : (path) => path.replace(/^\/ds/, ''),
    },
    // OnlyOffice 将转换后的编辑资源放在 /cache/files 下；开发态必须与生产 Nginx 一样转发，
    // 否则 Vite 会把该地址回退到 SPA，编辑器最终显示“下载失败”。
    '/cache': {
      target: onlyofficeTarget,
      changeOrigin: false,
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
