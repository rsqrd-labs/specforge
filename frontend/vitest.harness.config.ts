/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"
import { createRequire } from "node:module"
import { resolve } from "node:path"

const require = createRequire(import.meta.url)

/**
 * Vitest config for harness/tests/frontend contract tests.
 * RED before Phase 4 tasks are implemented; GREEN after each task completes.
 * Not included in `pnpm test` (which uses vite.config.ts) — CI stays clean.
 *
 * Run with:
 *   cd frontend && pnpm vitest run --config vitest.harness.config.ts
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    // Harness files live outside `frontend/`, so bare imports otherwise walk
    // toward the repository root and miss frontend's isolated pnpm install on
    // clean CI runners. Vite 8 removed the old `resolve.modules` escape hatch;
    // pin harness-owned bare imports to this package explicitly. React's
    // regex entry also covers the JSX runtime injected by the React plugin.
    alias: [
      {
        find: /^react(\/.*)?$/,
        replacement: `${resolve(__dirname, "node_modules/react")}$1`,
      },
      // react-router@8 is exports-only — it ships no `main`/`module`, so the
      // bare directory alias used for react below cannot resolve it. Pin the
      // resolved entry instead. This matches the bare specifier only, which is
      // all the harness tests import (MemoryRouter, from the root); a future
      // `react-router/dom` import here would need its own entry.
      {
        find: /^react-router$/,
        replacement: require.resolve("react-router", { paths: [__dirname] }),
      },
      {
        find: "@testing-library/react",
        replacement: resolve(
          __dirname,
          "node_modules/@testing-library/react",
        ),
      },
    ],
  },
  server: {
    fs: { allow: [__dirname, resolve(__dirname, "..")] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: [resolve(__dirname, "src/__tests__/setup.ts")],
    include: [resolve(__dirname, "../harness/tests/frontend/**/*.{test,spec}.{ts,tsx}")],
  },
})
