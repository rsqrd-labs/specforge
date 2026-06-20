/// <reference types="vitest/config" />
// Phase 6 validation suite (issue #18). Uses Astro's `getViteConfig` so tests
// can import `.astro` components (the Container API in geo-content.test.ts) and
// the site's TypeScript libs with the same resolution the build uses.
//
// `globalSetup` runs `astro build` unconditionally before any test, so every
// run asserts against a fresh `dist/` — this kills the stale-dist false-pass
// class outright (the build is ~1.4s). The CI job (Phase 7) builds explicitly
// too; the always-build here keeps `pnpm test` correct standalone.
import { getViteConfig } from "astro/config"

export default getViteConfig({
  test: {
    globals: true,
    environment: "node",
    globalSetup: ["./tests/setup/global-setup.ts"],
    include: ["tests/**/*.test.ts"],
    // The static build the dist-parsing tests read is produced once by
    // globalSetup; tests must not race it, so keep them serial-friendly.
    fileParallelism: true,
  },
})
