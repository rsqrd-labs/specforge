# Marketing-zone measurement

> Issue #18, Phase 5.2/5.3. How we measure organic + answer-engine (GEO)
> acquisition for the Astro marketing zone. Everything here is **off by default**
> and ships **zero client JS** until switched on with real credentials (Phase 7).

## Components

| Concern | Where | Switch |
| --- | --- | --- |
| Web analytics (traffic, referrers) | Vercel Web Analytics | `PUBLIC_ANALYTICS_ENABLED=true` |
| AI-engine referral channel | `src/lib/analytics.ts` + classifier in `Analytics.astro` | same flag |
| Search Console (organic queries/coverage) | `<meta name="google-site-verification">` | `PUBLIC_GSC_VERIFICATION=<token>` |
| GEO visibility audit | `synthetic-queries.json` + `audit.mjs` | manual, see `SYNTHETIC_QUERY_AUDIT.md` |

Gating lives in [`../src/lib/analytics.ts`](../src/lib/analytics.ts). With the
flag unset, `BaseLayout` renders no analytics island and no classifier — the
zone keeps the Phase-1/4 "zero executable JS" posture. The GSC `<meta>` is
independent: it renders whenever its token is set, even with analytics off,
because Search Console ownership doesn't depend on tracking.

## Analytics vendor: Vercel Web Analytics

Chosen because the zone deploys on Vercel: the script is served **first-party
from `/_vercel/insights/*`** (same-origin → CSP-clean, no third-party host to
allowlist), it's cookieless/privacy-light (no consent banner), and it captures
the **referrer breakdown automatically**. Enable Web Analytics on the Vercel
project, then set `PUBLIC_ANALYTICS_ENABLED=true`.

## The "AI answer engines" channel

The single source of truth for which referrers count as an answer engine is
`AI_ENGINE_REFERRERS` in [`../src/lib/analytics.ts`](../src/lib/analytics.ts).
The same table powers the Phase-6 tests, so the channel can't drift from what's
asserted.

| Engine | Host(s) | Channel |
| --- | --- | --- |
| ChatGPT | `chatgpt.com`, `chat.openai.com` | `ai_answer_engine` |
| Perplexity | `perplexity.ai` | `ai_answer_engine` |
| Google Gemini | `gemini.google.com` | `ai_answer_engine` |
| Microsoft Copilot | `copilot.microsoft.com` | `ai_answer_engine` |
| Claude | `claude.ai` | `ai_answer_engine` |
| Bing | `bing.com` | `mixed_search_ai` |

**Why `bing.com` is a separate bucket.** Referrals from `bing.com` are
overwhelmingly *classic Bing organic search*, not Copilot answers. Folding them
into the AI channel would inflate the exact number this phase exists to isolate.
We keep `bing.com` (some Copilot-in-Bing answers do refer as `bing.com`) but in
its own `mixed_search_ai` bucket — so the core AI channel stays clean and no
signal is dropped. `copilot.microsoft.com` is the high-confidence Copilot host.

### Two signals, measured two ways

1. **Guaranteed baseline — native referrers.** Vercel Web Analytics records the
   referrer host on every pageview, so `chatgpt.com` / `perplexity.ai` / etc.
   appear in the Referrers breakdown with **no extra wiring** on any plan. This
   is the dependable channel: filter the breakdown by the hosts above.
2. **Enhancement — a named custom event.** When a recognized referrer is seen,
   the classifier fires `track('AI Referral', { engine, channel })` so the
   channel is a first-class, normalized event instead of a host filter.
   **Caveat (be honest):** Vercel **custom events require a Pro+ plan**; on Hobby
   they're silently dropped. So treat the custom event as a nice-to-have layered
   on top of the native-referrer baseline, not the baseline itself.

### Inherent limitation

Referrer-based attribution is **best-effort**: `Referrer-Policy` stripping,
origin-only referrers, and in-app browsers mean some genuine AI traffic arrives
with an empty/opaque referrer and won't classify. The channel is a **sampler,
not a census** — read it as a directional trend, and corroborate with the
synthetic-query audit below.

## GEO visibility audit

See [`SYNTHETIC_QUERY_AUDIT.md`](./SYNTHETIC_QUERY_AUDIT.md). The referral
channel above measures **traffic that already arrived** from answer engines; the
synthetic audit measures **whether we're visible** in their answers in the first
place. Run the audit (`node measurement/audit.mjs`) to produce a dated results
log; commit runs under `measurement/runs/`.

## Deferred

- `/llms.txt` — explicitly deferred (issue #18: not a launch dependency).
- Instant-publish/ISR analytics on content edits — build-time + deploy-hook is
  the launch posture (Phase 7).
