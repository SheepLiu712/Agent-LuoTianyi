import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/admin/',
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/admin/api': {
        target: 'http://127.0.0.1:60030',
        changeOrigin: true,
      },
    },
  },
});
