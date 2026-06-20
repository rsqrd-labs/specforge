// Measurement layer for the marketing zone (issue #18, Phase 5). Two concerns:
//
//   1. Gating — analytics ships ZERO client JS unless `PUBLIC_ANALYTICS_ENABLED`
//      is exactly "true". Off by default, so CI/dev/preview builds stay
//      script-free (preserving the Phase-1/4 "zero executable JS" posture) and
//      the real vendor wiring only switches on when creds land (Phase 7). GSC
//      verification is independent: its <meta> renders whenever the token is set,
//      even with analytics disabled, because Search Console ownership doesn't
//      depend on tracking.
//
//   2. The "AI answer engines" channel (the GEO-critical signal) — a single,
//      authoritative definition of which referrer hosts count as an answer
//      engine, plus a pure `classifyReferrer()` the Phase-6 tests exercise
//      directly and the client classifier reuses (one source of truth, no drift).
//
// Vendor: Vercel Web Analytics. Its script is served first-party from
// `/_vercel/insights/*` (same-origin → CSP-clean, no third-party host to
// allowlist), and it captures the raw referrer breakdown automatically. The
// custom `track('AI Referral', …)` event normalizes that into a named channel —
// see measurement/README.md for the (honest) plan-tier caveat.

/** Analytics is opt-in. Anything other than the literal "true" leaves it off. */
export const analyticsEnabled =
  import.meta.env.PUBLIC_ANALYTICS_ENABLED === "true"

/**
 * Google Search Console verification token — the `content` of the
 * `<meta name="google-site-verification">` tag. Undefined/blank ⇒ no tag.
 */
export const gscVerification: string | undefined = (
  import.meta.env.PUBLIC_GSC_VERIFICATION || ""
).trim() || undefined

/** The Vercel custom-event name for a classified AI-engine referral. */
export const AI_REFERRAL_EVENT = "AI Referral"

/**
 * How confident we are that a referrer host means an *AI answer engine* vs. a
 * surface that mixes classic search and AI answers. Kept explicit so the core
 * channel metric stays clean: `bing.com` referrals are overwhelmingly classic
 * Bing organic search, not Copilot answers, so lumping them into the AI channel
 * would corrupt the exact number this phase exists to isolate. We still keep
 * `bing.com` (some Copilot-in-Bing answers refer as `bing.com`) — just in its
 * own bucket, so no signal is lost and the AI channel isn't inflated.
 */
export type ReferrerChannel = "ai_answer_engine" | "mixed_search_ai"

export interface AiEngineReferrer {
  /** Normalized engine key used as the custom-event property + dashboard facet. */
  engine: string
  /** Human-readable label for docs/dashboards. */
  label: string
  /** Hostnames that map to this engine (apex; subdomains match by suffix). */
  hosts: string[]
  channel: ReferrerChannel
}

/**
 * The canonical "AI answer engines" channel definition (issue #18, Phase 5.2).
 * Order matters only for first-match determinism; hosts are disjoint in
 * practice. This is the single source of truth the client classifier and the
 * Phase-6 audit both consume.
 */
export const AI_ENGINE_REFERRERS: readonly AiEngineReferrer[] = [
  {
    engine: "chatgpt",
    label: "ChatGPT",
    hosts: ["chatgpt.com", "chat.openai.com"],
    channel: "ai_answer_engine",
  },
  {
    engine: "perplexity",
    label: "Perplexity",
    hosts: ["perplexity.ai"],
    channel: "ai_answer_engine",
  },
  {
    engine: "gemini",
    label: "Google Gemini",
    hosts: ["gemini.google.com"],
    channel: "ai_answer_engine",
  },
  {
    engine: "copilot",
    label: "Microsoft Copilot",
    hosts: ["copilot.microsoft.com"],
    channel: "ai_answer_engine",
  },
  {
    engine: "claude",
    label: "Claude",
    hosts: ["claude.ai"],
    channel: "ai_answer_engine",
  },
  {
    // Deliberately a separate bucket — see ReferrerChannel. Classic Bing search
    // dominates this host; only a fraction is Copilot-in-Bing.
    engine: "bing",
    label: "Bing (mixed search/AI)",
    hosts: ["bing.com"],
    channel: "mixed_search_ai",
  },
] as const

export interface ClassifiedReferrer {
  engine: string
  label: string
  channel: ReferrerChannel
}

/**
 * Map a raw `document.referrer` (or any URL string) to an AI-engine channel
 * entry, or `null` when it isn't one. Pure and side-effect free so the Phase-6
 * suite can assert it directly. Matching is host-suffix based, so
 * `www.perplexity.ai` and `cn.bing.com` resolve to their apex entry.
 *
 * Best-effort by nature: Referrer-Policy stripping and origin-only referrers
 * mean some genuine AI traffic arrives with an empty/opaque referrer and can't
 * be classified. Treat the result as a sampler, not a census.
 */
export function classifyReferrer(
  referrer: string | null | undefined,
): ClassifiedReferrer | null {
  if (!referrer) return null
  let host: string
  try {
    host = new URL(referrer).hostname.toLowerCase()
  } catch {
    return null
  }
  if (!host) return null
  for (const entry of AI_ENGINE_REFERRERS) {
    for (const h of entry.hosts) {
      if (host === h || host.endsWith(`.${h}`)) {
        return { engine: entry.engine, label: entry.label, channel: entry.channel }
      }
    }
  }
  return null
}
