import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { getPublicStoryboard } from "../services/api"
import type { StoryboardPublicResponse } from "../types/storyboard"

// Unauthenticated public Storyboard page (Phase 20 — T-257), served at /sb/:slug
// OUTSIDE the auth guard.
//
// SECURITY: this file must NOT import the auth route guard, any authenticated
// client-side store, the signed-in viewer's profile, or any credit / account
// UI. The harness contract test enforces this by string-searching the source
// for those identifiers, so they must not appear here even in comments. The
// page reads exclusively from the unauthenticated /storyboards/public/{slug}
// endpoint via the bare axios path in api.ts (no CSRF / auth headers attached),
// and never persists source excerpts, notes, or appendix content to
// localStorage / sessionStorage.
//
// This is the foundation the cinematic public deck, presenter-free view, share
// surface, and gated downloads (T-260) build on.

const NOINDEX_META_ID = "specforge-storyboard-public-noindex"

// Inject `<meta name="robots" content="noindex, nofollow">` for the lifetime of
// the public view — belt-and-suspenders with the backend's X-Robots-Tag header.
function useNoIndexMeta() {
  useEffect(() => {
    const existing = document.getElementById(NOINDEX_META_ID)
    if (existing) return
    const meta = document.createElement("meta")
    meta.id = NOINDEX_META_ID
    meta.name = "robots"
    meta.content = "noindex, nofollow"
    document.head.appendChild(meta)
    return () => {
      meta.remove()
    }
  }, [])
}

type LoadState =
  | { kind: "loading" }
  | { kind: "not_found" }
  | { kind: "ready"; storyboard: StoryboardPublicResponse }

export default function StoryboardPublic() {
  const { slug } = useParams<{ slug: string }>()
  const [state, setState] = useState<LoadState>({ kind: "loading" })
  useNoIndexMeta()

  useEffect(() => {
    if (!slug) {
      setState({ kind: "not_found" })
      return
    }
    let cancelled = false
    setState({ kind: "loading" })
    // getPublicStoryboard maps unknown / disabled / rotated slugs to null, so a
    // bad link renders the empty state rather than crashing or redirecting.
    getPublicStoryboard(slug)
      .then((storyboard) => {
        if (cancelled) return
        setState(
          storyboard === null
            ? { kind: "not_found" }
            : { kind: "ready", storyboard },
        )
      })
      .catch(() => {
        if (!cancelled) setState({ kind: "not_found" })
      })
    return () => {
      cancelled = true
    }
  }, [slug])

  useEffect(() => {
    document.title =
      state.kind === "ready"
        ? `${state.storyboard.title} — Storyboard`
        : "Storyboard — SpecForge"
    return () => {
      document.title = "SpecForge"
    }
  }, [state])

  if (state.kind === "loading") {
    return (
      <main className="storyboard-public" aria-busy="true">
        <p>Loading…</p>
      </main>
    )
  }

  if (state.kind === "not_found") {
    return (
      <main className="storyboard-public storyboard-public--empty">
        <h1>This Storyboard link is no longer available</h1>
        <p>The link may have been disabled or replaced by its owner.</p>
      </main>
    )
  }

  const { storyboard } = state
  return (
    <main className="storyboard-public">
      <header className="storyboard-public__header">
        <h1>{storyboard.title}</h1>
      </header>
      <ol className="storyboard-public__acts">
        {storyboard.presentation.sections.map((section) => (
          <li key={section.id}>{section.title}</li>
        ))}
      </ol>
    </main>
  )
}
