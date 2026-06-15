# Issue #21 — Branded, Informative Loading Screens

**Goal:** Replace every loading state across SpecForge with one branded, accessible,
informative loading system: animated squirrel, stage progress, and an honest
estimated-time-remaining signal. Production-grade — secure, scalable, reliable, robust.

## Current state (audit)

| Surface | Today | Problem |
|---|---|---|
| `components/workspace/StreamingOverlay.tsx` | 4-stage rail + elapsed ticker + liveness copy | No brand, no ETA |
| `components/shared/BrandLogo.tsx` | Static **508 KB** PNG | Not animated; heavy |
| `App.tsx` route `<Suspense fallback={null}>` | Renders nothing on lazy load | Blank screen |
| AuthCallback, Dashboard, ~20 modals/buttons | Bespoke per-component loaders | Inconsistent, unbranded |
| Backend heartbeat `stage_manager.py:1792` | `{state:"generating", elapsed_seconds}` only | No phase, no ETA source |

## Design principles (the non-negotiables)

- **One primitive, many variants.** A single `<BrandLoader>` + `useEtaEstimate` hook.
  Every other loader is refactored to it. No new bespoke spinners.
- **Honest progress.** Never a countdown that hits 0 and keeps spinning. The bar
  *decelerates and asymptotes* (caps ~90%) until the real `done` arrives. Copy is
  banded ("usually ~45s"), never falsely precise.
- **Degrade gracefully.** CSS-only animation (no JS/Lottie runtime dep), self-hosted
  asset (no network fetch), `prefers-reduced-motion` path, ETA optional and
  non-blocking. If the telemetry endpoint is down, a constant heuristic table drives ETA.

---

## Phase 1 — Branded loader primitive (frontend-only, ships immediately)

