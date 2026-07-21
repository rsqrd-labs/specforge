/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

export default defineConfig({
  plugins: [react()],
  build: {
    // Vite 8 bundles with rolldown (no esbuild) and defaults
    // build.target to "baseline-widely-available" (≈ Chrome/Edge 107,
    // Firefox 104, Safari 16). We pin it explicitly rather than inherit
    // silently: this SaaS app's audience is modern evergreen browsers, so
    // the baseline default is the deliberate, documented floor.
    target: "baseline-widely-available",
    rollupOptions: {
      output: {
        // rolldown dropped the rollup object form of manualChunks; it now
        // accepts a function only. This is the faithful translation of the
        // Vite 6 object form (codemirror / react / vendor), preserving the
        // same composition — anything not matched here is left to
        // rolldown's automatic chunking, exactly as Vite 6 behaved.
        manualChunks(id) {
          if (!id.includes("node_modules")) return
          if (/[\\/](@codemirror|@lezer|@marijn)[\\/]/.test(id)) return "codemirror"
          if (/[\\/](react|react-dom|react-router|react-router-dom|@remix-run[\\/]router|scheduler)[\\/]/.test(id))
            return "react"
          if (/[\\/](axios|zustand)[\\/]/.test(id)) return "vendor"
        },
      },
    },
  },
  server: {
    watch: {
      usePolling: true,
      interval: 300,
    },
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json", "json-summary", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/__tests__/**", "src/main.tsx", "src/vite-env.d.ts"],
      thresholds: {
        // Issue #48 release policy. Keep the aggregate floor and the
        // risk-critical per-file boundaries explicit so broad low-risk tests
        // cannot mask a regression in auth, streaming, or state management.
        statements: 80,
        branches: 80,
        functions: 80,
        lines: 80,
        // Vitest 4.1 applies a glob threshold to the matching aggregate. Keep
        // these as exact-file patterns so each boundary is independently
        // enforced without relying on a second policy parser.
        "src/services/api.ts": { statements: 90, branches: 90 },
        "src/services/sseService.ts": { statements: 90, branches: 90 },
        "src/store/generationEstimatesStore.ts": { statements: 90, branches: 90 },
        "src/store/stageStore.ts": { statements: 90, branches: 90 },
        "src/store/userStore.ts": { statements: 90, branches: 90 },
        "src/store/workspaceStore.ts": { statements: 90, branches: 90 },
        "src/hooks/useStream.ts": { statements: 90, branches: 90 },
        "src/hooks/useGitHubSync.ts": { statements: 90, branches: 90 },
        "src/hooks/useReconnectPoll.ts": { statements: 90, branches: 90 },
        "src/pages/AuthCallback.tsx": { statements: 90, branches: 90 },
        "src/components/shared/ProtectedRoute.tsx": { statements: 90, branches: 90 },
        "src/components/shared/SessionExpiryWatcher.tsx": { statements: 90, branches: 90 },
      },
    },
  },
})
