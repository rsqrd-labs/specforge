import { gzipSync } from "node:zlib"
import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"

const assetDirectory = new URL("../dist/assets/", import.meta.url)
const budgets = [
  [/^index-.*\.css$/, 55],
  [/^index-.*\.js$/, 36],
  // Re-baselined for React 19.2 (issue #87). Measured with this script's own
  // gzip on a production build: React 18.3 shipped 58.27 KiB against the prior
  // 60 ceiling; React 19.2 ships 71.89 KiB — a +13.6 KiB step from React 19's
  // larger runtime, not from app code. 76 restores roughly the headroom the
  // old number carried. Re-measure rather than nudge this if it trips again.
  [/^react-.*\.js$/, 76],
  [/^Workspace-.*\.js$/, 58],
  [/^MarkdownRenderer-.*\.js$/, 110],
  [/^codemirror-.*\.js$/, 170],
]

const failures = []
for (const [pattern, limitKb] of budgets) {
  const filename = readdirSync(assetDirectory).find((candidate) => pattern.test(candidate))
  if (!filename) {
    failures.push(`Missing expected bundle matching ${pattern}`)
    continue
  }
  const gzipKb = gzipSync(readFileSync(join(assetDirectory.pathname, filename))).byteLength / 1024
  if (gzipKb > limitKb) {
    failures.push(`${filename}: ${gzipKb.toFixed(2)} KiB gzip exceeds ${limitKb} KiB`)
  }
}

if (failures.length) {
  console.error(`Bundle budget failed:\n${failures.join("\n")}`)
  process.exit(1)
}

console.log("Bundle budgets passed")
