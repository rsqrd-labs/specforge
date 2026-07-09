# Settings → Account Hub

**Goal:** Replace the current single-purpose `/settings` page (GitHub install + a
read-only data-retention card) with a proper, discoverable account area — one shell,
multiple sections, one shared entry point — without regressing the two features that
already live there.

## Current state (audit)

| Surface | Today | Problem |
|---|---|---|
| `pages/Settings.tsx` | Renders `GitHubConnection` + `DataRetentionPanel` only | Page named "Settings" has exactly one actionable control |
| Entry points | `components/shared/GitHubStatusPill.tsx` (Dashboard header), `components/workspace/SyncStatusBanner.tsx:40`, and `components/workspace/ExportGitHubModal.tsx:331` all link/navigate to bare `/settings` — every one of them GitHub-flavored | Every door into the account area is GitHub-branded; nothing reads as a general "Settings" entry point |
| Identity (avatar, name, sign-out) | Lives in `pages/Dashboard.tsx` header (`UserAvatar`, `handleLogout`) | Not reachable from Settings at all |
| Credits / plan | `pages/Billing.tsx`, a fully separate route with its own back-button nav (`BillingNav`) | No link from Settings to Billing or back |
| Account deletion | Does not exist — no frontend UI, no backend endpoint | CLAUDE.md's billing docs already anticipate "account-deletion settlement ops," but nothing implements the user-facing side |
| `GitHubConnection` installed state | Full hero treatment (gradient glow, large icon, `h1`) persists even once already installed | Oversized for a "nothing left to do" state once the page has more than one section |
| `settings-nav-spacer` / `billing-nav-spacer` | Both `<span>...spacer</span>` elements, hidden via `visibility: hidden` in CSS | Harmless today but fragile — literal placeholder text sitting in markup, in **both** `Settings.tsx` and `Billing.tsx:93` |
| Backend GitHub redirects | `routers/integrations.py:452` → `{frontend_url}/settings?github_installed=true\|false`; `routers/auth.py:224-228` → `/settings?github_connected=true` / `?github_error=…` | Both are load-bearing query params `GitHubConnection.tsx:112` reads via `useSearchParams` on the bare `/settings` path — a naive redirect of `/settings` → `/settings/profile` strands or drops these signals |
| Return-to navigation | `Settings.tsx:20-54` implements `state.from` + sessionStorage-backed "Back to Workspace/Dashboard"; `GitHubStatusPill` and `SyncStatusBanner` pass `state={{ from }}` when navigating here | The new shell must preserve this — users arriving from a workspace sync banner need a way back to that workspace, not just to Profile |
| Route guard | `App.tsx:100` guards the exact path `"/settings"` inside `ProtectedRoute` | Nested routes need `"/settings/*"` (or nested `<Route>` children under one guarded parent), or sub-routes fall outside the guard |
| BYOK provider API keys | Mentioned in CLAUDE.md's product pitch, but no router, no UI, no DB wiring beyond the GitHub-only key vault | **Out of scope for this plan** — flagged as a possible future section, not a gap this plan closes |

Net effect: three disconnected "account" surfaces (Dashboard header, Settings,
Billing) with zero cross-links, reached exclusively through GitHub-branded entry
points.

## Target IA

```
/settings/profile        (new)   — avatar, name, email, sign-out, delete account
/settings/integrations   (moved) — existing GitHubConnection, unchanged behavior
/settings/data-privacy   (moved) — existing DataRetentionPanel, unchanged behavior
/settings/billing        (moved) — existing Billing.tsx content, as a section
```

One shell (`SettingsShell`) with tab/rail navigation, URL-synced via nested routes so
each section is bookmarkable and shareable. Reuses the existing `settings-card` glass
visual language and Modern Indica tokens (`primary #8f4e00`, `outline-variant
#dbc2b0`) — no new visual system, just a new navigation layer over it.

## Design principles

- **One entry point.** Every path into account-related UI (Dashboard avatar pill,
  GitHub status pill, any future "billing" link) lands in the same shell, on the
  relevant section. No more silently-separate pages.
