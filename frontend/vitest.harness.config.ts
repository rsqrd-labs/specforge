/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"
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
    // Harness files live outside `frontend/`, so bare imports otherwise walk
    // toward the repository root and miss frontend's isolated pnpm install on
    // clean CI runners. Vite 8 removed the old `resolve.modules` escape hatch;
    // pin the one harness-owned bare import to this package explicitly.
    alias: {
      "@testing-library/react": resolve(
        __dirname,
        "node_modules/@testing-library/react",
      ),
    },
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
