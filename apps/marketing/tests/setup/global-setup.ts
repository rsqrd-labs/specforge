// Global setup: build the static site once before the suite runs, so every
// dist-parsing test asserts against fresh output (no stale-dist false passes).
// The build is deterministic and fast (~1.4s); a default/CI build has no Sanity
// creds, so only the homepage + 5 hubs are emitted — that is exactly the set
// the Phase-6 dist assertions target. Detail-page behavior is covered by
// component/unit tests that don't need Sanity content.
import { execFileSync } from "node:child_process"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const marketingRoot = resolve(here, "..", "..")

export default function setup() {
  // Pin the build to the credential-free contract the dist tests assert against:
  // homepage + 5 hubs only. We strip the Sanity project id (`isSanityConfigured`
  // in src/lib/sanity.ts keys off PUBLIC_SANITY_PROJECT_ID) so a dev machine —
  // or Phase-7 CI once real content exists — can't make detail pages appear and
  // break the "sitemap lists ONLY indexable routes" / route-count assertions.
  // Self-enforcing, not just documented.
  const env = { ...process.env }
  delete env.PUBLIC_SANITY_PROJECT_ID
  delete env.PUBLIC_SANITY_DATASET

  execFileSync("pnpm", ["exec", "astro", "build"], {
    cwd: marketingRoot,
    stdio: "inherit",
    env,
  })
}
