import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18762',
        changeOrigin: true,
        configure(proxy) {
          proxy.on('proxyReq', (request, original) => {
            if (original.method !== 'GET') request.setHeader('Origin', 'http://127.0.0.1:18762')
          })
        },
      },
    },
  },
})
