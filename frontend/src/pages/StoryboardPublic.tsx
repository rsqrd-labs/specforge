import { useEffect, useState } from "react"
import { useParams } from "react-router-dom"
import { PresenterMode } from "../components/storyboard/PresenterMode"
import { StoryboardDeck } from "../components/storyboard/StoryboardDeck"
import { StoryboardDownloadMenu } from "../components/storyboard/StoryboardDownloadMenu"
import { StoryboardLaunchPage } from "../components/storyboard/StoryboardLaunchPage"
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
// endpoint via the bare axios path in api.ts.

const NOINDEX_META_ID = "thought2build-storyboard-public-noindex"

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
  const [view, setView] = useState<"launch" | "deck">("launch")
  const [showDownloads, setShowDownloads] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  useNoIndexMeta()

  useEffect(() => {
    if (!slug) {
      setState({ kind: "not_found" })
      return
    }
    let cancelled = false
    setState({ kind: "loading" })
    setView("launch")
    setShowDownloads(false)
    setShowNotes(false)
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
        : "Storyboard — Thought2Build"
    return () => {
      document.title = "Thought2Build"
    }
  }, [state])

  if (state.kind === "loading") {
    return (
      <main className="storyboard-public" aria-busy="true">
        <StoryboardDeck isLoading title="Storyboard" />
      </main>
    )
  }

  if (state.kind === "not_found") {
    return (
      <main className="storyboard-public storyboard-public--empty">
        <h1>This Storyboard link is no longer available</h1>
        <p>
          This link may have been disabled, rotated, or mistyped. Ask the owner
          for a fresh Storyboard link.
        </p>
      </main>
    )
  }

  const { storyboard } = state
  const payload = storyboard.presentation
  return (
    <main className="storyboard-public">
      {view === "deck" ? (
        <StoryboardDeck
          payload={payload}
          status="ready"
          title={storyboard.title}
          isOwner={false}
          allowPresenterMode={storyboard.permissions.allow_notes_download}
          allowSourceLayer={storyboard.permissions.allow_source_layer}
          sharePermissions={storyboard.permissions}
          publicView={true}
          onExit={() => setView("launch")}
        />
      ) : (
        <>
          <StoryboardLaunchPage
            title={storyboard.title}
            payload={payload}
            permissions={storyboard.permissions}
            downloads={storyboard.downloads}
            sharedAt={storyboard.shared_at}
            onPresent={() => setView("deck")}
            onDownload={() => setShowDownloads((value) => !value)}
            onNotes={() => setShowNotes((value) => !value)}
          />
          {showDownloads && (
            <StoryboardDownloadMenu
              mode="public"
              title={storyboard.title}
              slug={slug}
              permissions={storyboard.permissions}
              downloads={storyboard.downloads}
              onClose={() => setShowDownloads(false)}
            />
          )}
          {showNotes && (
            <PresenterMode
              payload={payload}
              isOwner={false}
              permissions={storyboard.permissions}
              publicView={true}
              onClose={() => setShowNotes(false)}
            />
          )}
        </>
      )}
    </main>
  )
}