- **Weight matches state.** A resolved/settled section (GitHub already installed, data
  retention which is inherently static) gets quieter visual treatment than an
  action-needed section. Hero-card gradients are for first-run states, not steady state.
- **Relocate before you build.** Phases that move existing, working components
  (Integrations, Data & Privacy) ship first and carry near-zero behavioral risk.
  Net-new feature work (Profile's delete-account) and the highest-blast-radius move
  (Billing, which owns checkout/polling state) ship last, each on its own PR.
- **No regression in reachability.** Old bookmarked/linked URLs (`/settings`,
  `/billing`, any checkout-return redirect target) must keep working — redirect, don't
  delete.

---

## Phase 1 — Shell & navigation (foundation)

- Build `SettingsShell` (new component) with a left-rail / tab-strip navigation,
  backed by nested routes: `/settings/profile`, `/settings/integrations`,
  `/settings/data-privacy`, `/settings/billing`, each rendering its Phase 3
  content immediately (Phase 1 and Phase 3 ship together — see Sequencing) so no
  route exists with empty/placeholder content in between.
  - Use `<nav>` + `aria-current="page"` semantics, not `role="tablist"` — these are
    URL-synced route links a user can bookmark/share, not in-page arrow-key-switched
    tabs, so `tablist`/`tab` roles would misrepresent the interaction model.
  - Update `App.tsx:100`'s route from exact `"/settings"` to `"/settings/*"` (or
    nest child `<Route>`s under one `ProtectedRoute`-guarded parent) so every
    sub-route stays behind auth.
- New tab component styled from existing tokens: active indicator in `primary`
  (`#8f4e00`), resting state in `outline-variant` (`#dbc2b0`), consistent with the
  pill/eyebrow shapes already used in `GitHubConnection`. No tab primitive exists
  in the codebase yet (checked — `StoryboardDeck` is unrelated), so this is new.
  Specify small-viewport behavior explicitly (collapse to a horizontal scroll strip
  or a select-style dropdown below ~640px — the current `GitHubStatusPill` already
  collapses at that breakpoint, so the shell needs an equivalent, not silence).
- Fix the entry points, all of which are GitHub-branded today and must retarget to
  `/settings/integrations` specifically (not bare `/settings`):
  `GitHubStatusPill.tsx`, `SyncStatusBanner.tsx:40`, `ExportGitHubModal.tsx:331`.
  The Dashboard header's avatar/name pill (`UserAvatar` in `pages/Dashboard.tsx`)
  becomes the one genuinely general entry point, routing to `/settings/profile`.
- Preserve return-to navigation: port `Settings.tsx`'s existing `state.from` +
  sessionStorage back-navigation into `SettingsShell` unchanged, so a user arriving
  from `SyncStatusBanner` (mid-workspace) still gets "Back to Workspace," not a
  generic "Back to Dashboard."
- Redirect handling for the backend's GitHub OAuth/App callbacks: `bare /settings`
  must keep resolving with its query string intact and routed to
  `/settings/integrations` specifically, since `routers/integrations.py:452` and
  `routers/auth.py:224-228` redirect to `/settings?github_installed=…` /
  `?github_connected=…` / `?github_error=…`, and `GitHubConnection.tsx:112` reads
  `github_installed` off exactly that path. Either add a frontend redirect that
  preserves the full query string when landing on bare `/settings`, or (cleaner)
  update both backend redirect targets to `/settings/integrations?...` directly.
- Clean up the literal `"spacer"` text nodes in **both** `settings-nav-spacer`
  (`Settings.tsx`) and `billing-nav-spacer` (`Billing.tsx:93`): mark them
  `aria-hidden="true"` with no text content.

**Exit:** shell exists with real content in every section (merged with Phase 3),
reachable from clearly-labeled entry points, all GitHub-flow redirects (frontend
and backend-driven) land correctly with query params intact, old `/settings` URL
still resolves, workspace return-to navigation unchanged.

## Phase 2 — Profile section (new)

