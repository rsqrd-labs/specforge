import axios from "axios"
import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { getApiErrorMessage, getStoryboard } from "../services/api"
import type { StoryboardDetail } from "../types/storyboard"

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

  useEffect(() => {
    if (!id) {
      setState({ kind: "not_found" })
      return
    }
    let cancelled = false
    setState({ kind: "loading" })
    getStoryboard(id)
      .then((storyboard) => {
        if (!cancelled) setState({ kind: "ready", storyboard })
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
      <main className="storyboard-page" aria-busy="true">
        <p>Loading Storyboard…</p>
      </main>
    )
  }

  if (state.kind === "not_found") {
    return (
      <main className="storyboard-page storyboard-page--empty">
        <h1>Storyboard not found</h1>
        <p>This Storyboard does not exist or is not available on your account.</p>
        <Link to="/dashboard">Back to dashboard</Link>
      </main>
    )
  }

  if (state.kind === "error") {
    return (
      <main className="storyboard-page storyboard-page--error" role="alert">
        <h1>Could not load Storyboard</h1>
        <p>{state.message}</p>
        <Link to="/dashboard">Back to dashboard</Link>
      </main>
    )
  }

  const { storyboard } = state
  return (
    <main className="storyboard-page">
      <header className="storyboard-page__header">
        <h1>{storyboard.title}</h1>
        <p className="storyboard-page__meta">
          Version {storyboard.version} · <span>{storyboard.status}</span>
        </p>
      </header>
      <Link to={`/workspace/${storyboard.workspace_id}`}>Back to workspace</Link>
    </main>
  )
}
