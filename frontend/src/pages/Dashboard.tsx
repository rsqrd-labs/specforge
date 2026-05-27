import { Fragment, useEffect, useRef, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { ErrorBoundary } from "../components/ErrorBoundary"
import { GitHubStatusPill } from "../components/shared/GitHubStatusPill"
import { CreditMeter } from "../components/shared/CreditMeter"
import { CreateWorkspaceModal } from "../components/dashboard/CreateWorkspaceModal"
import { DeleteWorkspaceModal } from "../components/dashboard/DeleteWorkspaceModal"
import { WorkspaceCard } from "../components/dashboard/WorkspaceCard"
import { TemplatesStrip } from "../components/templates/TemplatesStrip"
import { STARTER_WORKSPACES } from "../config/starterWorkspaces"
import {
  fetchBillingHistory,
  getApiErrorMessage,
  getCredits,
  logout,
} from "../services/api"
import { useUserStore } from "../store/userStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { StripeCreditPack } from "../types/billing"
import type { Stage, StageStatus } from "../types/stage"
import type { Template } from "../types/template"
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
type PipelineStageId = "spec" | "plan" | "harness" | "tasks"

const PIPELINE_STAGE_DETAILS: Record<
  PipelineStageId,
  {
    number: string
    name: string
    description: string
    kicker: string
    copy: string
    points: string[]
  }
> = {
  spec: {
    number: "01",
    name: "Spec",
    description: "Turn the spark into crisp requirements and decisions",
    kicker: "What is a spec?",
    copy:
      "A spec is the product blueprint: what you are building, who it is for, how it should behave, and which tradeoffs matter before code starts moving.",
    points: ["Requirements", "Constraints", "Decisions"],
  },
  plan: {
    number: "02",
    name: "Plan",
    description: "Map the work before the work starts drifting",
    kicker: "What is a plan?",
    copy:
      "A plan turns the spec into an implementation route: the sequence of work, dependencies, risks, and checkpoints that keep the build from becoming guesswork.",
    points: ["Milestones", "Dependencies", "Risks"],
  },
  harness: {
    number: "03",
    name: "Harness",
    description: "Lock in proof that every promise is covered",
    kicker: "What is a harness?",
    copy:
      "A harness is the test scaffold for the product promise. It captures the behaviors the system must prove, so quality is designed into the workflow instead of inspected at the end.",
    points: ["Contracts", "Coverage", "Regression checks"],
  },
  tasks: {
    number: "04",
    name: "Tasks",
    description: "Hand engineers and agents a build list they can act on",
    kicker: "What are tasks?",
    copy:
      "Tasks break the plan into concrete implementation steps with enough context for engineers or agents to pick up the next move and keep shipping.",
    points: ["Action items", "Owners", "Next steps"],
  },
}

const PIPELINE_STAGE_ORDER: PipelineStageId[] = ["spec", "plan", "harness", "tasks"]
const STAGE_LABELS: Record<PipelineStageId, string> = {
  spec: "Spec",
  plan: "Plan",
  harness: "Harness",
  tasks: "Tasks",
}

const ACTIVE_STAGE_STATUSES: StageStatus[] = ["draft", "in_progress", "stale"]

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

function progressForWorkspace(workspace: WorkspaceWithStages): number {
  const finalised = workspace.stages?.filter((stage) => stage.status === "finalised").length ?? 0
  return Math.round((finalised / PIPELINE_STAGE_ORDER.length) * 100)
}

function nextStageForWorkspace(workspace: WorkspaceWithStages): Stage | null {
  const stageMap = Object.fromEntries(workspace.stages.map((stage) => [stage.type, stage]))
  const activeStage = PIPELINE_STAGE_ORDER
    .map((stageId) => stageMap[stageId])
    .find((stage): stage is Stage =>
      Boolean(stage && ACTIVE_STAGE_STATUSES.includes(stage.status)),
    )

  if (activeStage) return activeStage

  return PIPELINE_STAGE_ORDER
    .map((stageId) => stageMap[stageId])
    .find((stage): stage is Stage => Boolean(stage)) ?? null
}

function nextActionForStage(stage: Stage | null): string {
  if (!stage) return "Open Workspace"
  const stageName = STAGE_LABELS[stage.type]
  if (stage.type === "tasks" && stage.status === "finalised") return "Review Export"
  if (stage.status === "stale") return `Refresh ${stageName}`
  if (stage.status === "in_progress") return `Resume ${stageName}`
  if (stage.status === "finalised") return `Review ${stageName}`
  return `Continue ${stageName}`
}

function statusTextForStage(stage: Stage | null): string {
  if (!stage) return "Workspace ready"
  if (stage.type === "tasks" && stage.status === "finalised") return "Ready to export"
  if (stage.status === "stale") return `${STAGE_LABELS[stage.type]} needs refresh`
  if (stage.status === "in_progress") return `${STAGE_LABELS[stage.type]} in progress`
  if (stage.status === "draft") return `${STAGE_LABELS[stage.type]} waiting`
  if (stage.status === "locked") return `${STAGE_LABELS[stage.type]} locked`
  return `${STAGE_LABELS[stage.type]} complete`
}

function formatUpdatedDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
  }).format(new Date(value))
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