### 1a. Animated squirrel mark → bundled Lottie JSON (decided)
Add `components/shared/BrandLoader.tsx` and a **self-hosted** `assets/squirrel-loader.json`
(designer-authored Lottie), rendered via `lottie-web`/`lottie-react`.
- **Guardrails that make Lottie production-safe here (all mandatory):**
  - *Security:* the JSON is **bundled/self-hosted — no remote URL load** (preserves the
    codebase's no-network-fetch ethos); pin & audit `lottie-web` (`pnpm audit` in CI);
    strip any expression/`t" "`-embedded image data so the player can't fetch or eval.
  - *Reliability:* **lazy-load the player** (`React.lazy`/dynamic import) so it never
    blocks first paint, and wrap it so a player/asset failure **falls back to the static
    `BrandLogo` mark** — a loader must never itself become a broken state.
  - *Performance:* keep the JSON small (designer budget, asset ≤ ~75 KB; CI size gate);
    render `renderer: "svg"`, cap loop FPS, and **pause on `document.hidden`** + when
    off-screen (no wasted main-thread frames).
  - *Accessibility:* `prefers-reduced-motion` → **do not mount the player**; show the
    static mark + SR text instead.
- Keep `BrandLogo.tsx` as the static sibling and the reduced-motion / fallback target.
- Replace the 508 KB raster usages; keep one PNG only for OG/social.
- **If design can't deliver the Lottie source in time**, ship the loader shell against a
  placeholder CSS-animated mark and drop the JSON in later — no API change.

### 1b. `<BrandLoader variant size>` API
```
variant: "inline" | "block" | "overlay"   // button | route/section | full generation
size:    "sm" | "md" | "lg"
label?:  string                            // SR + visible caption
showEta?: EtaEstimate                       // optional, Phase 2
```
- Always renders `role="status" aria-live="polite" aria-busy="true"` with an
  SR-only text label so screen readers announce state without motion.
- Pauses animation when `document.hidden` (Page Visibility API) — no wasted frames.

### 1c. Wire the primitive everywhere
- `App.tsx`: replace all `<Suspense fallback={null}>` with `<BrandLoader variant="block">`.
- AuthCallback, Dashboard, modals, async buttons → `<BrandLoader variant="inline">`.
- `StreamingOverlay`: embed `<BrandLoader variant="overlay">` in the loading card,
  preserving the existing stage rail.

**Exit:** one shared, branded, accessible loader on every surface. No ETA yet.

---

## Phase 2 — Honest ETA (the hard part)

ETA must be engineered — the backend exposes no estimate today.
**Decision: ship 2a (heuristic-only) in the first delivery; 2b/2c are follow-up PRs.**

### 2a. Ship-first: client heuristic baselines  ← first delivery
- `useEtaEstimate(stageType, operation)` returns `{p50, p90}` from a constant table
  (e.g. spec ~30s, plan ~45s, harness ~60s, tasks ~50s; regenerate/patch variants).
- Render a **decelerating progress bar** that asymptotes at ~90% of p90 and a banded
  caption ("usually ~45s · still working" past p90). Drives off the existing
  `elapsedSeconds` ticker + `progress` heartbeat already in `StreamingOverlay`.
- Zero backend dependency → instant, reliable baseline.

### 2b. Data-driven: backend percentile endpoint  ← follow-up PR
- `GET /stages/generation-estimates` → cached `{ (provider,stage,operation): {p50,p90,n} }`.
  - Computed from existing telemetry (`llm_cost_events` / eval timing), **aggregate
    only — no per-user data, no PII** (security: no leakage, just durations + counts).
  - Computed by a **cheap periodic job → Redis (15 min TTL)**, *not* per request
    (scalable: O(1) reads, no query amplification under load).
  - Authenticated + rate-limited like other read endpoints.
- Frontend prefers live percentiles; **falls back to the 2a constant table** on any
  error/empty/`n < threshold` (robust: endpoint failure never degrades the UX below
  the heuristic baseline).

### 2c. (Optional) Phase-accurate progress
- Extend the heartbeat payload with `phase: "streaming"|"quality_gate"|"critic"|"persisting"`
  (backward-compatible additive field; harness contract test updated).
- `StreamingOverlay` reflects the real phase instead of inferring from elapsed alone.

**Exit:** every generation shows stage + phase + honest, data-backed ETA band.

---

## Cross-cutting guarantees (maps to the brief)

- **Secure:** no external animation/asset network calls; static bundled SVG (no script
  surface); ETA endpoint aggregate-only (no PII), authed + rate-limited; `aria-live`
  text never echoes untrusted/model content.
- **Scalable:** ETA aggregates precomputed to Redis by a periodic job; constant-table
  fallback means the core UX has *zero* backend dependency; animations are
  compositor-only so 100s of concurrent loaders cost ~nothing.
- **Reliable:** CSS-only loader survives JS-chunk failure; ETA is non-blocking and
  always falls back; reduced-motion path; tab-hidden pause.
- **Robust / accessible:** WCAG 2.2 — `role="status"`, `aria-live="polite"`,
  `aria-busy`, SR-only elapsed/ETA text, contrast-checked, `prefers-reduced-motion`,
  no flashing (seizure-safe).

## Testing & rollout

- **Unit (vitest):** ETA math (asymptote, banding, fallback), reduced-motion branch,
  visibility-pause.
- **RTL:** each `BrandLoader` variant renders correct a11y roles; `StreamingOverlay`
  shows ETA band + stage rail.
- **Harness contract test:** new `progress.phase` field (Phase 2c) on the SSE contract.
- **Perf:** assert animation uses only transform/opacity; SVG bundle-size budget in CI.
- **Rollout:** feature flag `branded_loaders` to dark-launch; migrate surfaces
  incrementally (Phase 1c is independent per-component); flip flag once StreamingOverlay
  + routes are verified.

## Sequencing

1. **Phase 1a/1b** — `BrandLoader` + animated SVG (1 PR).
2. **Phase 1c** — migrate all loaders behind the flag (1 PR, mechanical).
3. **Phase 2a** — heuristic ETA in `StreamingOverlay` (1 PR).
4. **Phase 2b** — telemetry endpoint + Redis job + frontend wiring (1 PR).
5. **Phase 2c** — optional phase-accurate heartbeat (1 PR, additive).

Phases 1 and 2a deliver the full visible win (branding + stage progress + ETA);
2b/2c upgrade ETA accuracy without changing the UX contract.
