import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
const proxy = { '/api': { target: 'http://localhost:3000', changeOrigin: true } };
export default defineConfig({ plugins: [react()], server: { host: true, port: 5173, allowedHosts: true, proxy }, preview: { host: true, port: 5173, allowedHosts: true, proxy } });