/**
 * Fallback rendered by ErrorBoundary when TemplatesStrip throws.
 * A malformed /api/templates response or network error during render must
 * not crash the entire Dashboard — it should degrade to this inline message.
 * MF-4 — T-208.
 */
function TemplatesErrorFallback() {
  return (
    <div className="templates-error-fallback" role="alert" aria-live="polite">
      <span className="templates-error-message">
        Templates unavailable — reload to retry.
      </span>
      <button
        type="button"
        className="templates-error-reload"
        onClick={() => window.location.reload()}
      >
        Reload
      </button>
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { workspaces, isLoading, fetchWorkspaces, deleteWorkspace } = useWorkspaceStore()
  const user = useUserStore((state) => state.user)
  const clearUser = useUserStore((state) => state.clearUser)
  const [balance, setBalance] = useState<number | null>(null)
  const [generationCost, setGenerationCost] = useState<number>(10)
  const [billingPacks, setBillingPacks] = useState<StripeCreditPack[]>([])
  const [showCreate, setShowCreate] = useState(false)
  const [starterWorkspace, setStarterWorkspace] = useState<
    (typeof STARTER_WORKSPACES)[number] | null
  >(null)
  const [pickedTemplate, setPickedTemplate] = useState<Template | null>(null)
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [workspaceToDelete, setWorkspaceToDelete] = useState<Workspace | null>(null)
  const [deletingWorkspaceId, setDeletingWorkspaceId] = useState<string | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [activePipelineInfo, setActivePipelineInfo] = useState<PipelineStageId | null>(null)

  useEffect(() => {
    void fetchWorkspaces()
    getCredits()
      .then((d) => {
        setBalance(d.balance)
        setGenerationCost(d.generation_cost)
      })
      .catch(() => setBalance(null))
    fetchBillingHistory()
      .then(setBillingPacks)
      .catch(() => setBillingPacks([]))
  }, [fetchWorkspaces])

  useEffect(() => {
    if (!activePipelineInfo) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setActivePipelineInfo(null)
      }
    }
    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [activePipelineInfo])

  const animatedBalance = useCountUp(balance)
  const userDisplayName = user ? displayName(user) : null
  const firstName = user ? firstDisplayName(user) : null
  const initials = user ? initialsFor(user) : "?"
  const isLow = balance !== null && balance <= 10
  const typedWorkspaces = workspaces as WorkspaceWithStages[]

  const totalDone = typedWorkspaces.reduce(
    (n, ws) => n + (ws.stages?.filter((s) => s.status === "finalised").length ?? 0),
    0,
  )
  const activeDrafts = typedWorkspaces.filter((ws) =>
    ws.stages?.some((stage) => ["draft", "in_progress", "stale"].includes(stage.status)),
  ).length
  const readyToExport = typedWorkspaces.filter((ws) =>
    ws.stages?.some((stage) => stage.type === "tasks" && stage.status === "finalised"),
  ).length
  const latestWorkspace = [...typedWorkspaces].sort(
    (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
  )[0]
  const latestStage = latestWorkspace ? nextStageForWorkspace(latestWorkspace) : null
  const latestProgress = latestWorkspace ? progressForWorkspace(latestWorkspace) : 0
  const fillPct = balance !== null ? Math.min((balance / CREDIT_FULL) * 100, 100) : 0
  const activePipelineDetail = activePipelineInfo
    ? PIPELINE_STAGE_DETAILS[activePipelineInfo]
    : null

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

  function openCreateWorkspace(starter: (typeof STARTER_WORKSPACES)[number] | null = null) {
    setStarterWorkspace(starter)
    setShowCreate(true)
  }

  function openCreateWorkspaceFromTemplate(template: Template) {
    // T-USE-12: clicking a template card opens the modal pre-filled with the
    // template's name, problem_statement, and provider. The template_slug is
    // stamped on the workspace at submit time for provenance.
    setPickedTemplate(template)
    setStarterWorkspace(null)
    setShowCreate(true)
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
              <GitHubStatusPill />
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
            Shape a rough idea into a spec your team can trust, then carry it
            through plans, tests, and build-ready tasks without losing momentum.
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
            {isLow ? "A few focused runs left" : "Fuel for the next breakthrough"}
          </p>
          <div className="credit-card-meter">
            {balance !== null ? (
              <CreditMeter
                balance={balance}
                packs={billingPacks}
                variant="inverse"
              />
            ) : (
              <span>Checking your credits</span>
            )}
          </div>
          <div className="credit-card-bar-track">
            <div
              className="credit-card-bar-fill"
              style={{ width: `${fillPct}%` }}
            />
          </div>
          <Link to="/billing" className="credit-card-buy-link">
            Buy Credits →
          </Link>
        </div>
      </div>

      {latestWorkspace && (
        <section className="continue-panel" aria-labelledby="continue-title">
          <div className="continue-panel-main">
            <div className="continue-panel-kicker">Continue where you left off</div>
            <h2 id="continue-title" className="continue-panel-title">
              {latestWorkspace.name}
            </h2>
            <p className="continue-panel-copy">
              {statusTextForStage(latestStage)}. Last touched {formatUpdatedDate(latestWorkspace.updated_at)}.
            </p>
            <div className="continue-progress" aria-label={`${latestProgress}% complete`}>
              <div className="continue-progress-track">
                <div
                  className="continue-progress-fill"
                  style={{ width: `${latestProgress}%` }}
                />
              </div>
              <span>{latestProgress}% complete</span>
            </div>
          </div>

          <div className="continue-panel-meta">
            <div className="continue-stage-orbit" aria-hidden="true">
              <span>{latestStage ? STAGE_LABELS[latestStage.type][0] : "W"}</span>
            </div>
            <div className="continue-stage-label">
              <span>Current focus</span>
              <strong>{latestStage ? STAGE_LABELS[latestStage.type] : "Workspace"}</strong>
            </div>
            <button
              type="button"
              className="continue-button"
              onClick={() => navigate(`/workspace/${latestWorkspace.id}`)}
            >
              {nextActionForStage(latestStage)}
            </button>
          </div>
        </section>
      )}

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
        <span className="pipeline-strip-label">Your launch path</span>
        <div className="pipeline-stages">
          {PIPELINE_STAGE_ORDER.map((stageId, index) => {
            const stage = PIPELINE_STAGE_DETAILS[stageId]
            const isActive = activePipelineInfo === stageId

            return (
              <Fragment key={stageId}>
                {index > 0 && <div className="pipeline-arrow">→</div>}
                <div className="pipeline-stage-wrap">
                  <button
                    type="button"
                    className={`pipeline-stage pipeline-stage-button${isActive ? " active" : ""}`}
                    onClick={() =>
                      setActivePipelineInfo((active) =>
                        active === stageId ? null : stageId,
                      )
                    }
                    aria-expanded={isActive}
                    aria-controls="pipeline-stage-info"
                  >
                    <div className="pipeline-stage-num">{stage.number}</div>
                    <div className="pipeline-stage-name">{stage.name}</div>
                    <div className="pipeline-stage-desc">{stage.description}</div>
                  </button>
                </div>
              </Fragment>
            )
          })}
        </div>
        {activePipelineDetail && (
          <div
            id="pipeline-stage-info"
            role="status"
            className="spec-info-panel"
          >
            <div className="spec-info-beam" aria-hidden="true" />
            <div className="spec-info-icon" aria-hidden="true">
              {activePipelineDetail.number}
            </div>
            <div>
              <p className="spec-info-kicker">{activePipelineDetail.kicker}</p>
              <p className="spec-info-copy">
                {activePipelineDetail.copy}
              </p>
              <div className="spec-info-points">
                {activePipelineDetail.points.map((point) => (
                  <span key={point}>{point}</span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Workspace list */}
      <div className="ws-section">
        <div className="ws-section-header">
          <div className="ws-section-copy">
            <span className="ws-section-eyebrow">Workspace foundry</span>
            <h2 className="ws-section-title">
              Ideas in <span>Motion</span>
            </h2>
            <p className="ws-section-subtitle">
              {workspaces.length === 0
                ? "Start with a rough thought and turn it into a buildable brief."
                : "Keep the strongest threads moving from spark to shipped plan."}
            </p>
          </div>
          <div className="ws-section-actions">
            <div className="ws-section-pulse" aria-hidden="true">
              <span />
              <span />
              <span />
            </div>
            <div className="ws-section-mini-stats" aria-label="Workspace status summary">
              <span>{activeDrafts} active</span>
              <span>{readyToExport} ready</span>
            </div>
          </div>
          <button className="forge-button" onClick={() => openCreateWorkspace()}>
            <span className="forge-button-icon">+</span>
            Start a Workspace
          </button>
        </div>

        {isLoading ? (
          <div className="dashboard-loading">
            <div className="loading-ring" />
          </div>
        ) : workspaces.length === 0 ? (
          <div className="workspace-empty">
            <ErrorBoundary fallback={<TemplatesErrorFallback />}>
              <TemplatesStrip
                prominent
                onPick={openCreateWorkspaceFromTemplate}
              />
            </ErrorBoundary>
            <div className="workspace-empty-icon">⚡</div>
            <p className="workspace-empty-heading">Your first great brief starts here</p>
            <p className="workspace-empty-body">
              Bring the messy version of the idea. SpecForge will help you
              sharpen it into a path your team can actually build.
            </p>
            <div className="starter-grid" aria-label="Starter workspace ideas">
              {STARTER_WORKSPACES.map((starter) => (
                <button
                  type="button"
                  key={starter.name}
                  className="starter-card"
                  onClick={() => openCreateWorkspace(starter)}
                >
                  <strong>{starter.name}</strong>
                  <span>{starter.description}</span>
                </button>
              ))}
            </div>
            <button className="forge-button" onClick={() => openCreateWorkspace()}>
              <span className="forge-button-icon">+</span>
              Draft the first workspace
            </button>
          </div>
        ) : (
          <>
            <ErrorBoundary fallback={<TemplatesErrorFallback />}>
              <TemplatesStrip onPick={openCreateWorkspaceFromTemplate} />
            </ErrorBoundary>
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
          </>
        )}
      </div>

      {showCreate && (
        <CreateWorkspaceModal
          initialName={starterWorkspace?.name ?? pickedTemplate?.name}
          initialStatement={
            starterWorkspace?.statement ?? pickedTemplate?.problem_statement
          }
          initialTemplate={pickedTemplate}
          balance={balance}
          generationCost={generationCost}
          onClose={() => {
            setShowCreate(false)
            setStarterWorkspace(null)
            setPickedTemplate(null)
          }}
        />
      )}
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
