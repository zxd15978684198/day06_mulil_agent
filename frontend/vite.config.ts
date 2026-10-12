import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// P0 冻结的三条构建契约（见 frontend/CONTRACTS.md D3/D4/D5）
//   D3 base 按命令切换：dev 用 '/'（Vite 自己服务），build 用 '/static/'
//      —— 因为 FastAPI 把 src/static 挂在 /static 上（paths.py:42 STATIC_DIR）
//   D4 dev 下 '/api' 代理到后端 127.0.0.1:8000，前端代码里永远只写相对路径 '/api/...'
//   D5 outDir 指到 ../src/static；emptyOutDir 会清空它（这是预期，见 CONTRACTS.md K5）
export default defineConfig(({ command }) => ({
  plugins: [react(), tailwindcss()],
  base: command === 'build' ? '/static/' : '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  build: {
    outDir: '../src/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
}))
