// Generates the 1200×630 Open Graph / Twitter share card at
// public/brand/og-card.png (the DEFAULT_OG_IMAGE referenced by src/lib/seo.ts).
//
// Why a script (not a hand-made asset): the card must stay in sync with the
// brand mark + wordmark, and 1200×630 is the exact 1.91:1 ratio that OG and
// Twitter `summary_large_image` expect — the previous square brand mark got
// letterboxed/cropped in previews. Run:  node scripts/generate-og-card.mjs
//
// sharp is a transitive dependency (Astro's image service) and isn't hoisted to
// the top-level node_modules under pnpm, so resolve it defensively.
import { readFileSync, readdirSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"
import { createRequire } from "node:module"

const require = createRequire(import.meta.url)
const here = dirname(fileURLToPath(import.meta.url))
const root = resolve(here, "..")

async function loadSharp() {
  try {
    return (await import("sharp")).default
  } catch {
    // Fall back to the pnpm virtual store (sharp@x.y.z/node_modules/sharp).
    const storeDir = resolve(root, "node_modules/.pnpm")
    const entry = readdirSync(storeDir).find((d) => /^sharp@\d/.test(d))
    if (!entry) throw new Error("sharp not found (install deps or add it)")
    return require(resolve(storeDir, entry, "node_modules/sharp")).default ?? require(
      resolve(storeDir, entry, "node_modules/sharp"),
    )
  }
}

const W = 1200
const H = 630
const mark = readFileSync(resolve(root, "public/brand/squirrel-mark.png"))

const sharp = await loadSharp()

// Resize the brand mark to sit in the top-left, keep its aspect ratio.
const markSize = 132
const markPng = await sharp(mark)
  .resize({ width: markSize, height: markSize, fit: "contain", background: { r: 0, g: 0, b: 0, alpha: 0 } })
  .png()
  .toBuffer()

// Background + text as SVG (vector text; the mark is composited as raster below).
// Modern Indica palette: dark slate ground, saffron accent, lotus hint.
const svg = `
<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0c0f1a"/>
      <stop offset="1" stop-color="#161a2b"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#f59e0b"/>
      <stop offset="1" stop-color="#ef7d5a"/>
    </linearGradient>
  </defs>
  <rect width="${W}" height="${H}" fill="url(#bg)"/>
  <rect x="0" y="0" width="14" height="${H}" fill="url(#accent)"/>
  <circle cx="1030" cy="120" r="360" fill="#f59e0b" opacity="0.06"/>
  <g font-family="Helvetica Neue, Helvetica, Arial, sans-serif">
    <text x="248" y="168" font-size="30" font-weight="600" fill="#f59e0b" letter-spacing="3">AI SPEC-TO-BUILD WORKSPACE</text>
    <text x="80" y="330" font-size="104" font-weight="800" fill="#f8fafc">Thought2Build</text>
    <text x="80" y="410" font-size="40" font-weight="600" fill="#cbd5e1">Turn rough product ideas into build-ready</text>
    <text x="80" y="462" font-size="40" font-weight="600" fill="#cbd5e1">specs, tests, and tasks.</text>
    <text x="80" y="556" font-size="32" font-weight="700" fill="#f8fafc">Spec</text>
    <text x="196" y="556" font-size="32" font-weight="400" fill="#64748b">→</text>
    <text x="240" y="556" font-size="32" font-weight="700" fill="#f8fafc">Plan</text>
    <text x="352" y="556" font-size="32" font-weight="400" fill="#64748b">→</text>
    <text x="396" y="556" font-size="32" font-weight="700" fill="#f8fafc">Harness</text>
    <text x="576" y="556" font-size="32" font-weight="400" fill="#64748b">→</text>
    <text x="620" y="556" font-size="32" font-weight="700" fill="#f8fafc">Tasks</text>
    <text x="${W - 80}" y="556" font-size="28" font-weight="600" fill="#94a3b8" text-anchor="end">thought2build.com</text>
  </g>
</svg>`

const out = resolve(root, "public/brand/og-card.png")
await sharp(Buffer.from(svg))
  .composite([{ input: markPng, top: 60, left: 80 }])
  .png()
  .toFile(out)

console.log(`Wrote ${out} (${W}x${H})`)
