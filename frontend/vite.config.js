import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { buildPreviewRuntime } from './scripts/build-preview-runtime.mjs'

// Generates the self-hosted React/ReactDOM IIFE used by DocumentEditor's
// JSX/TSX preview iframe (see scripts/build-preview-runtime.mjs). Runs once
// at dev-server start and before build so the asset always exists without a
// manual vendoring step — React itself is already a project dependency.
function previewRuntimePlugin() {
  return {
    name: 'zenith-preview-runtime',
    async buildStart() {
      await buildPreviewRuntime()
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), previewRuntimePlugin()],
})
