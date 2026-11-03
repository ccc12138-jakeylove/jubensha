import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// 构建产物由 FastAPI 提供：/assets 挂载 dist/assets，根路径返回 index.html。
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // 单页宣传站，禁用代码分割，产物更简单
    rollupOptions: { output: { manualChunks: undefined } },
  },
  server: {
    port: 5173,
    // 开发时把接口请求转发给本地 API，避免跨域
    proxy: { '/api': 'http://127.0.0.1:8100' },
  },
})
