import { configDefaults, defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: { strictPort: true, proxy: { '/api': process.env.CIP_API_TARGET ?? 'http://127.0.0.1:8000', '/docs': process.env.CIP_API_TARGET ?? 'http://127.0.0.1:8000', '/openapi.json': process.env.CIP_API_TARGET ?? 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./tests/setup.ts'], restoreMocks: true, exclude: [...configDefaults.exclude, 'tests/api.wire.test.ts'] },
});
