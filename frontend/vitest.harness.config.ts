/// <reference types="vitest" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { resolve } from "node:path"

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
    modules: [resolve(__dirname, "node_modules"), "node_modules"],
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
