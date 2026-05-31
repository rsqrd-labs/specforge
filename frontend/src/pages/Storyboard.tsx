import axios from "axios"
import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { PresenterMode } from "../components/storyboard/PresenterMode"
import { StoryboardDeck } from "../components/storyboard/StoryboardDeck"
import { StoryboardDownloadMenu } from "../components/storyboard/StoryboardDownloadMenu"
import { StoryboardLaunchPage } from "../components/storyboard/StoryboardLaunchPage"
import { StoryboardShareModal } from "../components/storyboard/StoryboardShareModal"
import { getApiErrorMessage, getStoryboard } from "../services/api"
import type { StoryboardDetail, StoryboardSharePermissions } from "../types/storyboard"

// Authenticated owner Storyboard page (Phase 20 — T-257).
//
// This is the foundation the cinematic deck (T-259), presenter mode, source
// layer, share modal, and download menu build on. It is registered behind the
// auth guard in App.tsx and fetches the owner's full Storyboard detail by id.
// A non-owned or unknown id surfaces a not-found state (the backend returns 404
// scoped to the caller, so another account's Storyboard is indistinguishable
// from a missing one).

type LoadState =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "not_found" }
  | { kind: "ready"; storyboard: StoryboardDetail }

export default function Storyboard() {
  const { id } = useParams<{ id: string }>()
  const [state, setState] = useState<LoadState>({ kind: "loading" })
  const [view, setView] = useState<"launch" | "deck">("launch")
  const [showDownloads, setShowDownloads] = useState(false)
  const [showNotes, setShowNotes] = useState(false)
  const [showShareModal, setShowShareModal] = useState(false)

  useEffect(() => {
    if (!id) {
      setState({ kind: "not_found" })
      return
    }
    let cancelled = false
    setState({ kind: "loading" })
    getStoryboard(id)
      .then((storyboard) => {
        if (!cancelled) {
          setState({ kind: "ready", storyboard })
          setView("launch")
          setShowDownloads(false)
          setShowNotes(false)
          setShowShareModal(false)
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return
        // 404 is owner-scoped: a non-owned or missing id is indistinguishable.
        if (axios.isAxiosError(error) && error.response?.status === 404) {
          setState({ kind: "not_found" })
        } else {
          setState({ kind: "error", message: getApiErrorMessage(error) })
        }
      })
    return () => {
      cancelled = true
    }
  }, [id])

  function updateShareState(next: {
    enabled: boolean
    slug: string | null
    permissions: StoryboardSharePermissions
  }) {
    setState((current) => {
      if (current.kind !== "ready") return current
      return {
        kind: "ready",
        storyboard: {
          ...current.storyboard,
          public_share_enabled: next.enabled,
          public_share_slug: next.slug,
          permissions: next.permissions,
        },
      }
    })
  }

  // Generation now runs server-side in the background, so a freshly created or
  // directly-opened Storyboard can legitimately be `generating`. Poll until it
  // settles so the page resolves to the deck (or a failed state) on its own
  // rather than stranding the viewer on the static "generating" panel.
  const generatingId =
    state.kind === "ready" && state.storyboard.status === "generating"
      ? state.storyboard.id
      : null
  useEffect(() => {
    if (!generatingId) return
    let cancelled = false
    const timer = window.setInterval(() => {
      getStoryboard(generatingId)
        .then((storyboard) => {
          if (!cancelled) setState({ kind: "ready", storyboard })
        })
        .catch(() => {
          /* transient read error: keep the last known state and retry */
        })
    }, 2500)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [generatingId])

  useEffect(() => {
    document.title =
      state.kind === "ready"
        ? `${state.storyboard.title} — SpecForge Storyboard`
        : "Storyboard — SpecForge"
    return () => {
      document.title = "SpecForge"
    }
  }, [state])

  if (state.kind === "loading") {
    return (
      <main className="storyboard-page storyboard-page--deck" aria-busy="true">
        <StoryboardDeck isLoading title="Storyboard" />
      </main>
    )
  }

  if (state.kind === "not_found") {
    return (
      <main className="storyboard-page storyboard-page--deck">
        <StoryboardDeck isNotFound title="Storyboard" />
        <Link to="/dashboard">Back to dashboard</Link>
      </main>
    )
  }

  if (state.kind === "error") {
    return (
      <main className="storyboard-page storyboard-page--deck" role="alert">
        <StoryboardDeck title="Storyboard" errorMessage={state.message} />
        <Link to="/dashboard">Back to dashboard</Link>
      </main>
    )
  }

  const { storyboard } = state
  const isPresentable = storyboard.status === "ready" || storyboard.status === "stale"
  return (
    <main className="storyboard-page storyboard-page--deck">
      <header className="storyboard-page__header">
        <p className="storyboard-page__meta">
          Version {storyboard.version} · <span>{storyboard.status}</span>
        </p>
        <Link to={`/workspace/${storyboard.workspace_id}`}>Back to workspace</Link>
      </header>
      {view === "deck" ? (
        <StoryboardDeck
          payload={storyboard.content}
          status={storyboard.status}
          title={storyboard.title}
          isOwner={true}
          allowPresenterMode={true}
          allowSourceLayer={true}
          sharePermissions={storyboard.permissions}
          onExit={() => setView("launch")}
        />
      ) : (
        <>
          <StoryboardLaunchPage
            title={storyboard.title}
            payload={storyboard.content}
            isOwner={true}
            permissions={storyboard.permissions}
            onPresent={() => {
              if (isPresentable) setView("deck")
            }}
            onDownload={() => setShowDownloads((value) => !value)}
            onNotes={() => setShowNotes((value) => !value)}
            onShare={() => setShowShareModal(true)}
          />
          {showDownloads && (
            <StoryboardDownloadMenu
              mode="owner"
              title={storyboard.title}
              storyboardId={storyboard.id}
              permissions={storyboard.permissions}
              onClose={() => setShowDownloads(false)}
            />
          )}
          {showNotes && (
            <PresenterMode
              payload={storyboard.content}
              isOwner={true}
              permissions={storyboard.permissions}
              onClose={() => setShowNotes(false)}
            />
          )}
        </>
      )}

      {showShareModal && (
        <StoryboardShareModal
          storyboardId={storyboard.id}
          initialEnabled={storyboard.public_share_enabled}
          initialSlug={storyboard.public_share_slug}
          initialPermissions={storyboard.permissions}
          onClose={() => setShowShareModal(false)}
          onShareChanged={updateShareState}
        />
      )}
    </main>
  )
}
