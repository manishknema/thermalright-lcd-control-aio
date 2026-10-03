import { defineConfig } from 'vite';

// The UI is served by the display service at its root, possibly behind a reverse
// proxy prefix, so every URL is relative.
// Dev: `DISPLAY_TOKEN=... pnpm dev` proxies api/* to a running service and adds
// the token header a reverse proxy would inject in production.
const target = process.env.DISPLAY_API || 'http://127.0.0.1:7499';
const token = process.env.DISPLAY_TOKEN || '';

export default defineConfig({
  base: './',
  esbuild: { jsx: 'automatic', jsxImportSource: 'preact' },
  build: {
    outDir: '../src/thermalright_lcd_control/web',
    emptyOutDir: true,
    assetsDir: 'assets',
    target: 'es2020',
    reportCompressedSize: true,
  },
  server: {
    proxy: {
      '/api': { target, changeOrigin: true, headers: token ? { 'X-Display-Token': token } : {} },
    },
  },
});