- New `ProfilePanel` component under `/settings/profile`: avatar, display name,
  email (read-only — sourced from Google OAuth, no edit UI), member-since date if
  available from the user record.
- Relocate **Sign out** here from the Dashboard header. Decide during build whether
  to keep a lightweight duplicate in the Dashboard header too (sign-out is a
  high-frequency action people expect near their name) or fully centralize it —
  default to keeping both unless it visually clutters the header.
- **Delete account** (net-new, not a relocation): confirmation-gated UI here, backed
  by a new backend endpoint. Must account for the billing-side settlement already
  referenced in CLAUDE.md's Lemon Squeezy/Razorpay sections (active credit packs,
  pending debts) before the account record itself is removed. Treat as its own
  sub-project — see "Sequencing" below.

**Exit:** Profile section is feature-complete except delete-account, which may ship
in a follow-up PR without blocking the rest of this plan.

## Phase 3 — Integrations & Data & Privacy sections (relocation, low risk)

*Ships together with Phase 1 — the shell isn't merged until its routes have real
content, so treat "Phase 1" and "Phase 3" as one PR in practice; kept as separate
phases here only to separate the navigation/plumbing work from the content moves.*

- Move `GitHubConnection` into `/settings/integrations` unchanged behaviorally.
  Downweight the already-installed visual state: smaller icon, no gradient glow,
  `h2` instead of `h1` — it's no longer the only thing on the page, so it no longer
  needs to dominate it.
- Move `DataRetentionPanel` into `/settings/data-privacy` unchanged. Keep it visually
  secondary (still a card, but lower visual weight than Profile/Integrations) since
  it's informational only, never actionable.

**Exit:** both existing features work identically inside the new shell; this phase
is a pure relocation + restyle, no new logic. Run `pnpm test` and `pnpm tsc` clean
before merge — existing `Settings.test.tsx` coverage should be ported to cover the
shell's routing, not deleted.

## Phase 4 — Billing section (consolidation, highest risk — ship last)

- Fold `pages/Billing.tsx` content into `/settings/billing` using the shared shell.
- Keep `/billing` alive as a redirect to `/settings/billing` **that preserves the
  query string** — `Billing.tsx:164` reads `checkout_ref` off `useSearchParams` to
  drive the post-checkout polling state machine, so `/billing?checkout_ref=…` must
  become `/settings/billing?checkout_ref=…`, not drop the param. Before removing
  the standalone route, audit every place that links to it directly, including
  `LEMONSQUEEZY_SUCCESS_URL` / `createCheckoutSession`'s return target and any
  Razorpay payment-link redirect.
- This section owns the checkout/polling state machine (`PollingStatus`,
  `fetchBillingStatus`) — do this only after Phases 1–3 have proven the shell
  pattern on lower-risk sections.

**Exit:** one account hub, four sections, all previously-scattered account UI
reachable from a single, correctly-labeled entry point. `checkout_ref` polling
verified end-to-end against the new URL shape before the `/billing` redirect ships.

---

## Sequencing recommendation

1. Ship Phases 1 and 3 as one PR: shell + navigation plumbing + entry-point fixes
   (frontend and backend redirect targets) + the two mechanical relocations. A
   shell with no real content behind its routes isn't shippable on its own, so
   these aren't meaningfully separable.
2. Profile minus delete-account as the next PR — additive, low risk once the shell
   exists.
3. Delete-account (back half of Phase 2) as its own follow-up task — it has real
   backend unknowns (billing settlement, data purge ordering) independent of the IA
   work and shouldn't block it.
4. Phase 4 (Billing) as its own PR, last, given the checkout-flow blast radius and
   the `checkout_ref` redirect requirement above.

## Non-goals

- Building BYOK provider-key management. Not implemented anywhere in the stack
  today; adding it is a separate product decision, not part of this IA fix. If it
  ships later, `/settings` is the natural place for it, and this shell already
  anticipates a fifth tab.
- Redesigning the visual system. This plan reuses Modern Indica tokens and the
  existing `settings-card` glass pattern throughout — no new color/typography work.
