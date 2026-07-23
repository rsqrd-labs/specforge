#!/usr/bin/env node
// Synthetic-query audit runner (issue #18, Phase 5.3). Dependency-free: reads
// synthetic-queries.json and emits a dated, fill-in results log (Markdown table)
// to stdout. This is a MONITORING aid, not an automated gate — it doesn't call
// any answer engine itself (most have no audit API); a human runs each query on
// each engine and records whether Thought2Build was cited. Where an engine exposes
// an API (e.g. Perplexity), wire it in later; the JSON's `method` flags which.
//
// Usage:
//   node measurement/audit.mjs                 # full results-log skeleton
//   node measurement/audit.mjs --cluster=spec-to-build
//   node measurement/audit.mjs > runs/2026-06-20.md
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, join } from "node:path"

const here = dirname(fileURLToPath(import.meta.url))
const data = JSON.parse(readFileSync(join(here, "synthetic-queries.json"), "utf8"))

const arg = process.argv.find((a) => a.startsWith("--cluster="))
const only = arg ? arg.split("=")[1] : null
const today = new Date().toISOString().slice(0, 10)

const clusters = data.clusters.filter((c) => !only || c.key === only)
if (only && clusters.length === 0) {
  console.error(`No cluster "${only}". Known: ${data.clusters.map((c) => c.key).join(", ")}`)
  process.exit(1)
}

const engines = data.engines.map((e) => e.label)
const lines = []
lines.push(`# Synthetic-query audit — ${today}`)
lines.push("")
lines.push(`Brand: **${data.target.brand}** · Hit = ${data.target.what_counts_as_a_hit}`)
lines.push("")
lines.push(`Engines: ${engines.join(", ")}`)
lines.push("")
lines.push("For each row, mark `Y` (Thought2Build cited/linked), `N` (not), or `~` (mentioned but not linked). Note the cited URL where relevant.")
lines.push("")

for (const c of clusters) {
  lines.push(`## ${c.label} \`(${c.key})\` → hub \`${c.hub}\``)
  lines.push("")
  const header = ["Query", ...data.engines.map((e) => e.key), "Notes / cited URL"]
  lines.push(`| ${header.join(" | ")} |`)
  lines.push(`| ${header.map(() => "---").join(" | ")} |`)
  for (const q of c.queries) {
    const cells = [q.replace(/\|/g, "\\|"), ...data.engines.map(() => " "), " "]
    lines.push(`| ${cells.join(" | ")} |`)
  }
  lines.push("")
}

const totalQueries = clusters.reduce((n, c) => n + c.queries.length, 0)
lines.push("---")
lines.push(`_${totalQueries} queries × ${engines.length} engines = ${totalQueries * engines.length} checks. Track the hit-rate trend across runs (commit each dated run under \`measurement/runs/\`)._`)

process.stdout.write(lines.join("\n") + "\n")
