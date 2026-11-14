import { readFileSync } from 'node:fs'
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
const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

export default defineConfig({
  plugins: [react(), previewRuntimePlugin()],
  // The version shown in Settings -> About comes from package.json, so it
  // can't drift from the release again.
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  build: {
    // Never base64-inline font files into the CSS: small subsets (<4 kB) were
    // being embedded, bloating the render-blocking stylesheet. As separate
    // files they load only when their unicode-range is actually used.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/.test(file) ? false : undefined),
  },
})
