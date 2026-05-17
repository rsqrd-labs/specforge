import { useEffect, useRef, useState } from "react"
import { useNavigate } from "react-router-dom"
import { CreateWorkspaceModal } from "../components/dashboard/CreateWorkspaceModal"
import { DeleteWorkspaceModal } from "../components/dashboard/DeleteWorkspaceModal"
import { WorkspaceCard } from "../components/dashboard/WorkspaceCard"
import { getApiErrorMessage, getCredits, logout } from "../services/api"
import { useUserStore } from "../store/userStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { Workspace, WorkspaceWithStages } from "../types/workspace"

function useCountUp(target: number | null, duration = 950) {
  const [value, setValue] = useState(0)
  const frameRef = useRef<number>(0)

  useEffect(() => {
    if (target === null) return
    const startTime = performance.now()
    const animate = (now: number) => {
      const progress = Math.min((now - startTime) / duration, 1)
      const ease = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(target * ease))
      if (progress < 1) frameRef.current = requestAnimationFrame(animate)
    }
    frameRef.current = requestAnimationFrame(animate)
    return () => cancelAnimationFrame(frameRef.current)
  }, [target, duration])

  return value
}

function greeting() {
  const h = new Date().getHours()
  if (h < 12) return "Good morning"
  if (h < 17) return "Good afternoon"
  return "Good evening"
}

const CREDIT_FULL = 100

function emailName(email: string): string {
  const localPart = email.split("@")[0] ?? email
  return localPart
    .replace(/[._-]+/g, " ")
    .trim()
}

function displayName(user: { name: string | null; email: string }): string {
  return user.name?.trim() || emailName(user.email) || user.email
}

function firstDisplayName(user: { name: string | null; email: string }): string {
  return displayName(user).split(/\s+/)[0] ?? "there"
}

function initialsFor(user: { name: string | null; email: string }): string {
  const parts = displayName(user)
    .split(/\s+/)
    .map((part) => part[0])
    .filter((part): part is string => Boolean(part))

  const fallback = user.email.match(/[a-zA-Z0-9]/g)?.slice(0, 2).join("") ?? "SF"
  return (parts.length > 1 ? `${parts[0]}${parts[1]}` : parts[0] ?? fallback).toUpperCase()
}

