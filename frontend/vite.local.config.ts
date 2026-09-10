import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/postcss';
import { fileURLToPath } from 'node:url';

// Local SQLite/FastAPI distribution; the generated Sites configuration stays available.
export default defineConfig({
  plugins: [react()],
  resolve: {alias: {'@': fileURLToPath(new URL('.', import.meta.url))}},
  css: {postcss: {plugins: [tailwindcss()]}},
  server: {host: '127.0.0.1', port: 5173, strictPort: true, proxy: {'/api': process.env.FLYKEEPER_API_URL || 'http://127.0.0.1:48173'}},
  build: {outDir: 'dist/local'},
});
