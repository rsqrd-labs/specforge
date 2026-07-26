// Pings IndexNow (Bing, Yandex, and other participating engines) with the
// marketing sitemap's URL list right after a production deploy — plan
// docs/SEO_INDEXING_REMEDIATION_PLAN.md §8 T-5.3. This is instant-submission,
// not a substitute for GSC/Bing Webmaster Tools (T-5.1/T-5.2): those are the
// crawler-facing dashboards; this just tells participating engines "something
// changed, come look sooner."
//
// Deliberately best-effort: a slow/unreachable IndexNow endpoint, or a
// transient gap before the CDN alias for a brand-new deploy resolves, must
// never fail the CI `deploy` job over a non-critical SEO nicety. `main()`
// always exits 0 and reports failures as a `::warning::` annotation instead.
//
// Auth: IndexNow's only "credential" is a key that is itself published as a
// public static file at the site root (public/<key>.txt, committed alongside
// this script) — there is no secret to hold, consistent with plan §2's
// credential boundary.
import { setTimeout as sleep } from "node:timers/promises"

const INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"

/**
 * Extracts every `<loc>` URL from a sitemap document. Handles both a
 * `<sitemapindex>` (returns the child sitemap URLs) and a `<urlset>` (returns
 * page URLs) — callers distinguish the two via `isSitemapIndex`. A plain
 * regex is sufficient and dependency-free: the input is always Astro's own
 * `@astrojs/sitemap` output, never third-party/untrusted XML.
 */
export function extractLocs(xml) {
  return [...xml.matchAll(/<loc>\s*([^<\s][^<]*?)\s*<\/loc>/g)].map((m) => m[1])
}

export function isSitemapIndex(xml) {
  return /<sitemapindex[\s>]/.test(xml)
}

/**
 * Resolves the full flat list of page URLs from a sitemap entry point,
 * following one level of `<sitemapindex>` → child `<urlset>` if present.
 * `@astrojs/sitemap` never nests an index inside an index, so one level is
 * sufficient and matches the real shape of `sitemap-index.xml`.
 *
 * @param {string} sitemapIndexUrl
 * @param {(url: string) => Promise<Response>} [fetchImpl]
 */
export async function collectSitemapUrls(sitemapIndexUrl, fetchImpl = fetch) {
  const res = await fetchImpl(sitemapIndexUrl)
  if (!res.ok) {
    throw new Error(`GET ${sitemapIndexUrl} -> ${res.status}`)
  }
  const xml = await res.text()
  const locs = extractLocs(xml)
  if (!isSitemapIndex(xml)) {
    return locs
  }
  const pages = []
  for (const childUrl of locs) {
    const childRes = await fetchImpl(childUrl)
    if (!childRes.ok) {
      throw new Error(`GET ${childUrl} -> ${childRes.status}`)
    }
    pages.push(...extractLocs(await childRes.text()))
  }
  return pages
}

async function submitToIndexNow({ host, key, keyLocation, urlList }, fetchImpl = fetch) {
  return fetchImpl(INDEXNOW_ENDPOINT, {
    method: "POST",
    headers: { "Content-Type": "application/json; charset=utf-8" },
    body: JSON.stringify({ host, key, keyLocation, urlList }),
  })
}

async function withRetries(fn, { attempts = 3, delayMs = 3000 } = {}) {
  let lastErr
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await fn()
    } catch (err) {
      lastErr = err
      if (i < attempts - 1) await sleep(delayMs)
    }
  }
  throw lastErr
}

async function main() {
  const siteUrl = process.env.INDEXNOW_SITE_URL
  const key = process.env.INDEXNOW_KEY
  if (!siteUrl || !key) {
    console.log(
      "::warning::submit-indexnow: INDEXNOW_SITE_URL/INDEXNOW_KEY not set — skipping IndexNow ping (non-fatal).",
    )
    return
  }

  const origin = siteUrl.replace(/\/+$/, "")
  const host = new URL(origin).host
  const keyLocation = `${origin}/${key}.txt`
  const sitemapIndexUrl = `${origin}/sitemap-index.xml`

  try {
    const urlList = await withRetries(() => collectSitemapUrls(sitemapIndexUrl))
    if (urlList.length === 0) {
      console.log("::warning::submit-indexnow: sitemap had zero URLs — skipping submission.")
      return
    }

    const res = await withRetries(() => submitToIndexNow({ host, key, keyLocation, urlList }))
    // IndexNow: 200 = accepted, 202 = accepted (key not yet re-verified but queued).
    if (res.ok || res.status === 202) {
      console.log(`submit-indexnow: submitted ${urlList.length} URL(s) to IndexNow (status ${res.status}).`)
    } else {
      const body = await res.text().catch(() => "<unreadable>")
      console.log(
        `::warning::submit-indexnow: IndexNow rejected the submission (status ${res.status}): ${body.slice(0, 300)}`,
      )
    }
  } catch (err) {
    console.log(`::warning::submit-indexnow: failed after retries: ${err.message}`)
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  await main()
}