function UserAvatar({
  avatarUrl,
  initials,
}: {
  avatarUrl: string | null
  initials: string
}) {
  const [imageFailed, setImageFailed] = useState(false)
  const cleanAvatarUrl = avatarUrl?.trim() || null

  if (cleanAvatarUrl && !imageFailed) {
    return (
      <img
        src={cleanAvatarUrl}
        alt=""
        className="user-avatar-img"
        referrerPolicy="no-referrer"
        onError={() => setImageFailed(true)}
      />
    )
  }

  return <div className="user-avatar-fallback">{initials}</div>
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { workspaces, isLoading, fetchWorkspaces, deleteWorkspace } = useWorkspaceStore()
  const user = useUserStore((state) => state.user)
  const clearUser = useUserStore((state) => state.clearUser)
  const [balance, setBalance] = useState<number | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [workspaceToDelete, setWorkspaceToDelete] = useState<Workspace | null>(null)
  const [deletingWorkspaceId, setDeletingWorkspaceId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  useEffect(() => {
    void fetchWorkspaces()
    getCredits()
      .then((d) => setBalance(d.balance))
      .catch(() => setBalance(null))
  }, [fetchWorkspaces])

  const animatedBalance = useCountUp(balance)
  const userDisplayName = user ? displayName(user) : null
  const firstName = user ? firstDisplayName(user) : null
  const initials = user ? initialsFor(user) : "?"
  const isLow = balance !== null && balance <= 10

  const totalDone = (workspaces as WorkspaceWithStages[]).reduce(
    (n, ws) => n + (ws.stages?.filter((s) => s.status === "finalised").length ?? 0),
    0,
  )
  const fillPct = balance !== null ? Math.min((balance / CREDIT_FULL) * 100, 100) : 0

  async function handleLogout() {
    if (isLoggingOut) return
    setIsLoggingOut(true)
    try {
      await logout()
    } catch {
      // Local auth state still needs to be cleared if the server session is gone.
    } finally {
      clearUser()
      navigate("/", { replace: true })
    }
  }

  async function handleConfirmDelete() {
    if (!workspaceToDelete || deletingWorkspaceId) return
    setDeletingWorkspaceId(workspaceToDelete.id)
    setDeleteError(null)
    try {
      await deleteWorkspace(workspaceToDelete.id)
      setWorkspaceToDelete(null)
    } catch (error) {
      setDeleteError(
        getApiErrorMessage(error, "Failed to delete workspace. Please try again."),
      )
    } finally {
      setDeletingWorkspaceId(null)
    }
  }

  return (
    <div className="dashboard-shell">
      <div className="ambient-field" aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
        <div className="ambient-band band-slate" />
      </div>

      {/* Nav */}
      <nav className="dashboard-nav">
        <div className="dashboard-nav-inner">
          <div className="flex items-center gap-3">
            <span className="brand-mark brand-mark-sm">
              <span>SF</span>
            </span>
            <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
          </div>
          {user && (
            <div className="dashboard-user-actions">
              <div className="user-nav-pill">
                <UserAvatar avatarUrl={user.avatar_url} initials={initials} />
                <span className="user-name hidden sm:block" title={userDisplayName ?? undefined}>
                  {userDisplayName}
                </span>
              </div>
              <button
                type="button"
                className="logout-button"
                onClick={() => void handleLogout()}
                disabled={isLoggingOut}
                aria-label="Sign out"
              >
                <span className="logout-button-icon" aria-hidden="true">
                  <svg viewBox="0 0 20 20" focusable="false">
                    <path d="M8.4 3.2H5.7c-.9 0-1.6.7-1.6 1.6v10.4c0 .9.7 1.6 1.6 1.6h2.7" />
                    <path d="M11.7 6.2 15.5 10l-3.8 3.8" />
                    <path d="M15.1 10H7.8" />
                  </svg>
                </span>
                <span>{isLoggingOut ? "Signing out" : "Sign out"}</span>
              </button>
            </div>
          )}
        </div>
      </nav>

      {/* Hero */}
      <div className="dashboard-hero">
        <div className="dashboard-hero-copy">
          <span className="greeting-tag">✦ {greeting()}</span>
          <h1 className="dashboard-title">
            {firstName ? (
              <>
                Welcome back,
                <br />
                {firstName}.
              </>
            ) : (
              "Your Workspaces"
            )}
          </h1>
          <p className="dashboard-subtitle">
            Turn ideas into engineering specs with a four-stage AI pipeline.
            Each generation brings you closer to shipping.
          </p>
        </div>

        {/* Credit card */}
        <div className={`credit-card${isLow ? " low" : ""}`}>
          <div className="credit-card-orb credit-card-orb-1" />
          <div className="credit-card-orb credit-card-orb-2" />
          <p className="credit-card-label">Credits Available</p>
          <p className="credit-card-value">
            {balance !== null ? animatedBalance : "—"}
          </p>
          <p className="credit-card-sub">
            {isLow ? "Running low — top up soon" : "Ready to forge"}
          </p>
          <div className="credit-card-bar-track">
            <div
              className="credit-card-bar-fill"
              style={{ width: `${fillPct}%` }}
            />
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="stats-strip">
        <div className="stat-chip">
          <span className="stat-chip-icon">🗂</span>
          <div>
            <div className="stat-chip-value">{workspaces.length}</div>
            <div className="stat-chip-label">Workspaces</div>
          </div>
        </div>
        <div className="stat-chip">
          <span className="stat-chip-icon">✅</span>
          <div>
            <div className="stat-chip-value">{totalDone}</div>
            <div className="stat-chip-label">Stages Complete</div>
          </div>
        </div>
        <div className="stat-chip">
          <span className="stat-chip-icon">⚡</span>
          <div>
            <div className="stat-chip-value">4</div>
            <div className="stat-chip-label">Pipeline Stages</div>
          </div>
        </div>
      </div>

      {/* Pipeline overview */}
      <div className="pipeline-strip">
        <span className="pipeline-strip-label">How it works</span>
        <div className="pipeline-stages">
          <div className="pipeline-stage">
            <div className="pipeline-stage-num">01</div>
            <div className="pipeline-stage-name">Spec</div>
            <div className="pipeline-stage-desc">Functional requirements, constraints, and architecture decisions</div>
          </div>
          <div className="pipeline-arrow">→</div>
          <div className="pipeline-stage">
            <div className="pipeline-stage-num">02</div>
            <div className="pipeline-stage-name">Plan</div>
            <div className="pipeline-stage-desc">Implementation blueprint with a full traceability matrix</div>
          </div>
          <div className="pipeline-arrow">→</div>
          <div className="pipeline-stage">
            <div className="pipeline-stage-num">03</div>
            <div className="pipeline-stage-name">Harness</div>
            <div className="pipeline-stage-desc">Contract test suite that covers every requirement</div>
          </div>
          <div className="pipeline-arrow">→</div>
          <div className="pipeline-stage">
            <div className="pipeline-stage-num">04</div>
            <div className="pipeline-stage-name">Tasks</div>
            <div className="pipeline-stage-desc">Granular implementation playbook for agents and engineers</div>
          </div>
        </div>
      </div>

      {/* Workspace list */}
      <div className="ws-section">
        <div className="ws-section-header">
          <h2 className="ws-section-title">Your Workspaces</h2>
          <button className="forge-button" onClick={() => setShowCreate(true)}>
            <span className="forge-button-icon">+</span>
            New Workspace
          </button>
        </div>

        {isLoading ? (
          <div className="dashboard-loading">
            <div className="loading-ring" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="workspace-empty">
            <div className="workspace-empty-icon">⚡</div>
            <p className="workspace-empty-heading">No workspaces yet</p>
            <p className="workspace-empty-body">
              Create one to start building your spec pipeline.
            </p>
            <button className="forge-button" onClick={() => setShowCreate(true)}>
              <span className="forge-button-icon">+</span>
              Create your first workspace
            </button>
          </div>
        ) : (
          <div className="workspace-grid">
            {workspaces.map((ws, i) => (
              <WorkspaceCard
                key={ws.id}
                workspace={ws}
                index={i}
                isDeleting={deletingWorkspaceId === ws.id}
                onDelete={(workspace) => {
                  setDeleteError(null)
                  setWorkspaceToDelete(workspace)
                }}
              />
            ))}
          </div>
        )}
      </div>

      {showCreate && <CreateWorkspaceModal onClose={() => setShowCreate(false)} />}
      {workspaceToDelete && (
        <DeleteWorkspaceModal
          workspace={workspaceToDelete}
          error={deleteError}
          isDeleting={deletingWorkspaceId === workspaceToDelete.id}
          onCancel={() => {
            if (deletingWorkspaceId) return
            setWorkspaceToDelete(null)
            setDeleteError(null)
          }}
          onConfirm={() => void handleConfirmDelete()}
        />
      )}
    </div>
  )
}
