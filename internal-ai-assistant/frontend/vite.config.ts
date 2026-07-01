import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure: (proxy) => {
          // 透传 SSE：禁用代理对 text/event-stream 的缓冲，确保增量 delta 实时到达浏览器
          proxy.on('proxyReq', (proxyReq) => {
            proxyReq.setHeader('Accept-Encoding', 'identity')
          })
          proxy.on('proxyRes', (proxyRes) => {
            const ct = String(proxyRes.headers['content-type'] || '')
            if (ct.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              proxyRes.headers['x-accel-buffering'] = 'no'
              delete proxyRes.headers['content-length']
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('@lark-base-open/js-sdk')) return 'vendor-feishu'
        },
      },
    },
  },
})
