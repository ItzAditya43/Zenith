import { defineConfig } from 'vite'

// Standalone from vite.config.js on purpose: that file is touched by other
// work this session and pulls in a build-time plugin (preview-runtime
// generation) that tests don't need. Vitest is happy reading its config
// from either file, so this keeps test config isolated from build config.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.test.js'],
  },
})
