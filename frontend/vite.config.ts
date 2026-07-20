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
        // Issue #30 baseline ratchet. Raise these monotonically as the
        // risk-focused coverage remediation lands; never lower them.
        statements: 60,
        branches: 60,
        functions: 60,
        lines: 60,
      },
    },
  },
})
