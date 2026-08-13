// Builds a self-contained, self-hosted React + ReactDOM runtime for the
// DocumentEditor "Preview" tab's sandboxed iframe. The iframe runs JSX/TSX
// snippets that have been transpiled (via esbuild-wasm) down to
// `React.createElement(...)` calls — those calls need `React`/`ReactDOM` as
// globals inside the iframe to actually execute.
//
// React 19 no longer ships a UMD build, so instead of fetching one from a
// CDN (never happens in this project — see README "Philosophy"), we bundle
// our own tiny IIFE from the `react` / `react-dom` packages already
// installed in node_modules, using esbuild-wasm's Node API (already a
// dependency for the in-browser JSX transform). Output is a plain script
// that sets `window.React` / `window.ReactDOM`.
//
// Runs automatically from a Vite plugin (see vite.config.js) on dev server
// start and on build, so there is no manual vendoring step — unlike the
// large Pyodide runtime, React itself is already a project dependency.
import { build } from "esbuild-wasm";
import { mkdirSync, writeFileSync, existsSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outDir = path.join(root, "public", "preview-runtime");
const outFile = path.join(outDir, "react-runtime.js");

export async function buildPreviewRuntime({ force = false } = {}) {
  if (!force && existsSync(outFile) && statSync(outFile).size > 0) return outFile;
  mkdirSync(outDir, { recursive: true });
  const result = await build({
    stdin: {
      contents: `
        import * as React from "react";
        import * as ReactDOM from "react-dom/client";
        window.React = React;
        window.ReactDOM = ReactDOM;
      `,
      resolveDir: root,
      loader: "js",
    },
    bundle: true,
    format: "iife",
    minify: true,
    write: false,
  });
  const [out] = result.outputFiles;
  writeFileSync(outFile, out.contents);
  return outFile;
}

// Allow running directly: `node scripts/build-preview-runtime.mjs`
if (import.meta.url === `file://${process.argv[1]}`) {
  buildPreviewRuntime({ force: true }).then((p) => {
    console.log(`Preview runtime built: ${p}`);
  });
}
