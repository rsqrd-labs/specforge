import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { CoveragePanel } from "../components/workspace/CoveragePanel"
import { ConstructionVerifiedBadge } from "../components/workspace/ConstructionVerifiedBadge"
import { DemoDayHandoffPanel } from "../components/workspace/DemoDayHandoffPanel"
import {
  CreateStoryboardModal,
  canCreateStoryboardFromStages,
} from "../components/workspace/CreateStoryboardModal"
import { CreditConfirmModal, CREDIT_COSTS } from "../components/workspace/CreditConfirmModal"
import {
  BlockedPartialBadge,
  BlockedPartialNotice,
} from "../components/workspace/BlockedPartialBanner"
import { DiffViewer } from "../components/workspace/DiffViewer"
import { GenerateBar } from "../components/workspace/GenerateBar"
import { HumanReviewGate } from "../components/workspace/HumanReviewGate"
import {
  QualityBadge,
  QUALITY_STATUS_LABEL,
  deriveQualityStatus,
} from "../components/workspace/QualityBadge"
import { StageEditor, type StageEditorHandle } from "../components/workspace/StageEditor"
import { StageNavigator } from "../components/workspace/StageNavigator"
import { StalenessWarning } from "../components/workspace/StalenessWarning"
import {
  StreamingOverlay,
  type GenerationActivityInfo,
  type GenerationActivityOperation,
} from "../components/workspace/StreamingOverlay"
import { MarkdownRenderer } from "../components/workspace/MarkdownRenderer"
import { StageEmptyState } from "../components/workspace/StageEmptyState"
import { StageEditAction } from "../components/workspace/StageEditAction"
import { TasksBoard } from "../components/workspace/TasksBoard"
import { ProblemStatementPanel } from "../components/workspace/ProblemStatementPanel"
import { ResearchConsentToggle } from "../components/workspace/ResearchConsentToggle"
import { TaskValidationPanel } from "../components/workspace/TaskValidationPanel"
import { TaskCompletionPanel } from "../components/workspace/TaskCompletionPanel"
import { VersionHistoryPanel } from "../components/workspace/VersionHistoryPanel"
import { IncrementTimeline } from "../components/workspace/IncrementTimeline"
import { ExportGitHubModal } from "../components/workspace/ExportGitHubModal"
import {
  useActionAlert,
  type ActionAlertAction,
} from "../components/shared/ActionAlert"
import { useGitHubSync } from "../hooks/useGitHubSync"
// ExportPDFButton — T-USE-08 contract; PDF export logic is inlined in handlePdfExport
import type { } from "../components/workspace/ExportPDFButton"
import { HarnessCoverageChip } from "../components/workspace/HarnessCoverageChip"
import { SharePublicLinkModal } from "../components/workspace/SharePublicLinkModal"
import { SpecClarificationModal } from "../components/workspace/SpecClarificationModal"
import { StoryboardToolbar } from "../components/workspace/StoryboardToolbar"
import { AiDisclaimer } from "../components/shared/AiDisclaimer"
import { BrandLoader } from "../components/shared/BrandLoader"
import { BrandLockup } from "../components/shared/BrandLogo"
import { DownloadIcon, GitHubIcon, PDFIcon, ShareIcon } from "../components/shared/icons"
import { useCredits } from "../hooks/useCredits"
import {
  formatEffortSummaryChip,
  parseEffortSummary,
  parseTaskBlocks,
} from "../utils/tasksParser"
import { useReconnectPoll } from "../hooks/useReconnectPoll"
import { useStream } from "../hooks/useStream"
import {
  acceptStageDiff,
  acknowledgeReviewGate,
  acknowledgeStaleStage,
  exportWorkspace,
  exportWorkspacePdf,
  finaliseStage,
  generateStoryboard,
  getStageEval,
  getApiErrorMessage,
  getGitHubInstallations,
  getGitHubIntegration,
  getLatestStoryboard,
  getStoryboard,

  getWorkspace,
  overrideQualityGate,
  refineStage,
  regenerateStoryboard,
  rejectStageDiff,
  revalidateTasks,
  rollbackStage,
  shareStoryboard,
  updateWorkspace,
  updateStageContent,
  downloadStoryboard,
  downloadAgentInstructions,
  type ClarifyAnswer,
} from "../services/api"
import { useStageStore } from "../store/stageStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { EvalResult, RefineResponse, Stage, StageType } from "../types/stage"
import type { StoryboardDetail, StoryboardDownloadKind } from "../types/storyboard"
import type { TargetAgent } from "../types/workspace"
import {
  actionAlertFromMessage,
  actionAlertFromStreamError,
} from "../utils/errorPresentation"
import {
  deriveAdvisoryFindings,
  deriveFinaliseGateBlock,
  deriveJudgeReconciliationNote,
} from "../utils/qualityGate"
import { pollForFreshVerdict } from "../utils/constructionVerdict"
import { AdvisoryFindingsPanel } from "../components/workspace/AdvisoryFindingsPanel"
import { featureFlags } from "../config/featureFlags"

const STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

const STAGE_LABELS: Record<StageType, string> = {
  spec: "SPEC",
  plan: "PLAN",
  harness: "HARNESS",
  tasks: "TASKS",
}

const EVAL_POLL_ATTEMPTS = 12
const EVAL_POLL_DELAY_MS = 2500
// Generation runs in a background task on the server (the request returns the
// 'generating' placeholder immediately), so the client polls the owner-detail
// endpoint until it settles. The window comfortably outlasts a full keynote
// generation (LLM call plus up to two repair rounds); if it lapses, the toolbar
// still shows 'generating' and reopening the workspace resumes polling, and the
// server-side recovery loop is the ultimate backstop.
const STORYBOARD_POLL_ATTEMPTS = 150
const STORYBOARD_POLL_DELAY_MS = 2500

const REFINE_MODE_OPTIONS = [
  {
    mode: "focused",
    label: "Focused",
    submitLabel: "Refine",
    detail: "Smallest safe edit",
  },
  {
    mode: "section",
    label: "Section",
    submitLabel: "Rewrite",
    detail: "Broader local pass",
  },
  {
    mode: "full",
    label: "Full",
    submitLabel: "Regenerate",
    detail: "Deliberate replacement",
  },
] as const

type GenerationCreditAction = "generate" | "regenerate"
type CreditAction = GenerationCreditAction | "patch"
type StoryboardAction = "generate" | "regenerate" | "share" | "download" | "notes"

interface StoryboardFlowMessage {
  kind: "info" | "success" | "error"
  text: string
}

interface PendingCreditAction {
  action: CreditAction
  stageId: string
}

interface PendingReviewAction {
  action: GenerationCreditAction
  stageId: string
}

interface PendingClarifyAction extends PendingReviewAction {
  mode: "new" | "existing"
}

function getGenerationActionLabel(operation: GenerationActivityOperation) {
  switch (operation) {
    case "focused-patch":
      return "Preparing refinement"
    case "quality-gate-regenerate":
      return "Regenerating with gate feedback"
    case "regenerate-gaps":
      return "Regenerating coverage gaps"
    case "regenerate":
      return "Regenerating stage"
    case "generate":
    default:
      return "Generating stage"
  }
}

/**
 * Map the persisted `stages.generation_action` (backend "generate"/"regenerate")
 * to the overlay operation for a reconnect after refresh, so a regenerate shows
 * the right copy instead of always "generate" (A6). Unknown/NULL → "generate".
 */
function reconnectOperation(
  action: string | null | undefined,
): GenerationActivityOperation {
  return action === "regenerate" ? "regenerate" : "generate"
}

const sleep = (ms: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, ms))

function storyboardFileStem(title: string, id: string): string {
  return (
    title
      .toLowerCase()
      .replace(/[^a-z0-9-]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || `storyboard-${id}`
  )
}

function storyboardFilename(
  storyboard: StoryboardDetail,
  kind: StoryboardDownloadKind,
): string {
  const extensionByKind: Record<StoryboardDownloadKind, string> = {
    html: "html",
    pdf: "pdf",
    notes: "md",
    "demo-script": "md",
    appendix: "md",
  }
  return `specforge-${storyboardFileStem(storyboard.title, storyboard.id)}-${kind}.${extensionByKind[kind]}`
}

function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = filename
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1_500)
}

function firstUnlockedStage(stages: Stage[]): Stage | null {
  return (
    STAGE_ORDER.map((type) => stages.find((stage) => stage.type === type)).find(
      (stage) => stage && stage.status !== "locked",
    ) ?? null
  )
}

/**
 * Which stage to select on a (re)load of the workspace.
 *
 * Keeps the user's current selection if it still exists. Otherwise — a fresh
 * mount, e.g. a page refresh while a stage is still generating server-side —
 * prefers the in-progress stage so its reconnect overlay is visible, instead of
 * defaulting to the first unlocked stage. Without this, a user who refreshed
 * mid-PLAN would land on SPEC and see no sign that PLAN is still running
 * (docs/REFRESH_DURING_GENERATION_PLAN.md). Falls back to the first unlocked
 * stage when nothing is generating.
 */
export function pickActiveStageOnLoad(
  stages: Stage[],
  existing: string | null,
): string | null {
  if (existing && stages.some((stage) => stage.id === existing)) {
    return existing
  }
  const generating = stages.find((stage) => stage.status === "in_progress")
  return generating?.id ?? firstUnlockedStage(stages)?.id ?? null
}

function sortStages(stages: Stage[]): Stage[] {
  return [...stages].sort(
    (a, b) => STAGE_ORDER.indexOf(a.type) - STAGE_ORDER.indexOf(b.type),
  )
}

function previousStageType(type: StageType): StageType {
  const index = STAGE_ORDER.indexOf(type)
  return STAGE_ORDER[Math.max(0, index - 1)]
}

function formatStageStatus(status: Stage["status"]): string {
  return status.replace("_", " ")
}

interface WorkspaceGenerationLock {
  locked: boolean
  /** Short headline of what is running, e.g. "Generating HARNESS". */
  message: string
  /** Muted supporting line explaining the read-only state to the user. */
  detail: string
  reason: string
  busyLabel: string
  stageLabel: string | null
}

function getWorkspaceGenerationVerb(
  operation: GenerationActivityOperation | null,
): string {
  if (operation === "focused-patch") return "Refining"
  if (
    operation === "regenerate" ||
    operation === "regenerate-gaps" ||
    operation === "quality-gate-regenerate"
  ) {
    return "Regenerating"
  }
  return "Generating"
}

function getWorkspaceGenerationLock(
  locked: boolean,
  stage: Stage | null,
  operation: GenerationActivityOperation | null,
): WorkspaceGenerationLock {
  const reason = "Editing resumes when generation finishes."
  if (!locked) {
    return {
      locked: false,
      message: "",
      detail: "",
      reason,
      busyLabel: "",
      stageLabel: null,
    }
  }

  const stageLabel = stage ? STAGE_LABELS[stage.type] : "workspace"
  const verb = getWorkspaceGenerationVerb(operation)
  return {
    locked: true,
    message: `${verb} ${stageLabel}`,
    detail: "Editing is locked to keep this draft consistent — you can keep reading.",
    reason,
    busyLabel: `${verb} ${stageLabel}. Editing paused.`,
    stageLabel,
  }
}

function useAnimatedNumber(value: number | null, duration = 750) {
  const [displayValue, setDisplayValue] = useState(value ?? 0)
  const previousValue = useRef(value ?? 0)

  useEffect(() => {
    if (value === null) return

    const from = previousValue.current
    const to = value
    const startedAt = performance.now()
    let frame = 0

    function tick(now: number) {
      const progress = Math.min((now - startedAt) / duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      setDisplayValue(Math.round(from + (to - from) * eased))

      if (progress < 1) {
        frame = requestAnimationFrame(tick)
      } else {
        previousValue.current = to
      }
    }

    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [value, duration])

  return displayValue
}

export default function Workspace() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const editorRef = useRef<StageEditorHandle>(null)
  const exportMenuRef = useRef<HTMLDivElement>(null)
  const storyboardAutoOpenRef = useRef<string | null>(null)
  const storyboardActionInFlightRef = useRef(false)
  const storyboardLoadRequestRef = useRef(0)
  const storyboardLoadingRequestRef = useRef(0)
  const lastGenerationActionRef = useRef<"generate" | "regenerate" | "regenerate-gaps">(
    "generate",
  )
  const { showAlert, dismissAlert } = useActionAlert()
  const { currentWorkspace, isLoading, fetchWorkspace, setCurrentWorkspace } =
    useWorkspaceStore()
  const { stages: stageMap, setStage, setStages } = useStageStore()
  const qualityGateMap = useStageStore((s) => s.qualityGate)
  const setQualityGate = useStageStore((s) => s.setQualityGate)
  const clearQualityGate = useStageStore((s) => s.clearQualityGate)
  const streamProgressMap = useStageStore((s) => s.streamProgress)
  const { balance } = useCredits()
  const animatedBalance = useAnimatedNumber(balance)

  const [activeStageId, setActiveStageId] = useState<string | null>(null)
  const [pendingCredit, setPendingCredit] = useState<PendingCreditAction | null>(
    null,
  )
  const [pendingReview, setPendingReview] = useState<PendingReviewAction | null>(
    null,
  )
  const [refineInstruction, setRefineInstruction] = useState("")
  const [refineMode, setRefineMode] = useState<"focused" | "section" | "full">(
    "focused",
  )
  const [isRefining, setIsRefining] = useState(false)
  const refineInFlightRef = useRef(false)
  const finaliseInFlightRef = useRef(false)
  const [showRefineInput, setShowRefineInput] = useState(false)
  const [selection, setSelection] = useState<{
    start: number
    end: number
    text: string
  } | null>(null)
  const [diffResult, setDiffResult] = useState<RefineResponse | null>(null)
  const [largeSelectionWarning, setLargeSelectionWarning] = useState(false)
  const [evalResults, setEvalResults] = useState<Record<string, EvalResult | null>>(
    {},
  )
  /** Stages whose eval validation could not complete. When true, QualityBadge
   *  renders the quiet, non-blocking "Unavailable" status (issue #27 Phase 1;
   *  originally M-5 — T-187).
   */
  const [evalError, setEvalError] = useState<Record<string, boolean>>({})
  const setGenericError = useCallback(
    (message: string, title = "Action could not finish") => {
      showAlert(
        actionAlertFromMessage({
          title,
          message,
          recovery:
            "Your workspace is safe. Try the action again, or refresh if the problem continues.",
          source: "Workspace",
        }),
      )
    },
    [showAlert],
  )
  const [showRefineHint, setShowRefineHint] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [isMobileNavOpen, setIsMobileNavOpen] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [specViewMode, setSpecViewMode] = useState<"preview" | "edit">("preview")
  const [problemDraft, setProblemDraft] = useState("")
  const [problemDirty, setProblemDirty] = useState(false)
  const [isGitHubConnected, setIsGitHubConnected] = useState(false)
  const [showGitHubExport, setShowGitHubExport] = useState(false)
  const [showShareModal, setShowShareModal] = useState(false)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [isPdfExporting, setIsPdfExporting] = useState(false)
  const [agentDownloadTarget, setAgentDownloadTarget] = useState<TargetAgent | null>(null)
  const [isUpdatingAgentTarget, setIsUpdatingAgentTarget] = useState(false)
  // Demo Day handoff-bundle download (separate from the generic export so the
  // panel's button has its own in-flight state and post-download verdict refresh).
  const [isDownloadingBundle, setIsDownloadingBundle] = useState(false)
  const [latestStoryboard, setLatestStoryboard] =
    useState<StoryboardDetail | null>(null)
  const [isStoryboardLoading, setIsStoryboardLoading] = useState(false)
  const [showCreateStoryboard, setShowCreateStoryboard] = useState(false)
  const [storyboardAction, setStoryboardAction] =
    useState<StoryboardAction | null>(null)
  const [storyboardMessage, setStoryboardMessage] =
    useState<StoryboardFlowMessage | null>(null)
  const [storyboardGenerationFailure, setStoryboardGenerationFailure] =
    useState<string | null>(null)
  const [pendingClarify, setPendingClarify] = useState<PendingClarifyAction | null>(
    null,
  )
  const [generationActivity, setGenerationActivity] =
    useState<GenerationActivityInfo | null>(null)
  const generationActivityRef = useRef<GenerationActivityInfo | null>(null)
  // RC-1: a STABLE per-stage reconnect elapsed baseline. When a stage is
  // observed in_progress but this client isn't streaming it (a refresh landed
  // mid-generation), we pin the baseline once here — from the backend's
  // write-once `generation_started_at` if present, else the stage's `updated_at`
  // at first observation — and reuse it for every subsequent reconnect-poll
  // re-render. Without this the memo below recomputed off `updated_at`, which
  // the 30s DB heartbeat bumps, sawtoothing the timer back toward 0. Entries are
  // pruned when the stage leaves in_progress (see the effect below).
  const reconnectStartRef = useRef<Record<string, number>>({})
  // P1-B belt-and-braces: fires at most one delayed post-load refetch per
  // workspace to catch a generation that committed `in_progress` just after the
  // initial load (the preflight-blindness window). Keyed by workspace id.
  const preflightRecheckRef = useRef<string | null>(null)
  // Cancellation token for the in-flight post-`done` construction-verdict poll
  // (Demo Day mode). A new generation (or unmount) flips `cancelled` so a stale
  // poll can never overwrite a superseded workspace — mirrors `advisoryPollRef`
  // in useStream.ts.
  const verdictPollRef = useRef<{ cancelled: boolean } | null>(null)
  useEffect(
    () => () => {
      if (verdictPollRef.current) verdictPollRef.current.cancelled = true
    },
    [],
  )

  // "Connected enough to export" under the GitHub App living system means an
  // active App installation; we also honour a legacy OAuth connection so a
  // mid-migration user isn't locked out of the export entry point (the modal
  // itself nudges them to install the App when no installation_id exists).
  useEffect(() => {
    let cancelled = false
    Promise.all([
      getGitHubInstallations().catch(() => ({
        installations: [],
        on_legacy_oauth: false,
      })),
      getGitHubIntegration().catch(() => ({ connected: false })),
    ])
      .then(([installs, legacy]) => {
        if (cancelled) return
        const hasActiveApp = installs.installations.some(
          (i: { suspended: boolean }) => !i.suspended,
        )
        setIsGitHubConnected(hasActiveApp || legacy.connected)
      })
      .catch(() => {
        if (!cancelled) setIsGitHubConnected(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const activeStage = activeStageId ? stageMap[activeStageId] : null
  const { start: startStream, isStreaming, error: streamError } = useStream(
    activeStage?.id ?? null,
  )
  // Reconnect overlay: the stage is generating server-side but THIS client is
  // not the one streaming it (true on a fresh mount after a page refresh —
  // docs/REFRESH_DURING_GENERATION_PLAN.md). The detached pipeline keeps running
  // and `useReconnectPoll` delivers the settled artifact, but without a
  // synthetic activity the StreamingOverlay never shows, so the screen looks
  // empty and the user thinks the generation was lost.
  //
  // Elapsed baseline (RC-1): `updated_at` is NOT a stable start instant — the
  // 30s DB heartbeat (`_stage_db_heartbeat`) bumps it precisely so the recovery
  // sweep never kills a live generation, so reading it live sawtoothed the timer
  // back toward 0 on every reconnect-poll refetch. Prefer the write-once
  // `generation_started_at`; when absent (older backends / cache-hit drafts) pin
  // `updated_at` at first observation via `reconnectStartRef` and reuse it. Both
  // clamped ≤ now for clock skew. The operation label comes from the persisted
  // `generation_action` so a refreshed regenerate isn't mislabelled "generate"
  // (A6). Memoised on stable inputs (NOT `updated_at`) so identity is steady
  // across the poll's 3s re-renders and the overlay's timer effect never re-arms
  // onto a fresh baseline.
  const reconnectStreaming =
    Boolean(activeStage) &&
    activeStage?.status === "in_progress" &&
    !isStreaming &&
    generationActivity?.stageId !== activeStage?.id
  let reconnectStart = Date.now()
  if (reconnectStreaming && activeStage) {
    const now = Date.now()
    const stamped = activeStage.generation_started_at
      ? Date.parse(activeStage.generation_started_at)
      : NaN
    if (Number.isFinite(stamped)) {
      reconnectStart = Math.min(stamped, now)
    } else {
      const pinned = reconnectStartRef.current[activeStage.id]
      reconnectStart =
        pinned ??
        (reconnectStartRef.current[activeStage.id] = Math.min(
          Date.parse(activeStage.updated_at) || now,
          now,
        ))
    }
  }
  const reconnectOp = reconnectOperation(activeStage?.generation_action)
  const reconnectActivity: GenerationActivityInfo | null = useMemo(
    () =>
      reconnectStreaming && activeStage
        ? {
            stageId: activeStage.id,
            stageType: activeStage.type,
            operation: reconnectOp,
            actionLabel: getGenerationActionLabel(reconnectOp),
            startedAt: reconnectStart,
            streamed: false,
          }
        : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      reconnectStreaming,
      activeStage?.id,
      activeStage?.type,
      reconnectOp,
      reconnectStart,
    ],
  )
  const activeGenerationActivity =
    activeStage && generationActivity?.stageId === activeStage.id
      ? generationActivity
      : reconnectActivity
  const activeBusyOperation = activeGenerationActivity?.operation ?? null
  // Backend liveness heartbeat for the in-flight generation (issue #19):
  // surfaces "still working" in the overlay while the model reasons silently.
  const activeStreamProgress =
    activeStage && activeGenerationActivity
      ? streamProgressMap[activeStage.id] ?? null
      : null
  // Progressive streaming: once live draft tokens are arriving, the overlay
  // collapses to a slim pill so the user watches the document grow in the
  // editor instead of staring at a full-card loading screen.
  const hasLiveDraft = useStageStore((s) =>
    Boolean(activeStageId && s.streamingContent[activeStageId]),
  )

  const startGenerationActivity = useCallback(
    (
      stage: Stage,
      operation: GenerationActivityOperation,
      streamed: boolean,
    ) => {
      const nextActivity: GenerationActivityInfo = {
        stageId: stage.id,
        stageType: stage.type,
        operation,
        actionLabel: getGenerationActionLabel(operation),
        startedAt: Date.now(),
        streamed,
      }
      generationActivityRef.current = nextActivity
      setGenerationActivity(nextActivity)
      return nextActivity
    },
    [],
  )

  const clearGenerationActivity = useCallback((stageId?: string) => {
    if (
      stageId &&
      generationActivityRef.current &&
      generationActivityRef.current.stageId !== stageId
    ) {
      return
    }
    generationActivityRef.current = null
    setGenerationActivity(null)
  }, [])

  // Live GitHub task-completion + drift state (T-275). Only polls on the Tasks
  // stage, where the completion panel is shown beside the coverage panels.
  const githubSync = useGitHubSync(id, activeStage?.type === "tasks")

  // T-247 critic quality gate: findings surfaced when a generation is held back.
  // The transient, SSE-driven map still feeds the findings panel below, but it is
  // dismissable — so it must NOT decide whether finalise is blocked.
  const activeGate = activeStage ? qualityGateMap[activeStage.id] : undefined
  // Finalise-blocking reads ONE authoritative source: the persisted stage object
  // (issue #28, Phase 1). It is populated the moment the gate fires (the
  // `quality_gate_failed` stream rejection refetches the stage — useStream.ts:100)
  // and after every refresh, and unlike the SSE map it cannot be dismissed away.
  const finaliseGateBlock = deriveFinaliseGateBlock(activeStage)
  const qualityGateBlocked = finaliseGateBlock.blocked
  const qualityGateBlockedMessage = finaliseGateBlock.message
  // Non-blocking critic suggestions on a finalisable draft (issue #34).
  const advisoryFindings = deriveAdvisoryFindings(activeStage)

  const stages = useMemo(() => {
    const workspaceStageIds = new Set(
      currentWorkspace?.stages.map((stage) => stage.id) ?? [],
    )
    return sortStages(
      Object.values(stageMap).filter((stage) => workspaceStageIds.has(stage.id)),
    )
  }, [currentWorkspace?.stages, stageMap])
  const inProgressStage = stages.find((stage) => stage.status === "in_progress") ?? null
  // Prune pinned reconnect baselines (RC-1) for any stage no longer in_progress,
  // so a later generation of the same stage re-pins from its fresh start instead
  // of reusing a stale one. Bounded to the handful of concurrent generations.
  useEffect(() => {
    const live = new Set(
      stages.filter((s) => s.status === "in_progress").map((s) => s.id),
    )
    for (const id of Object.keys(reconnectStartRef.current)) {
      if (!live.has(id)) delete reconnectStartRef.current[id]
    }
  }, [stages])
  const workspaceLockStage =
    (generationActivity ? stageMap[generationActivity.stageId] : null) ??
    inProgressStage ??
    (isStreaming || isRefining ? activeStage : null)
  const workspaceLockOperation =
    generationActivity?.operation ??
    (isRefining ? "focused-patch" : null) ??
    (inProgressStage || isStreaming ? "generate" : null)
  const workspaceGenerationLock = getWorkspaceGenerationLock(
    Boolean(generationActivity) || isStreaming || isRefining || Boolean(inProgressStage),
    workspaceLockStage,
    workspaceLockOperation,
  )
  const isGenerationBusy = workspaceGenerationLock.locked
  const isActiveStageBusy =
    Boolean(activeGenerationActivity) ||
    (isStreaming && !generationActivity) ||
    activeStage?.status === "in_progress"
  const workspaceLockReason = workspaceGenerationLock.reason
  const workspaceLockInlineReason = workspaceGenerationLock.locked
    ? `Editing paused. ${workspaceLockReason}`
    : undefined
  const guardWorkspaceMutation = useCallback(() => {
    if (!workspaceGenerationLock.locked) return false
    showAlert(
      actionAlertFromMessage({
        title: "Editing is paused",
        message: `${workspaceGenerationLock.message}. ${workspaceGenerationLock.detail}`,
        recovery: workspaceLockReason,
        source: "Workspace",
      }),
    )
    return true
  }, [
    showAlert,
    workspaceGenerationLock.locked,
    workspaceGenerationLock.message,
    workspaceGenerationLock.detail,
    workspaceLockReason,
  ])
  const stagesWithEval = useMemo(
    () =>
      stages.map((stage) => ({
        ...stage,
        eval_result: evalResults[stage.id] ?? stage.eval_result ?? null,
      })),
    [stages, evalResults],
  )

  const allFinalised =
    stages.length === STAGE_ORDER.length &&
    stages.every((stage) => stage.status === "finalised")
  // Demo Day mode (docs/DEMO_DAY_MODE_IMPLEMENTATION_PLAN.md §10 Phase 4). The
  // construction badge + handoff panel render data-driven on the workspace's
  // persisted mode, NOT the build flag, so a workspace already created in Demo
  // Day mode keeps its handoff UI even if VITE_DEMO_DAY_MODE is off.
  const isDemoDayWorkspace = currentWorkspace?.mode === "demo_day"
  const constructionVerdict = currentWorkspace?.construction_verdict ?? null
  const canCreateStoryboard = canCreateStoryboardFromStages(stages)
  const hasStaleStoryboardPrerequisite = stages.some(
    (stage) => stage.status === "stale",
  )
  const savedClarificationAnswers = currentWorkspace?.clarification_qa ?? []
  const hasSavedClarificationAnswers = savedClarificationAnswers.length > 0
  const shouldShowCreateStoryboardCta =
    canCreateStoryboard && latestStoryboard === null && !isStoryboardLoading

  // Count tasks for the GitHub modal's issue-count preview using the same
  // canonical parser as TasksBoard, so the preview can never disagree with the
  // cards users just reviewed (including whitespace before the heading colon).
  const taskCount = useMemo(() => {
    const tasksStage = stages.find((s) => s.type === "tasks")
    if (!tasksStage?.content) return 0
    return parseTaskBlocks(tasksStage.content).length
  }, [stages])

  // Effort Summary chip — only the TASKS stage carries this block, and only
  // when the user is viewing the tasks pane. Older finalised tasks generated
  // before T-164 return null from the parser and the chip is hidden.
  const effortSummary = useMemo(() => {
    if (!activeStage || activeStage.type !== "tasks") return null
    return parseEffortSummary(activeStage.content ?? "")
  }, [activeStage])

  const canExport =
    allFinalised ||
    stages.some((stage) => Boolean(stage.content?.trim())) ||
    Boolean(problemDraft.trim())

  const refreshLatestStoryboard = useCallback(
    async (quiet = false) => {
      if (!id) return null

      const requestId = storyboardLoadRequestRef.current + 1
      storyboardLoadRequestRef.current = requestId
      if (!quiet) {
        storyboardLoadingRequestRef.current = requestId
        setIsStoryboardLoading(true)
      }
      try {
        const storyboard = await getLatestStoryboard(id)
        if (storyboardLoadRequestRef.current === requestId) {
          setLatestStoryboard(storyboard)
        }
        return storyboard
      } catch (error) {
        if (storyboardLoadRequestRef.current === requestId) {
          setStoryboardMessage({
            kind: "error",
            text: getApiErrorMessage(error, "Could not load the latest Storyboard."),
          })
        }
        return null
      } finally {
        if (!quiet && storyboardLoadingRequestRef.current === requestId) {
          setIsStoryboardLoading(false)
        }
      }
    },
    [id],
  )

  useEffect(() => {
    if (id) {
      void fetchWorkspace(id)
    }
  }, [id, fetchWorkspace])

  useEffect(() => {
    if (!id || currentWorkspace?.id !== id) return
    void refreshLatestStoryboard()
  }, [id, currentWorkspace?.id, refreshLatestStoryboard])

  useEffect(() => {
    if (!currentWorkspace) return

    setStages(currentWorkspace.stages)
    setActiveStageId((existing) => pickActiveStageOnLoad(currentWorkspace.stages, existing))

    setEvalResults((existing) => {
      const next = { ...existing }
      currentWorkspace.stages.forEach((stage) => {
        if (stage.eval_result) {
          next[stage.id] = stage.eval_result
        } else if (!(stage.id in next)) {
          next[stage.id] = null
        }
      })
      return next
    })
    setProblemDraft(currentWorkspace.problem_statement)
    setProblemDirty(false)
  }, [currentWorkspace, setStages])

  useEffect(() => {
    if (
      !activeStage ||
      activeStage.status === "locked" ||
      activeStage.status === "in_progress" ||
      activeStage.quality_gate?.status === "blocked" ||
      !activeStage.content?.trim()
    ) {
      return
    }

    const stageId = activeStage.id
    let cancelled = false

    const loadEval = async () => {
      let consecutiveFailures = 0
      for (let attempt = 0; attempt < EVAL_POLL_ATTEMPTS; attempt += 1) {
        try {
          const result = await getStageEval(stageId)
          if (!cancelled) {
            consecutiveFailures = 0
            setEvalResults((existing) => ({ ...existing, [stageId]: result }))
          }
          return
        } catch (err) {
          if (cancelled) {
            return
          }
          consecutiveFailures += 1
          if (consecutiveFailures >= EVAL_POLL_ATTEMPTS || attempt === EVAL_POLL_ATTEMPTS - 1) {
            // All retries exhausted — surface a terminal error badge rather than
            // leaving the shimmer spinner spinning indefinitely.  M-5 — T-187.
            console.error("[eval] polling exhausted maxRetries for stage", stageId, err)
            setEvalError((existing) => ({ ...existing, [stageId]: true }))
            setEvalResults((existing) => ({ ...existing, [stageId]: null }))
            return
          }
          await sleep(EVAL_POLL_DELAY_MS)
        }
      }
    }

    void loadEval()

    return () => {
      cancelled = true
    }
  }, [
    activeStage?.id,
    activeStage?.status,
    activeStage?.current_version,
    activeStage?.content,
    activeStage?.quality_gate?.status,
  ])

  // Reconnect-by-poll (docs/REFRESH_DURING_GENERATION_PLAN.md): when a stage is
  // `in_progress` but THIS client is not the one streaming it — true on a fresh
  // mount after a page refresh — the server keeps the detached generation
  // pipeline running and persists the finished artifact at `done`. The hook
  // polls until the stage leaves `in_progress` and writes the settled result
  // into the store, so the completed draft (or a quality-gate block) appears
  // without a manual re-generate. The active streamer drives the stage via the
  // SSE hook, so it never polls here.
  useReconnectPoll(inProgressStage?.id ?? null, isStreaming)

  useEffect(() => {
    if (!latestStoryboard || latestStoryboard.status !== "generating") return

    let cancelled = false
    let attempts = 0
    let timeoutId: number | undefined

    const poll = async () => {
      attempts += 1
      try {
        const fresh = await getStoryboard(latestStoryboard.id)
        if (cancelled) return

        setLatestStoryboard(fresh)

        if (fresh.status === "ready") {
          setStoryboardMessage({
            kind: "success",
            text: "Storyboard is ready to present.",
          })
          if (storyboardAutoOpenRef.current === fresh.id) {
            storyboardAutoOpenRef.current = null
            navigate(`/storyboards/${fresh.id}`, { state: { workspaceId: id } })
          }
          return
        }

        if (fresh.status === "failed") {
          storyboardAutoOpenRef.current = null
          setStoryboardGenerationFailure(
            "Storyboard generation failed after the request was accepted.",
          )
          setStoryboardMessage({
            kind: "error",
            text:
              "Storyboard generation failed. Credits were refunded and any previous ready Storyboard remains available.",
          })
          if (id) {
            const authoritativeLatest = await getLatestStoryboard(id)
            if (!cancelled && authoritativeLatest) {
              setLatestStoryboard(authoritativeLatest)
            }
          }
          return
        }

        if (fresh.status !== "generating") {
          storyboardAutoOpenRef.current = null
          return
        }
      } catch {
        if (cancelled) return
        if (attempts >= STORYBOARD_POLL_ATTEMPTS) {
          setStoryboardMessage({
            kind: "error",
            text: "Storyboard status could not be refreshed. Open the workspace again to check the latest state.",
          })
          return
        }
      }

      if (!cancelled && attempts < STORYBOARD_POLL_ATTEMPTS) {
        timeoutId = window.setTimeout(poll, STORYBOARD_POLL_DELAY_MS)
      }
    }

    timeoutId = window.setTimeout(poll, STORYBOARD_POLL_DELAY_MS)

    return () => {
      cancelled = true
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId)
      }
    }
  }, [id, latestStoryboard?.id, latestStoryboard?.status, navigate])

  useEffect(() => {
    if (!showRefineHint) return
    const t = setTimeout(() => setShowRefineHint(false), 5000)
    return () => clearTimeout(t)
  }, [showRefineHint])

  useEffect(() => {
    setIsEditMode(false)
    setSpecViewMode("preview")
    setIsMobileNavOpen(false)
  }, [activeStageId])

  const refreshWorkspace = useCallback(async () => {
    if (!id) return
    const workspace = await getWorkspace(id)
    setCurrentWorkspace(workspace)
    setStages(workspace.stages)
  }, [id, setCurrentWorkspace, setStages])

  // P1-B belt-and-braces (RC-3 Mode B): a page refresh can land in the brief
  // preflight window BEFORE generate() commits `in_progress`. The backend
  // reorder shrank that window to ~ms, but the cheap Redis/admission preflight
  // before the charge is still nonzero, and a refresh there sees the stage as
  // `draft` — so neither the reconnect overlay nor the poll engages and the
  // screen looks idle. Once per workspace load, if nothing is in_progress, do
  // ONE delayed refetch to catch a generation that committed just after we
  // loaded. Harmless (a single extra GET) when the workspace really is idle.
  useEffect(() => {
    if (isLoading || !id) return
    if (preflightRecheckRef.current === id) return
    preflightRecheckRef.current = id
    if (inProgressStage) return
    const timer = window.setTimeout(() => {
      void refreshWorkspace().catch(() => {})
    }, 5000)
    return () => window.clearTimeout(timer)
  }, [id, isLoading, inProgressStage, refreshWorkspace])

  // Demo Day: the construction verdict is computed by a DETACHED backend task a
  // few seconds AFTER the tasks stream ends (plan §7.3), so the single
  // refreshWorkspace() that runGeneration does on `done` is too early to see it —
  // without this the badge stays "pending" until a manual reload. Follow the
  // refresh with a bounded poll that stops the instant a fresh verdict lands.
  // Cancellable so a tasks regenerate (or unmount) can never let a late fetch
  // clobber the now-in_progress workspace. Best-effort: every fetch error is
  // swallowed and on timeout the verdict surfaces on the next natural fetch.
  const pollForConstructionVerdict = useCallback(() => {
    if (!id) return
    if (verdictPollRef.current) verdictPollRef.current.cancelled = true
    const token = { cancelled: false }
    verdictPollRef.current = token
    void pollForFreshVerdict({
      fetchWorkspace: () => getWorkspace(id),
      onWorkspace: (workspace) => {
        setCurrentWorkspace(workspace)
        setStages(workspace.stages)
      },
      isCancelled: () => token.cancelled,
    })
  }, [id, setCurrentWorkspace, setStages])

  const saveProblemStatement = useCallback(async () => {
    if (!id || !currentWorkspace || !problemDirty) return true
    if (guardWorkspaceMutation()) return false

    const trimmed = problemDraft.trim()
    if (trimmed.length < 50) {
      setGenericError("Problem statement needs at least 50 characters before saving.")
      return false
    }

    try {
      const workspace = await updateWorkspace(id, {
        problem_statement: problemDraft,
      })
      setCurrentWorkspace(workspace)
      setStages(workspace.stages)
      setProblemDirty(false)
      return true
    } catch (error) {
      setGenericError(
        getApiErrorMessage(error, "Could not save the problem statement."),
      )
      return false
    }
  }, [
    id,
    currentWorkspace,
    problemDirty,
    problemDraft,
    guardWorkspaceMutation,
    setCurrentWorkspace,
    setStages,
  ])

  const updateClarificationAnswersLocally = useCallback(
    (answers: ClarifyAnswer[]) => {
      if (!currentWorkspace || answers.length === 0) return
      setCurrentWorkspace({
        ...currentWorkspace,
        clarification_qa: answers.map((entry) => ({
          question: entry.question,
          answer: entry.answer,
        })),
      })
    },
    [currentWorkspace, setCurrentWorkspace],
  )

  // Declared before confirmCredits/proceedThroughReviewGate which call it
  const runGeneration = useCallback(
    async (
      action: "generate" | "regenerate" | "regenerate-gaps",
      operation: GenerationActivityOperation = action,
      activityAlreadyStarted = false,
    ) => {
      if (!activeStage || (generationActivityRef.current && !activityAlreadyStarted)) {
        return
      }

      const stageId = activeStage.id
      if (!activityAlreadyStarted) {
        startGenerationActivity(activeStage, operation, true)
      }

      // A fresh generation supersedes any verdict poll still running for the
      // prior package (Demo Day) — cancel it before the new stream so a late
      // fetch can't overwrite the now-in_progress workspace.
      if (verdictPollRef.current) verdictPollRef.current.cancelled = true

      lastGenerationActionRef.current = action
      dismissAlert()
      setEvalResults((existing) => ({ ...existing, [stageId]: null }))
      try {
        const result = await startStream(action)
        if (!result) return

        setStage(result.stage)
        if (result.stage.type === "spec") {
          setSpecViewMode("preview")
        }
        if (result.evalResult) {
          setEvalResults((existing) => ({
            ...existing,
            [result.stage.id]: result.evalResult,
          }))
        }
        await refreshWorkspace()
        // Demo Day: a completed tasks generation (generate / regenerate /
        // regenerate-gaps all reschedule the backend verifier) means the
        // detached verdict run just started — poll until it lands.
        if (result.stage.type === "tasks" && isDemoDayWorkspace) {
          pollForConstructionVerdict()
        }
      } finally {
        clearGenerationActivity(stageId)
      }
    },
    [
      activeStage,
      clearGenerationActivity,
      dismissAlert,
      isDemoDayWorkspace,
      pollForConstructionVerdict,
      refreshWorkspace,
      setStage,
      startGenerationActivity,
      startStream,
    ],
  )

  const handleGateRegenerate = useCallback(async () => {
    if (!activeStage) return
    if (generationActivityRef.current || guardWorkspaceMutation()) return
    startGenerationActivity(activeStage, "quality-gate-regenerate", true)
    clearQualityGate(activeStage.id)
    await runGeneration("regenerate", "quality-gate-regenerate", true)
  }, [activeStage, clearQualityGate, guardWorkspaceMutation, runGeneration, startGenerationActivity])

  const handleGateOverride = useCallback(async () => {
    if (!activeStage) return
    if (guardWorkspaceMutation()) return
    try {
      const updatedStage = await overrideQualityGate(activeStage.id)
      setStage(updatedStage)
      clearQualityGate(activeStage.id)
      await refreshWorkspace()
    } catch (error) {
      setGenericError(
        getApiErrorMessage(error, "Could not override the quality gate."),
      )
    }
  }, [
    activeStage,
    clearQualityGate,
    guardWorkspaceMutation,
    refreshWorkspace,
    setStage,
  ])

  // "Hide details" (issue #28, Phase 2): collapse the findings panel only. This
  // clears the transient SSE map entry, but the blocked state stays legible —
  // the header badge and the collapsed notice both derive from the persisted
  // `activeStage.quality_gate`, so nothing about the block is lost.
  const handleGateDismiss = useCallback(() => {
    if (!activeStage) return
    if (guardWorkspaceMutation()) return
    clearQualityGate(activeStage.id)
  }, [activeStage, clearQualityGate, guardWorkspaceMutation])

  // "Show details": re-expand the findings panel from the authoritative stage
  // object (symmetric with the badge's source), so dismissal is non-destructive
  // and reversible without a refresh.
  const handleGateShowDetails = useCallback(() => {
    if (!activeStage?.quality_gate) return
    setQualityGate(activeStage.id, activeStage.quality_gate)
  }, [activeStage, setQualityGate])

  const requestGeneration = useCallback(
    async (action: "generate" | "regenerate") => {
      if (generationActivityRef.current) return
      if (!activeStage) return
      if (guardWorkspaceMutation()) return
      if (activeStage.type === "spec") {
        const saved = await saveProblemStatement()
        if (!saved) return
      }
      // First spec generation gets the clarification gate. Subsequent
      // regenerates and every non-spec stage skip straight to credit
      // confirm. The modal opens only when the user has not already
      // answered clarifications on this workspace.
      const needsClarification =
        action === "generate" &&
        activeStage.type === "spec" &&
        activeStage.current_version === 0 &&
        !hasSavedClarificationAnswers
      if (needsClarification) {
        setPendingClarify({ action, stageId: activeStage.id, mode: "new" })
        return
      }
      setPendingCredit({ action, stageId: activeStage.id })
    },
    [
      activeStage,
      guardWorkspaceMutation,
      hasSavedClarificationAnswers,
      saveProblemStatement,
    ],
  )

  const handleClarifyProceed = useCallback(
    (answers: ClarifyAnswer[]) => {
      if (!pendingClarify) return
      updateClarificationAnswersLocally(answers)
      const next = pendingClarify
      setPendingClarify(null)
      setPendingCredit(next)
    },
    [pendingClarify, updateClarificationAnswersLocally],
  )

  const handleClarifyCancel = useCallback(() => {
    setPendingClarify(null)
  }, [])

  const requestGapPatch = useCallback(() => {
    if (!activeStage) return
    if (generationActivityRef.current || guardWorkspaceMutation()) return
    setPendingCredit({ action: "patch", stageId: activeStage.id })
  }, [activeStage, guardWorkspaceMutation])

  const performRollback = useCallback(async (version: number) => {
    if (!activeStage) return
    if (guardWorkspaceMutation()) return
    try {
      const updated = await rollbackStage(activeStage.id, version)
      setStage(updated)
      setEvalResults((existing) => ({ ...existing, [activeStage.id]: null }))
      await refreshWorkspace()
    } catch (error) {
      // Rollback now 409s on an in_progress stage (A1). Surface it instead of an
      // unhandled promise rejection; a concurrent generation reconciles itself.
      setGenericError(
        getApiErrorMessage(error, "Could not restore this version right now."),
      )
    }
  }, [activeStage, guardWorkspaceMutation, setStage, refreshWorkspace])

  useEffect(() => {
    // `session_expired` is intentionally skipped here: the app-level
    // SessionExpiryWatcher already shows the single authoritative explanation
    // and redirects to sign-in — a second, generic "action could not finish"
    // alert from this effect would just be noise on top of it.
    // `generation_in_progress` is skipped too: useStream reconciles a
    // duplicate-trigger into the reconnect UX (no alert), so this should never
    // fire, but suppress it defensively so a stray one can't nag the user.
    if (
      !streamError ||
      streamError.code === "quality_gate_failed" ||
      streamError.code === "session_expired" ||
      streamError.code === "generation_in_progress"
    )
      return

    const retryable = new Set([
      "generation_timeout",
      "generation_unavailable",
      "rate_limit_exceeded",
      "internal_error",
      // An interrupted stream that reconciled to "failed + refunded" (or a
      // gap-patch rollback): offer a user-consented retry — never an auto-POST.
      "stream_interrupted",
      "generic",
    ])
    const canRetrySpecWithAnswers =
      retryable.has(streamError.code) &&
      activeStage !== null &&
      activeStage.type === "spec" &&
      activeStage.current_version === 0 &&
      lastGenerationActionRef.current === "generate" &&
      hasSavedClarificationAnswers

    let primaryAction: ActionAlertAction | undefined
    if (streamError.code === "insufficient_credits") {
      primaryAction = {
        label: "View billing",
        onSelect: () => navigate("/billing"),
      }
    } else if (
      streamError.code === "stage_not_generatable" &&
      activeStage &&
      activeStage.status === "finalised"
    ) {
      // "Unlock stage" is a rollback, and rollback flips the stage to draft. Only
      // offer it for a FINALISED stage — the case the copy was written for.
      // Offering it on an in_progress stage (the old behavior) let a duplicate
      // trigger flip a LIVE generation back to draft and start a second charged
      // run (A1). A genuine in_progress duplicate now arrives as
      // `generation_in_progress` and is reconciled silently, never here.
      primaryAction = {
        label: "Unlock stage",
        onSelect: () => {
          void performRollback(activeStage.current_version)
        },
      }
    } else if (canRetrySpecWithAnswers && activeStage) {
      primaryAction = {
        label: "Retry with answers",
        onSelect: () => {
          setPendingCredit({ action: "generate", stageId: activeStage.id })
        },
      }
    } else if (retryable.has(streamError.code)) {
      primaryAction = {
        label: "Try again",
        onSelect: () => {
          void runGeneration(lastGenerationActionRef.current)
        },
      }
    }

    let secondaryAction: ActionAlertAction | undefined
    if (canRetrySpecWithAnswers && activeStage) {
      secondaryAction = {
        label: "Edit answers",
        onSelect: () => {
          setPendingClarify({
            action: "generate",
            stageId: activeStage.id,
            mode: "existing",
          })
        },
      }
    }

    showAlert(
      actionAlertFromStreamError(streamError, { primaryAction, secondaryAction }),
    )
  }, [
    activeStage,
    hasSavedClarificationAnswers,
    navigate,
    performRollback,
    runGeneration,
    showAlert,
    streamError,
  ])

  const requestRefine = useCallback(() => {
    if (guardWorkspaceMutation()) return
    const currentSelection = editorRef.current?.getSelection()
    if (!activeStage || !currentSelection) {
      if (activeStage?.type === "spec") {
        setSpecViewMode("edit")
      } else {
        setIsEditMode(true)
      }
      setShowRefineHint(true)
      return
    }

    setSelection(currentSelection)
    setRefineInstruction("")
    setRefineMode("focused")
    setShowRefineInput(true)
    dismissAlert()
  }, [activeStage, dismissAlert, guardWorkspaceMutation])

  const confirmCredits = useCallback(async () => {
    if (!pendingCredit) return
    if (guardWorkspaceMutation()) return

    const stage = stageMap[pendingCredit.stageId]
    if (!stage) return

    // A5: `runGeneration` generates whatever is CURRENTLY active (the useStream
    // hook is bound to `activeStage`), while this validated `stage` is the one
    // the credit modal was opened for. They can only differ if navigation
    // slipped between opening the modal and confirming; generating the wrong
    // stage would silently charge for the wrong artifact. Refuse rather than
    // generate the wrong one — a select-then-run can't work in one pass anyway
    // (the captured closures wouldn't see the new active stage).
    if (pendingCredit.stageId !== activeStage?.id) {
      setPendingCredit(null)
      return
    }

    if (
      pendingCredit.action !== "patch" &&
      stage.type !== "spec" &&
      !stage.review_gate_acknowledged
    ) {
      setPendingReview({
        action: pendingCredit.action,
        stageId: pendingCredit.stageId,
      })
      setPendingCredit(null)
      return
    }

    const nextAction =
      pendingCredit.action === "patch"
        ? "regenerate-gaps"
        : pendingCredit.action
    setPendingCredit(null)

    await runGeneration(nextAction)
  }, [activeStage?.id, guardWorkspaceMutation, pendingCredit, stageMap, runGeneration])

  const proceedThroughReviewGate = useCallback(async () => {
    if (!pendingReview) return
    if (guardWorkspaceMutation()) return

    // A5: the review gate was queued for a specific stage, but `runGeneration`
    // always generates the ACTIVE stage. If the user navigated to a different
    // stage after the gate was raised, proceeding would acknowledge one stage's
    // gate and then charge a generation on another. Refuse + clear, exactly like
    // confirmCredits.
    if (pendingReview.stageId !== activeStage?.id) {
      setPendingReview(null)
      return
    }

    const stage = stageMap[pendingReview.stageId]
    if (!stage) return

    try {
      const reviewedStage = await acknowledgeReviewGate(stage.id)
      setStage(reviewedStage)
      setPendingReview(null)
      await runGeneration(
        pendingReview.action === "regenerate" ? "regenerate" : "generate",
      )
    } catch {
      setGenericError("Could not acknowledge the review gate.")
    }
  }, [
    activeStage?.id,
    guardWorkspaceMutation,
    pendingReview,
    stageMap,
    setStage,
    runGeneration,
  ])

  const runRefine = useCallback(async () => {
    if (guardWorkspaceMutation()) return
    if (refineInFlightRef.current || generationActivityRef.current) {
      return
    }
    if (!activeStage || !selection || !refineInstruction.trim()) {
      setGenericError("Add an instruction before refining.")
      return
    }

    refineInFlightRef.current = true
    startGenerationActivity(activeStage, "focused-patch", false)
    setIsRefining(true)
    try {
      const currentContent = editorRef.current?.getContent()
      if (currentContent !== undefined && currentContent !== activeStage.content) {
        const savedStage = await updateStageContent(activeStage.id, currentContent)
        setStage(savedStage)
        setEvalResults((existing) => ({ ...existing, [savedStage.id]: null }))
      }
      const result = await refineStage(activeStage.id, {
        instruction: refineInstruction.trim(),
        selection_start: selection.start,
        selection_end: selection.end,
        selected_text: selection.text,
        mode: refineMode,
      })
      setDiffResult(result)
      setLargeSelectionWarning(result.large_selection)
      setShowRefineInput(false)
    } catch (error) {
      setGenericError(
        getApiErrorMessage(error, "Refine failed. Check your selection and try again."),
      )
    } finally {
      refineInFlightRef.current = false
      setIsRefining(false)
      clearGenerationActivity(activeStage.id)
    }
  }, [
    activeStage,
    clearGenerationActivity,
    refineInstruction,
    refineMode,
    guardWorkspaceMutation,
    selection,
    setStage,
    startGenerationActivity,
  ])

  const acceptDiff = useCallback(
    async (proposed: string) => {
      if (!activeStage) return
      if (guardWorkspaceMutation()) return
      try {
        const updatedStage = await acceptStageDiff(activeStage.id, proposed)
        setStage(updatedStage)
        setEvalResults((existing) => ({ ...existing, [updatedStage.id]: null }))
        setDiffResult(null)
        setLargeSelectionWarning(false)
      } catch (error) {
        // Keep the diff mounted on failure so the paid proposal is never lost
        // to a transient network or concurrency error.
        setGenericError(
          getApiErrorMessage(error, "Could not apply the proposed changes."),
        )
      }
    },
    [activeStage, guardWorkspaceMutation, setStage, setGenericError],
  )

  const rejectDiff = useCallback(async () => {
    if (!activeStage) {
      setDiffResult(null)
      return
    }
    if (guardWorkspaceMutation()) return

    try {
      await rejectStageDiff(activeStage.id)
      setDiffResult(null)
      setLargeSelectionWarning(false)
    } catch (error) {
      // Reject is persisted server-side for audit/cleanup. If it fails, retain
      // the proposal so the user can retry either action without regenerating.
      setGenericError(
        getApiErrorMessage(error, "Could not reject the proposed changes."),
      )
    }
  }, [activeStage, guardWorkspaceMutation, setGenericError])

  // Accept a stale stage's existing content as-is: restores it to finalised
  // server-side via the credit-free acknowledge path (no regenerate). This is
  // NOT finaliseStage() — that endpoint rejects non-draft stages (the "Stage
  // status 'stale' cannot be finalised" 409) and would re-stale a still-
  // consistent finalised downstream. Reached from both the staleness banner's
  // "Keep" button and the GenerateBar "Finalise" button when the stage is stale.
  const handleAcknowledgeStale = useCallback(async () => {
    if (!activeStage || !id) return
    if (finaliseInFlightRef.current) return
    if (guardWorkspaceMutation()) return
    finaliseInFlightRef.current = true
    try {
      const updatedStage = await acknowledgeStaleStage(activeStage.id)
      setStage(updatedStage)
      const workspace = await getWorkspace(id)
      setCurrentWorkspace(workspace)
      setStages(workspace.stages)
      void refreshLatestStoryboard(true)
    } catch (err) {
      setGenericError(getApiErrorMessage(err, "Could not keep this stage as-is."))
    } finally {
      finaliseInFlightRef.current = false
    }
  }, [
    activeStage,
    guardWorkspaceMutation,
    id,
    refreshLatestStoryboard,
    setCurrentWorkspace,
    setGenericError,
    setStage,
    setStages,
  ])

  const handleFinalise = useCallback(async () => {
    if (!activeStage || !id) return
    if (finaliseInFlightRef.current) return
    if (guardWorkspaceMutation()) return
    // A stale stage's "Finalise" means "accept what's already here": there is no
    // new draft to finalise, so route it to the credit-free acknowledge path.
    if (activeStage.status === "stale") {
      void handleAcknowledgeStale()
      return
    }
    const gateBlock = deriveFinaliseGateBlock(activeStage)
    if (gateBlock.blocked) {
      setGenericError(gateBlock.message)
      return
    }
    const finalisedType = activeStage.type
    finaliseInFlightRef.current = true
    try {
      const updatedStage = await finaliseStage(activeStage.id)
      setStage(updatedStage)
      const workspace = await getWorkspace(id)
      setCurrentWorkspace(workspace)
      setStages(workspace.stages)
      void refreshLatestStoryboard(true)
      // Auto-advance to the next stage now that it's unlocked
      const nextIndex = STAGE_ORDER.indexOf(finalisedType) + 1
      if (nextIndex < STAGE_ORDER.length) {
        const nextStage = workspace.stages.find(
          (s) => s.type === STAGE_ORDER[nextIndex],
        )
        if (nextStage && nextStage.status !== "locked") {
          setActiveStageId(nextStage.id)
        }
      }
    } catch (err) {
      // Surface the backend's structured gate 409 (`detail.message` /
      // `detail.recovery.message`) verbatim instead of the old blanket
      // draft-only copy. The status-branch ValueError ("…cannot be finalised")
      // is a plain-string detail and is surfaced as-is; the generic fallback
      // only applies when no structured detail is present (issue #28, Phase 1).
      setGenericError(getApiErrorMessage(err, "Only draft stages can be finalised."))
    } finally {
      finaliseInFlightRef.current = false
    }
  }, [
    activeStage,
    guardWorkspaceMutation,
    handleAcknowledgeStale,
    id,
    refreshLatestStoryboard,
    setCurrentWorkspace,
    setGenericError,
    setStage,
    setStages,
  ])

  const handleContentChange = useCallback(
    async (content: string) => {
      if (!activeStage || workspaceGenerationLock.locked) return
      if (content === (activeStage.content ?? "")) return
      setStage({ ...activeStage, content })
      setEvalResults((existing) => ({ ...existing, [activeStage.id]: null }))
      try {
        const updatedStage = await updateStageContent(activeStage.id, content)
        setStage(updatedStage)
      } catch {
        setGenericError("Could not save the latest edit.")
      }
    },
    [activeStage, setGenericError, setStage, workspaceGenerationLock.locked],
  )

  const handleRevalidateTasks = useCallback(async () => {
    if (!activeStage || activeStage.type !== "tasks") return
    if (guardWorkspaceMutation()) return
    try {
      const fresh = await revalidateTasks(activeStage.id)
      setEvalResults((existing) => ({ ...existing, [activeStage.id]: fresh }))
    } catch {
      setGenericError("Could not re-validate tasks.")
    }
  }, [activeStage, guardWorkspaceMutation])

  const handleExport = useCallback(async () => {
    if (!id || !canExport || isExporting) return

    setIsExporting(true)
    try {
      let blob: Blob
      let filename: string
      if (allFinalised) {
        blob = await exportWorkspace(id)
        filename = `specforge-${id}.zip`
      } else {
        const content = [
          `# ${currentWorkspace?.name ?? "SpecForge Workspace"}`,
          "",
          "## Problem Statement",
          "",
          problemDraft,
          "",
          ...stages
            .filter((stage) => stage.content?.trim())
            .flatMap((stage) => [
              `## ${STAGE_LABELS[stage.type]}`,
              "",
              stage.content ?? "",
              "",
            ]),
        ].join("\n")
        blob = new Blob([content], { type: "text/markdown;charset=utf-8" })
        filename = `specforge-${id}-draft.md`
      }
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setGenericError("Export failed. Try again after saving the latest edits.")
    } finally {
      setIsExporting(false)
    }
  }, [id, canExport, isExporting, allFinalised, currentWorkspace?.name, problemDraft, stages])

  const handlePdfExport = useCallback(async () => {
    if (!id || isPdfExporting || !allFinalised) return
    setIsPdfExporting(true)
    setShowExportMenu(false)
    try {
      const blob = await exportWorkspacePdf(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = `specforge-${(currentWorkspace?.name ?? id).toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60) || "workspace"}.pdf`
      a.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 1_500)
    } catch (exc) {
      showAlert(
        actionAlertFromMessage({
          title: "PDF export failed",
          message: getApiErrorMessage(exc, "Could not generate the PDF."),
          recovery: "Your workspace is saved. Open the export menu and try again.",
          source: "Export",
          primaryAction: {
            label: "Open export menu",
            onSelect: () => setShowExportMenu(true),
          },
        }),
      )
    } finally {
      setIsPdfExporting(false)
    }
  }, [id, isPdfExporting, allFinalised, currentWorkspace?.name, showAlert])

  const handleAgentTargetChange = useCallback(async (target: TargetAgent) => {
    if (!id || isUpdatingAgentTarget) return
    setIsUpdatingAgentTarget(true)
    try {
      const workspace = await updateWorkspace(id, { target_agent: target })
      setCurrentWorkspace(workspace)
    } catch (error) {
      setGenericError(getApiErrorMessage(error, "Could not update agent instructions."))
    } finally {
      setIsUpdatingAgentTarget(false)
    }
  }, [id, isUpdatingAgentTarget, setCurrentWorkspace, setGenericError])

  const handleAgentInstructionsDownload = useCallback(async (target: TargetAgent) => {
    if (!id || !allFinalised || agentDownloadTarget) return
    setAgentDownloadTarget(target)
    try {
      const blob = await downloadAgentInstructions(id, target)
      const filename = target === "codex"
        ? "AGENTS.md"
        : target === "claude_code"
          ? "CLAUDE.md"
          : "specforge-agent-instructions.zip"
      saveBlob(blob, filename)
    } catch (error) {
      setGenericError(getApiErrorMessage(error, "Agent-instruction download failed."))
    } finally {
      setAgentDownloadTarget(null)
    }
  }, [id, allFinalised, agentDownloadTarget, setGenericError])

  // Demo Day handoff bundle (plan §8). Reuses the standard ZIP export — which,
  // for a demo_day workspace, already carries the operating manual +
  // CONSTRUCTION_REPORT.md and re-runs the construction verdict server-side when
  // it is stale (export_service.build_export → ensure_fresh_verdict). After the
  // download we re-fetch the workspace so the freshly-recomputed verdict updates
  // the badge/panel (this is the §7.3 on-demand re-run, no extra endpoint).
  const handleDownloadHandoffBundle = useCallback(async () => {
    if (!id || isDownloadingBundle || !allFinalised) return
    setIsDownloadingBundle(true)
    try {
      const blob = await exportWorkspace(id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `specforge-${id}-demo-day.zip`
      link.click()
      URL.revokeObjectURL(url)
      // Pull the server-refreshed verdict so a stale badge turns fresh.
      await fetchWorkspace(id)
    } catch (exc) {
      showAlert(
        actionAlertFromMessage({
          title: "Handoff bundle download failed",
          message: getApiErrorMessage(exc, "Could not build the handoff bundle."),
          recovery: "Your workspace is saved. Try the download again in a moment.",
          source: "Export",
        }),
      )
    } finally {
      setIsDownloadingBundle(false)
    }
  }, [id, isDownloadingBundle, allFinalised, fetchWorkspace, showAlert])

  const handleCreateStoryboard = useCallback(async () => {
    if (!id || storyboardActionInFlightRef.current) return

    if (!canCreateStoryboard || hasStaleStoryboardPrerequisite) {
      setStoryboardGenerationFailure(
        "All four source stages must be finalised before creating a Storyboard.",
      )
      return
    }

    storyboardActionInFlightRef.current = true
    setStoryboardAction("generate")
    setStoryboardMessage(null)
    setStoryboardGenerationFailure(null)

    try {
      const created = await generateStoryboard(id)
      setLatestStoryboard(created)
      setShowCreateStoryboard(false)

      if (created.status === "ready") {
        setStoryboardMessage({
          kind: "success",
          text: "Storyboard is ready to present.",
        })
        navigate(`/storyboards/${created.id}`, { state: { workspaceId: id } })
      } else if (created.status === "failed") {
        setStoryboardGenerationFailure("Storyboard generation failed.")
        showAlert(
          actionAlertFromMessage({
            title: "Storyboard generation failed",
            message: "Credits were refunded and you can try again.",
            recovery: "Your finalised workspace stages are still available.",
            source: "Storyboard",
            primaryAction: {
              label: "Try again",
              onSelect: () => setShowCreateStoryboard(true),
            },
          }),
        )
      } else {
        storyboardAutoOpenRef.current = created.id
        setStoryboardMessage({
          kind: "info",
          text: "Storyboard generation started. This workspace will open the deck when it is ready.",
        })
      }
    } catch (error) {
      const message = getApiErrorMessage(
        error,
        "Storyboard generation failed. If credits were deducted, the backend refund path restores them.",
      )
      setStoryboardGenerationFailure(message)
      showAlert(
        actionAlertFromMessage({
          title: "Storyboard generation failed",
          message,
          recovery:
            "If credits were deducted, the backend refund path restores them.",
          source: "Storyboard",
          primaryAction: {
            label: "Try again",
            onSelect: () => setShowCreateStoryboard(true),
          },
        }),
      )
    } finally {
      storyboardActionInFlightRef.current = false
      setStoryboardAction(null)
    }
  }, [
    id,
    canCreateStoryboard,
    hasStaleStoryboardPrerequisite,
    navigate,
    showAlert,
  ])

  const handleOpenStoryboard = useCallback(() => {
    if (!latestStoryboard || latestStoryboard.status === "failed") return
    navigate(`/storyboards/${latestStoryboard.id}`, { state: { workspaceId: id } })
  }, [latestStoryboard, navigate, id])

  const handlePresentStoryboard = useCallback(() => {
    if (
      !latestStoryboard ||
      (latestStoryboard.status !== "ready" && latestStoryboard.status !== "stale")
    ) {
      return
    }
    navigate(`/storyboards/${latestStoryboard.id}?present=1`, {
      state: { workspaceId: id },
    })
  }, [latestStoryboard, navigate, id])

  const handleRegenerateStoryboard = useCallback(async () => {
    if (!latestStoryboard || storyboardActionInFlightRef.current) return

    storyboardActionInFlightRef.current = true
    setStoryboardAction("regenerate")
    setStoryboardMessage(null)
    setStoryboardGenerationFailure(null)

    try {
      const regenerating = await regenerateStoryboard(latestStoryboard.id)
      setLatestStoryboard(regenerating)

      if (regenerating.status === "ready") {
        setStoryboardMessage({
          kind: "success",
          text: "Storyboard regeneration finished.",
        })
        navigate(`/storyboards/${regenerating.id}`, { state: { workspaceId: id } })
      } else if (regenerating.status === "failed") {
        setStoryboardGenerationFailure("Storyboard regeneration failed.")
        showAlert(
          actionAlertFromMessage({
            title: "Storyboard regeneration failed",
            message:
              "Credits were refunded and the previous ready deck remains available.",
            recovery: "Try regeneration again when you are ready.",
            source: "Storyboard",
            primaryAction: {
              label: "Try again",
              onSelect: () => {
                void handleRegenerateStoryboard()
              },
            },
          }),
        )
        await refreshLatestStoryboard(true)
      } else {
        storyboardAutoOpenRef.current = regenerating.id
        setStoryboardMessage({
          kind: "info",
          text: "Storyboard regeneration started. The current ready deck remains available until a new version is ready.",
        })
      }
    } catch (error) {
      showAlert(
        actionAlertFromMessage({
          title: "Storyboard regeneration failed",
          message: getApiErrorMessage(
            error,
            "Storyboard regeneration failed. Credits are refunded if the backend cannot complete the paid run.",
          ),
          recovery: "The previous ready deck remains available.",
          source: "Storyboard",
          primaryAction: {
            label: "Try again",
            onSelect: () => {
              void handleRegenerateStoryboard()
            },
          },
        }),
      )
    } finally {
      storyboardActionInFlightRef.current = false
      setStoryboardAction(null)
    }
  }, [latestStoryboard, navigate, refreshLatestStoryboard, id, showAlert])

  const handleShareStoryboard = useCallback(async () => {
    if (
      !latestStoryboard ||
      latestStoryboard.status !== "ready" ||
      storyboardActionInFlightRef.current
    ) {
      return
    }

    storyboardActionInFlightRef.current = true
    setStoryboardAction("share")
    setStoryboardMessage(null)

    try {
      const share = await shareStoryboard(latestStoryboard.id, {
        allow_pdf_download: true,
        allow_notes_download: false,
        allow_appendix_download: false,
        allow_source_layer: false,
      })
      setLatestStoryboard({
        ...latestStoryboard,
        public_share_enabled: share.enabled,
        public_share_slug: share.slug,
        permissions: share.permissions,
      })
      try {
        await navigator.clipboard.writeText(share.url)
        setStoryboardMessage({
          kind: "success",
          text: "Share link enabled with private materials hidden by default and copied to clipboard.",
        })
      } catch {
        setStoryboardMessage({
          kind: "success",
          text: `Share link enabled with private materials hidden by default: ${share.url}`,
        })
      }
    } catch (error) {
      showAlert(
        actionAlertFromMessage({
          title: "Share link could not be enabled",
          message: getApiErrorMessage(error, "Could not enable the Storyboard share link."),
          recovery: "The current Storyboard remains private until sharing succeeds.",
          source: "Storyboard",
          primaryAction: {
            label: "Try again",
            onSelect: () => {
              void handleShareStoryboard()
            },
          },
        }),
      )
    } finally {
      storyboardActionInFlightRef.current = false
      setStoryboardAction(null)
    }
  }, [latestStoryboard, showAlert])

  const handleDownloadStoryboard = useCallback(
    async (kind: StoryboardDownloadKind) => {
      if (!latestStoryboard || storyboardActionInFlightRef.current) return
      if (
        latestStoryboard.status !== "ready" &&
        latestStoryboard.status !== "stale"
      ) {
        return
      }

      storyboardActionInFlightRef.current = true
      setStoryboardAction(kind === "notes" ? "notes" : "download")
      setStoryboardMessage(null)

      try {
        const blob = await downloadStoryboard(
          latestStoryboard.id,
          kind,
          kind === "notes" ? "md" : undefined,
        )
        saveBlob(blob, storyboardFilename(latestStoryboard, kind))
      } catch (error) {
        showAlert(
          actionAlertFromMessage({
            title: "Storyboard download failed",
            message: getApiErrorMessage(error, "Storyboard download failed."),
            recovery: "Try again from the Storyboard toolbar.",
            source: "Storyboard",
            primaryAction: {
              label: "Try again",
              onSelect: () => {
                void handleDownloadStoryboard(kind)
              },
            },
          }),
        )
      } finally {
        storyboardActionInFlightRef.current = false
        setStoryboardAction(null)
      }
    },
    [latestStoryboard, showAlert],
  )

  useEffect(() => {
    if (!showExportMenu) return
    function handleClickOutside(e: MouseEvent) {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target as Node)) {
        setShowExportMenu(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [showExportMenu])

  if (isLoading) {
    return (
      <div className="workspace-center">
        {featureFlags.brandedLoaders ? (
          <BrandLoader variant="block" size="lg" label="Loading workspace…" />
        ) : (
          <div className="loading-ring" />
        )}
      </div>
    )
  }

  if (!currentWorkspace || !activeStage) {
    return (
      <div className="workspace-center">
        <p className="text-sm text-ink-text-muted">Workspace unavailable.</p>
      </div>
    )
  }

  const evalResult = evalResults[activeStage.id] ?? activeStage.eval_result ?? null
  const isEvalError = evalError[activeStage.id] ?? false
  // When the eval badge says "Ready" while the critic left suggestions for the
  // same version, explain the split instead of showing two silently
  // contradictory signals (audit theme 1).
  const judgeReconciliationNote = deriveJudgeReconciliationNote(
    evalResult,
    advisoryFindings,
  )
  const showStaleWarning = activeStage.status === "stale"
  const upstreamType = previousStageType(activeStage.type)
  const taskIssues = evalResult?.tasks_without_ref ?? []
  const genuineGapIssues = taskIssues.filter(
    (i) => !i.gap_type || i.gap_type === "GENUINE_GAP"
  )
  // Deferred-coverage notes are non-blocking but still surfaced — reserve the
  // panel for them too so the harness's recorded deferral stays visible.
  const deferredCoverageIssues = taskIssues.filter(
    (i) => i.gap_type === "DEFERRED_COVERAGE"
  )
  // The right column is reserved ONLY when something substantive renders in it.
  // For harness that means actual coverage gaps — CoveragePanel returns null on a
  // fully-covered ("ready") harness, so gating on `evalResult !== null` reserved a
  // 380px column that rendered empty (the right-side vacant band). Gate on the gap
  // count, mirroring the tasks branch, so a clean harness gets the full width.
  // Coverage gaps are the deterministic deferred_reqs only — the same set
  // CoveragePanel renders. The judge's uncovered_reqs is truncation-poisoned and
  // no longer surfaced (issue: false coverage gaps, D-1), so counting it here
  // would reserve the 380px rail for a panel that renders nothing.
  const harnessCoverageGaps = evalResult?.deferred_reqs?.length ?? 0
  // Demo Day: the handoff panel lives on the tasks pane and is always worth a
  // rail column (it carries the bundle download + verdict even before the
  // verifier has run). Without this the rail would stay collapsed and the panel
  // would never render (the §9 silent-no-op integration point).
  const showDemoDayHandoff = isDemoDayWorkspace && activeStage.type === "tasks"
  const hasVersionHistory = activeStage.current_version > 1
  const showRightPanel =
    Boolean(diffResult) ||
    showDemoDayHandoff ||
    hasVersionHistory ||
    (activeStage.type === "harness" && harnessCoverageGaps > 0) ||
    (activeStage.type === "tasks" &&
      (genuineGapIssues.length > 0 ||
        deferredCoverageIssues.length > 0 ||
        githubSync.data !== null))
  const showQualitySignal =
    evalResult !== null || isEvalError || activeStage.status === "in_progress"
  const showConstructionSignal =
    isDemoDayWorkspace &&
    activeStage.type === "tasks" &&
    constructionVerdict !== null &&
    constructionVerdict !== undefined
  const showTaskValidationSignals =
    activeStage.type === "tasks" && evalResult !== null
  const showStageHeaderSummary =
    showQualitySignal || showConstructionSignal || showTaskValidationSignals
  // A finalised stage stays read-only until the user explicitly unlocks it.
  // The header swaps Edit for that rollback action, which remains available
  // unless another generation currently owns the workspace action lock.
  const isStageFinalised = activeStage.status === "finalised"
  const stageEditActionDisabled = workspaceGenerationLock.locked
  const stageEditActionDisabledReason = workspaceGenerationLock.locked
    ? workspaceLockReason
    : undefined
  const finalisedCount = stages.filter((stage) => stage.status === "finalised").length
  const readiness = stages.length === 0 ? 0 : Math.round((finalisedCount / stages.length) * 100)
  const currentStageIndex = STAGE_ORDER.indexOf(activeStage.type)
  const nextStage =
    stages.find((stage) => STAGE_ORDER.indexOf(stage.type) > currentStageIndex) ??
    activeStage
  const nextStageLabel =
    activeStage.type === "tasks" && activeStage.status === "finalised"
      ? "EXPORT"
      : STAGE_LABELS[nextStage.type]
  const activeIssueCount =
    activeStage.type === "harness"
      ? evalResult?.deferred_reqs?.length ?? 0
      : activeStage.type === "tasks"
        ? genuineGapIssues.length
        : evalResult?.flagged
          ? 1
          : 0
  // Distinct wording from the "Quality: Ready" row below on purpose — that row
  // reports the content-eval verdict, this one reports the review gate, and
  // the design review found both rows saying the bare word "Ready" for two
  // different facts on the same finalised workspace (2026-07 remediation).
  const sidebarGateLabel =
    activeStage.status === "finalised"
      ? "Gate passed"
      : activeIssueCount > 0
        ? `${activeIssueCount} flagged`
        : activeStage.status === "in_progress"
          ? "Generating"
          : "No blockers"
  const activeWordCount = activeStage.content?.trim()
    ? activeStage.content.trim().split(/\s+/).length
    : 0
  const selectedContentRatio =
    selection && activeStage.content
      ? selection.text.length / Math.max(activeStage.content.length, 1)
      : 0
  const isLargeRefineSelection = selectedContentRatio > 0.8
  const activeRefineMode =
    REFINE_MODE_OPTIONS.find((option) => option.mode === refineMode) ??
    REFINE_MODE_OPTIONS[0]
  // Findings-derived status instead of the old `N/100` number (issue #27
  // Phase 1, Decision C). The numeric score is no longer a user-facing signal.
  const qualityStatus = deriveQualityStatus(evalResult, {
    error: isEvalError,
    checking: activeStage.status === "in_progress",
  })
  const sidebarSignals = [
    ["Quality", qualityStatus ? QUALITY_STATUS_LABEL[qualityStatus] : "Not run"],
    ["Output", activeWordCount === 0 ? "No draft yet" : `${activeWordCount.toLocaleString()} words`],
  ]
  const isStoryboardBusy = storyboardAction !== null
  const storyboardProgressText =
    latestStoryboard?.status === "generating"
      ? "Storyboard generation is running. You can keep working here while status refreshes."
      : isStoryboardLoading
        ? "Checking Storyboard status..."
        : null

  const pdfDisabledReason = allFinalised
    ? undefined
    : (() => {
        const blocker = STAGE_ORDER.find(
          (t) => stages.find((s) => s.type === t)?.status !== "finalised",
        )
        return blocker
          ? `Finalise ${STAGE_LABELS[blocker]} to enable PDF export.`
          : "Finalise all stages to enable PDF export."
      })()

  return (
    <div className="workspace-shell">
      {/* Ambient background */}
      <div className="ambient-field" style={{ opacity: 0.35 }} aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
      </div>

      {/* Sidebar (an off-canvas drawer below ~1024px — see .workspace-sidebar-toggle) */}
      {isMobileNavOpen && (
        <button
          type="button"
          className="workspace-sidebar-scrim"
          aria-label="Close workspace menu"
          onClick={() => setIsMobileNavOpen(false)}
        />
      )}
      <aside className={`workspace-sidebar${isMobileNavOpen ? " is-open" : ""}`}>
        <div className="workspace-sidebar-header">
          <BrandLockup variant="small" className="workspace-brand-lockup" />
        </div>
        <StageNavigator
          stages={stagesWithEval}
          activeStageId={activeStage.id}
          onSelectStage={setActiveStageId}
        />
        <div className="workspace-sidebar-insight" aria-label="Workspace progress summary">
          <div className="sidebar-insight-glow" aria-hidden="true" />
          <div className="sidebar-insight-topbar">
            <span />
            <span />
            <span />
            <strong>Workspace pulse</strong>
          </div>

          <div className="sidebar-readiness-card">
            <div>
              <span>Readiness</span>
              <strong>{readiness}%</strong>
            </div>
            {/* The percentage to the left already states this figure — the
                ring is a purely visual reinforcement, not a second reading,
                so the count moves to an aria-label instead of duplicate
                on-screen text (2026-07 design review remediation: "stop
                reporting readiness twice"). */}
            <div
              className="sidebar-readiness-ring"
              style={{ "--readiness": readiness } as CSSProperties}
              role="img"
              aria-label={`${finalisedCount} of ${stages.length} stages finalised`}
            />
          </div>

          <div className="sidebar-mini-grid">
            <div>
              <span>Now</span>
              <strong>{STAGE_LABELS[activeStage.type]}</strong>
            </div>
            <div>
              <span>Next</span>
              <strong>{nextStageLabel}</strong>
            </div>
          </div>

          <div
            className={`sidebar-handoff-card${
              activeStage.status === "finalised" ? " is-quiet" : ""
            }`}
          >
            <div>
              <span>Review gate</span>
              <strong>{sidebarGateLabel}</strong>
            </div>
            <em>{formatStageStatus(activeStage.status)}</em>
          </div>

          <div className="sidebar-signal-stack">
            {sidebarSignals.map(([label, value]) => (
              <div key={label} className="sidebar-signal-row">
                <span aria-hidden="true" />
                <div>
                  <strong>{label}</strong>
                  <p>{value}</p>
                </div>
              </div>
            ))}
          </div>

          <div className="sidebar-pipeline-trace" aria-hidden="true">
            {stages.map((stage, index) => (
              <span
                key={stage.id}
                className={[
                  stage.status === "finalised" ? "done" : "",
                  stage.id === activeStage.id ? "active" : "",
                ].filter(Boolean).join(" ")}
                style={{ animationDelay: `${index * 0.08}s` }}
              />
            ))}
          </div>
        </div>
        <AiDisclaimer variant="sidebar" className="workspace-sidebar-disclaimer" />
      </aside>

      {/* Main */}
      <main className="workspace-main">
        {/* Header */}
        <header className="workspace-header">
          <button
            type="button"
            className="workspace-sidebar-toggle"
            onClick={() => setIsMobileNavOpen((open) => !open)}
            aria-label={isMobileNavOpen ? "Close workspace menu" : "Open workspace menu"}
            aria-expanded={isMobileNavOpen}
          >
            <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
          <h1 className="workspace-title">{currentWorkspace.name}</h1>
          <div className="workspace-header-actions">
            <div className="workspace-credit-pill" aria-label="Available credits">
              <span className="workspace-credit-label">Credits</span>
              <strong className="workspace-credit-value">
                {balance === null ? "—" : animatedBalance}
              </strong>
            </div>
            <div className="ws-export-wrap" ref={exportMenuRef}>
              <button
                type="button"
                className={`ws-export-trigger ${allFinalised ? "ready" : ""}`}
                onClick={() => setShowExportMenu((v) => !v)}
                aria-haspopup="menu"
                aria-expanded={showExportMenu}
              >
                <DownloadIcon />
                <span>Export</span>
                <svg className="ws-chevron" viewBox="0 0 10 6" fill="none" aria-hidden="true">
                  <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {showExportMenu && (
                <div className="ws-export-menu" role="menu">
                  <label className="ws-export-item" htmlFor="workspace-agent-target">
                    <span>Bundle instructions</span>
                    <select
                      id="workspace-agent-target"
                      aria-label="Bundle agent instructions"
                      value={currentWorkspace?.target_agent ?? "codex"}
                      disabled={isUpdatingAgentTarget}
                      onChange={(event) => void handleAgentTargetChange(event.target.value as TargetAgent)}
                    >
                      <option value="codex">AGENTS.md</option>
                      <option value="claude_code">CLAUDE.md</option>
                      <option value="both">Both files</option>
                    </select>
                  </label>
                  <button
                    type="button"
                    role="menuitem"
                    className="ws-export-item"
                    disabled={!canExport || isExporting}
                    onClick={() => { void handleExport(); setShowExportMenu(false) }}
                    aria-label="Download ZIP"
                  >
                    <DownloadIcon />
                    <span>{isExporting ? "Exporting…" : "ZIP"}</span>
                  </button>
                  {(["codex", "claude_code", "both"] as const).map((target) => (
                    <button
                      key={target}
                      type="button"
                      role="menuitem"
                      className="ws-export-item"
                      disabled={!allFinalised || agentDownloadTarget !== null}
                      onClick={() => void handleAgentInstructionsDownload(target)}
                    >
                      <DownloadIcon />
                      <span>
                        {target === "codex"
                          ? "Download AGENTS.md"
                          : target === "claude_code"
                            ? "Download CLAUDE.md"
                            : "Download both instruction files"}
                      </span>
                    </button>
                  ))}
                  <button
                    type="button"
                    role="menuitem"
                    className={`ws-export-item ${allFinalised ? "ready" : ""}`}
                    disabled={!allFinalised || isPdfExporting}
                    data-tooltip={!allFinalised ? pdfDisabledReason : undefined}
                    onClick={() => void handlePdfExport()}
                    aria-label="Export PDF"
                  >
                    <PDFIcon />
                    <span>{isPdfExporting ? "Generating PDF…" : "PDF"}</span>
                  </button>
                  <div
                    className="ws-export-item-wrap"
                    data-tooltip={!isGitHubConnected ? "Connect GitHub in Settings to export" : undefined}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      data-testid="workspace-github-btn"
                      className={`ws-export-item ${allFinalised && isGitHubConnected ? "ready" : ""}`}
                      disabled={!canExport || !isGitHubConnected}
                      onClick={() => { setShowGitHubExport(true); setShowExportMenu(false) }}
                      aria-label="Export to GitHub"
                    >
                      <GitHubIcon />
                      <span>GitHub</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
            <button
              type="button"
              className={`workspace-share-btn ${allFinalised ? "ready" : ""}`}
              disabled={!allFinalised}
              onClick={() => setShowShareModal(true)}
              aria-label="Share publicly"
              title={allFinalised ? "Share a read-only link" : "Finalise all stages to share"}
            >
              <ShareIcon />
              <span>Share</span>
            </button>
          </div>
        </header>

        {/* Horizontal stage stepper — shown only below the mobile breakpoint,
            replacing the vertical rail (which the drawer above hides there). */}
        <div className="workspace-mobile-stepper">
          <StageNavigator
            stages={stagesWithEval}
            activeStageId={activeStage.id}
            onSelectStage={setActiveStageId}
            orientation="horizontal"
          />
        </div>

        {/* Banners */}
        {showStaleWarning && (
          <StalenessWarning
            stage={activeStage}
            upstreamStageType={STAGE_LABELS[upstreamType]}
            onRegenerate={() => void requestGeneration("regenerate")}
            onDismiss={() => void handleAcknowledgeStale()}
            disabled={workspaceGenerationLock.locked}
            disabledReason={workspaceLockReason}
          />
        )}

        {workspaceGenerationLock.locked && (
          <div className="ws-banner ws-lock" role="status" aria-live="polite">
            <span className="ws-lock-spinner" aria-hidden="true" />
            <div className="ws-lock-copy">
              <span className="ws-lock-headline">
                {workspaceGenerationLock.message}
                <span className="ws-lock-dots" aria-hidden="true" />
              </span>
              <span id="workspace-lock-action-reason" className="ws-lock-detail">
                {workspaceGenerationLock.detail} {workspaceLockReason}
              </span>
            </div>
          </div>
        )}

        {largeSelectionWarning && (
          <div className="ws-banner ws-warning">
            <span>Large selection — consider Regenerate instead of Refine.</span>
            <div className="flex shrink-0 gap-3">
              <button
                type="button"
                onClick={() => setLargeSelectionWarning(false)}
                disabled={workspaceGenerationLock.locked}
                title={workspaceGenerationLock.locked ? workspaceLockReason : undefined}
                aria-describedby={workspaceGenerationLock.locked ? "workspace-lock-action-reason" : undefined}
                className="text-xs underline opacity-75 hover:opacity-100"
              >
                Proceed
              </button>
              <button
                type="button"
                onClick={() => { void rejectDiff(); void requestGeneration("regenerate") }}
                className="gen-btn-primary gen-btn-compact"
                disabled={workspaceGenerationLock.locked}
                title={workspaceGenerationLock.locked ? workspaceLockReason : undefined}
                aria-describedby={workspaceGenerationLock.locked ? "workspace-lock-action-reason" : undefined}
              >
                Regenerate
              </button>
            </div>
          </div>
        )}

        {storyboardMessage && (
          <div className={`storyboard-flow-message ${storyboardMessage.kind}`}>
            <span>{storyboardMessage.text}</span>
            <button
              type="button"
              onClick={() => setStoryboardMessage(null)}
              aria-label="Dismiss Storyboard status"
            >
              x
            </button>
          </div>
        )}

        {storyboardProgressText && (
          <div className="storyboard-flow-message info" role="status">
            <span>{storyboardProgressText}</span>
          </div>
        )}

        {latestStoryboard ? (
          <StoryboardToolbar
            storyboard={latestStoryboard}
            isBusy={isStoryboardBusy}
            openLabel="Open"
            openAriaLabel="Open Storyboard"
            onOpen={handleOpenStoryboard}
            onPresent={handlePresentStoryboard}
            onShare={handleShareStoryboard}
            onDownload={() => void handleDownloadStoryboard("pdf")}
            onRegenerate={() => void handleRegenerateStoryboard()}
            onDownloadNotes={() => void handleDownloadStoryboard("notes")}
          />
        ) : shouldShowCreateStoryboardCta ? (
          <section className="storyboard-entry-card" aria-label="Storyboard creation">
            <div>
              <span className="storyboard-status-badge ready">Ready</span>
              <strong>Product keynote is unlocked</strong>
              <p>
                All four stages are finalised. Create a browser-native Storyboard
                with architecture reveal, notes, downloads, and sharing.
              </p>
            </div>
            <button
              type="button"
              className="gen-btn-primary"
              aria-label="Create Storyboard"
              onClick={() => {
                setStoryboardGenerationFailure(null)
                setShowCreateStoryboard(true)
              }}
	            >
	              Create
	            </button>
          </section>
        ) : null}

        {activeGate ? (
          <StreamingOverlay
            isVisible={false}
            gate={activeGate}
            onRegenerate={handleGateRegenerate}
            onOverride={handleGateOverride}
            onDismiss={handleGateDismiss}
            actionsDisabled={workspaceGenerationLock.locked}
            disabledReason={workspaceLockReason}
          />
        ) : qualityGateBlocked ? (
          // Findings panel collapsed via "Hide details" — the blocked state
          // persists as a slim, re-expandable notice off the stage object
          // (issue #28, Phase 2).
          <BlockedPartialNotice
            message={qualityGateBlockedMessage}
            label={finaliseGateBlock.label}
            onShowDetails={
              activeStage?.quality_gate ? handleGateShowDetails : undefined
            }
          />
        ) : advisoryFindings.length ? (
          // Delivered, finalisable draft with non-blocking critic suggestions
          // (issue #34). Never blocks finalisation.
          <AdvisoryFindingsPanel
            findings={advisoryFindings}
            stageType={activeStage.type}
            onRegenerate={handleGateRegenerate}
            actionsDisabled={workspaceGenerationLock.locked}
            disabledReason={workspaceLockReason}
            reconciliationNote={judgeReconciliationNote}
          />
        ) : null}

        {/* Finalised stages keep their rollback action beside the document
            title. Avoid a full-width action band containing only "Unlock". */}
        {activeStage.status !== "finalised" && (
          <div className="generate-bar">
            <GenerateBar
              stage={activeStage}
              onGenerate={() => void requestGeneration("generate")}
              onRegenerate={() => void requestGeneration("regenerate")}
              onRefine={requestRefine}
              onFinalise={handleFinalise}
              onUnlock={() => void performRollback(activeStage.current_version)}
              isBusy={isGenerationBusy}
              busyOperation={activeBusyOperation}
              busyLabel={workspaceGenerationLock.busyLabel || undefined}
              qualityGateBlocked={qualityGateBlocked}
              qualityGateBlockedMessage={qualityGateBlockedMessage}
            />
          </div>
        )}

        {/* Refine input */}
        {showRefineInput && (
          <form
            className="refine-bar"
            onSubmit={(e) => { e.preventDefault(); void runRefine() }}
          >
            <div className="refine-mode-toggle" aria-label="Refine scope">
              {REFINE_MODE_OPTIONS.map((option) => (
                <button
                  key={option.mode}
                  type="button"
                  className={refineMode === option.mode ? "active" : ""}
                  onClick={() => setRefineMode(option.mode)}
                  disabled={isGenerationBusy}
                  title={isGenerationBusy ? workspaceLockReason : undefined}
                  aria-describedby={isGenerationBusy ? "workspace-lock-action-reason" : undefined}
                >
                  <strong>{option.label}</strong>
                  <span>{option.detail}</span>
                </button>
              ))}
            </div>
            {isLargeRefineSelection && refineMode !== "full" && (
              <div className="refine-selection-advice" role="status">
                <strong>Large selection</strong>
                <span>Regenerate may produce a cleaner result.</span>
              </div>
            )}
            <input
              value={refineInstruction}
              onChange={(e) => setRefineInstruction(e.target.value)}
              maxLength={20000}
              placeholder="Describe how to refine the selected text…"
              className="refine-input"
              disabled={isGenerationBusy}
              title={isGenerationBusy ? workspaceLockReason : undefined}
              aria-describedby={isGenerationBusy ? "workspace-lock-action-reason" : undefined}
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowRefineInput(false)}
              className="gen-btn-secondary refine-cancel-btn"
              disabled={isGenerationBusy}
              title={isGenerationBusy ? workspaceLockReason : undefined}
              aria-describedby={isGenerationBusy ? "workspace-lock-action-reason" : undefined}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="gen-btn-primary refine-submit-btn"
              disabled={isGenerationBusy}
              title={isGenerationBusy ? workspaceLockReason : undefined}
              aria-describedby={isGenerationBusy ? "workspace-lock-action-reason" : undefined}
            >
              <span>
                {activeBusyOperation === "focused-patch"
                  ? "Preparing patch..."
                  : activeRefineMode.submitLabel}
              </span>
              {activeBusyOperation !== "focused-patch" && (
                <span className="refine-credit-cost">3 credits</span>
              )}
            </button>
          </form>
        )}

        {showRefineHint && (
          <div className="refine-hint-inline">
            <div className="refine-hint-icon" aria-hidden="true">✦</div>
            <div>
              <strong>Highlight text to refine</strong>
              <span>Switch to Edit mode, select the exact sentence or section, then run Refine.</span>
            </div>
            <button
              type="button"
              className="refine-hint-close"
              onClick={() => setShowRefineHint(false)}
              aria-label="Dismiss refine hint"
            >
              ✕
            </button>
          </div>
        )}

        {/* Editor + comparison panels */}
        {activeStage.type === "spec" ? (
          <div className="spec-compare-grid">
            <div className="spec-source-column">
              <ProblemStatementPanel
                stage={activeStage}
                problemStatement={problemDraft}
                isDirty={problemDirty}
                readOnly={workspaceGenerationLock.locked}
                readOnlyReason={workspaceLockInlineReason}
                onChange={(value) => {
                  if (workspaceGenerationLock.locked) return
                  setProblemDraft(value)
                  setProblemDirty(true)
                }}
                onBlur={() => void saveProblemStatement()}
                footer={
                  <ResearchConsentToggle
                    workspaceId={currentWorkspace.id}
                    enabled={currentWorkspace.brave_research_enabled ?? false}
                    disabled={workspaceGenerationLock.locked}
                    onChanged={(enabled) =>
                      setCurrentWorkspace({
                        ...currentWorkspace,
                        brave_research_enabled: enabled,
                      })
                    }
                  />
                }
              />
              <VersionHistoryPanel
                stage={activeStage}
                onRollback={performRollback}
                disabled={workspaceGenerationLock.locked}
                disabledReason={workspaceLockReason}
              />
            </div>

            <section className="workspace-document-card spec-document-card">
              <div className="workspace-pane-header workspace-stage-pane-header">
                <div className="workspace-stage-header-topline">
                  <div className="workspace-pane-left">
                    <h2 className="workspace-pane-title spec-pane-title">Generated Spec</h2>
                    <div className="ws-pane-chips">
                      <span className={`workspace-status-chip ${activeStage.status}`}>
                        {formatStageStatus(activeStage.status)}
                      </span>
                      <BlockedPartialBadge stage={activeStage} />
                      {workspaceGenerationLock.locked && (
                        <span className="workspace-lock-chip">Editing paused</span>
                      )}
                    </div>
                  </div>
                  {!diffResult && (
                    <StageEditAction
                      stage={activeStage}
                      isEditing={specViewMode === "edit"}
                      onToggleEdit={() =>
                        setSpecViewMode((m) => (m === "edit" ? "preview" : "edit"))
                      }
                      onUnlock={() => void performRollback(activeStage.current_version)}
                      disabled={stageEditActionDisabled}
                      disabledReason={stageEditActionDisabledReason}
                      describedBy={
                        workspaceGenerationLock.locked
                          ? "workspace-lock-action-reason"
                          : undefined
                      }
                    />
                  )}
                </div>
                {showQualitySignal && (
                  <div className="workspace-stage-header-summary">
                    <div className="workspace-pane-actions">
                      <QualityBadge
                        evalResult={evalResult}
                        error={isEvalError}
                        checking={activeStage.status === "in_progress"}
                      />
                    </div>
                  </div>
                )}
              </div>
              <div className="spec-card-body">
                {diffResult ? (
                  <DiffViewer
                    diff={diffResult.diff}
                    original={diffResult.original}
                    proposed={diffResult.proposed}
                    onAccept={acceptDiff}
                    onReject={rejectDiff}
                    disabled={workspaceGenerationLock.locked}
                    disabledReason={workspaceLockReason}
                  />
                ) : isActiveStageBusy || (specViewMode === "edit" && !isStageFinalised) ? (
                  <StageEditor
                    key={`${activeStage.id}-${activeStage.status}`}
                    ref={editorRef}
                    stageId={activeStage.id}
                    initialContent={activeStage.content ?? ""}
                    readOnly={workspaceGenerationLock.locked}
                    readOnlyReason={workspaceLockInlineReason}
                    onContentChange={handleContentChange}
                  />
                ) : !activeStage.content?.trim() ? (
                  <StageEmptyState stageType={activeStage.type} creditCost={CREDIT_COSTS.generate} />
                ) : (
                  <div className="document-markdown-scroll">
                    <MarkdownRenderer content={activeStage.content ?? ""} />
                  </div>
                )}
                <StreamingOverlay
                  isVisible={Boolean(activeGenerationActivity)}
                  activity={activeGenerationActivity}
                  progress={activeStreamProgress}
                  compact={hasLiveDraft}
                />
              </div>
            </section>
          </div>
        ) : (
          <div
            className="workspace-stage-grid"
            style={!showRightPanel ? { gridTemplateColumns: "minmax(0, 1fr)" } : undefined}
          >
            <section className="workspace-document-card workspace-stage-document">
              <div className="workspace-pane-header workspace-stage-pane-header">
                <div className="workspace-stage-header-topline">
                  <div className="workspace-pane-left">
                    <h2 className="workspace-pane-title">{STAGE_LABELS[activeStage.type]}</h2>
                    <div className="ws-pane-chips">
                      <span className={`workspace-status-chip ${activeStage.status}`}>
                        {formatStageStatus(activeStage.status)}
                      </span>
                      <BlockedPartialBadge stage={activeStage} />
                      {workspaceGenerationLock.locked && (
                        <span className="workspace-lock-chip">Editing paused</span>
                      )}
                      {activeStage.type === "harness" && (
                        <HarnessCoverageChip
                          coverage_summary={currentWorkspace.coverage_summary ?? null}
                        />
                      )}
                      {effortSummary && (
                        <span
                          className="effort-summary-chip"
                          title="S = 0.5–1d · M = 1–3d · L = 3–7d · XL = 7d+ · informational only"
                          aria-label={`Effort summary: ${formatEffortSummaryChip(effortSummary)}`}
                        >
                          <strong className="effort-summary-chip-estimate">
                            {effortSummary.estimateRange}
                          </strong>
                          <span aria-hidden="true"> · </span>
                          {effortSummary.totalTasks} tasks
                          <span aria-hidden="true"> · </span>
                          {effortSummary.mustCount} MUST
                        </span>
                      )}
                    </div>
                  </div>
                  <StageEditAction
                    stage={activeStage}
                    isEditing={isEditMode}
                    onToggleEdit={() => setIsEditMode((m) => !m)}
                    onUnlock={() => void performRollback(activeStage.current_version)}
                    disabled={stageEditActionDisabled}
                    disabledReason={stageEditActionDisabledReason}
                    describedBy={
                      workspaceGenerationLock.locked
                        ? "workspace-lock-action-reason"
                        : undefined
                    }
                  />
                </div>
                {showStageHeaderSummary && (
                  <div className="workspace-stage-header-summary">
                    <div className="workspace-pane-actions">
                      <QualityBadge
                        evalResult={evalResult}
                        error={isEvalError}
                        checking={activeStage.status === "in_progress"}
                      />
                      {/* Workspace-level construction verdict — surfaced on the tasks
                          pane (where the verifier runs) for a Demo Day workspace. */}
                      {isDemoDayWorkspace && activeStage.type === "tasks" && (
                        <ConstructionVerifiedBadge
                          verdict={constructionVerdict}
                          stages={stages}
                        />
                      )}
                      {activeStage.type === "tasks" &&
                        evalResult !== null &&
                        genuineGapIssues.length === 0 && (
                          <span className="ws-validation-ok-chip">✓ All tasks valid</span>
                        )}
                      {activeStage.type === "tasks" && evalResult !== null && (
                        <button
                          type="button"
                          className="ws-view-toggle ws-view-toggle-compact"
                          onClick={handleRevalidateTasks}
                          disabled={workspaceGenerationLock.locked}
                          title={workspaceGenerationLock.locked ? workspaceLockReason : undefined}
                          aria-describedby={
                            workspaceGenerationLock.locked
                              ? "workspace-lock-action-reason"
                              : undefined
                          }
                        >
                          Re-validate
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="stage-card-body">
                {(isEditMode && !isStageFinalised) || isActiveStageBusy ? (
                  <StageEditor
                    key={`${activeStage.id}-${activeStage.status}`}
                    ref={editorRef}
                    stageId={activeStage.id}
                    initialContent={activeStage.content ?? ""}
                    readOnly={workspaceGenerationLock.locked}
                    readOnlyReason={workspaceLockInlineReason}
                    onContentChange={handleContentChange}
                  />
                ) : !activeStage.content?.trim() ? (
                  <StageEmptyState stageType={activeStage.type} creditCost={CREDIT_COSTS.generate} />
                ) : activeStage.type === "tasks" ? (
                  <TasksBoard content={activeStage.content ?? ""} />
                ) : (
                  <div className="document-markdown-scroll">
                    <MarkdownRenderer
                      content={activeStage.content ?? ""}
                      variant={activeStage.type === "harness" ? "harness" : "default"}
                    />
                  </div>
                )}
                <StreamingOverlay
                  isVisible={Boolean(activeGenerationActivity)}
                  activity={activeGenerationActivity}
                  progress={activeStreamProgress}
                  compact={hasLiveDraft}
                />
              </div>
            </section>

            {showRightPanel && (
              <aside className="workspace-right-panel min-h-0">
                {diffResult ? (
                  <div className="workspace-diff-panel">
                    <DiffViewer
                      diff={diffResult.diff}
                      original={diffResult.original}
                      proposed={diffResult.proposed}
                      onAccept={acceptDiff}
                      onReject={rejectDiff}
                      disabled={workspaceGenerationLock.locked}
                      disabledReason={workspaceLockReason}
                    />
                  </div>
                ) : (
                  <>
                    {showDemoDayHandoff && (
                      <DemoDayHandoffPanel
                        verdict={constructionVerdict}
                        stages={stages}
                        targetAgent={currentWorkspace?.target_agent}
                        onDownloadBundle={() =>
                          void handleDownloadHandoffBundle()
                        }
                        downloading={isDownloadingBundle}
                        downloadDisabled={!allFinalised}
                        downloadDisabledReason={
                          allFinalised
                            ? undefined
                            : "Finalise all four stages to download the handoff bundle."
                        }
                      />
                    )}
                    <CoveragePanel
                      stage={activeStage}
                      evalResult={evalResult}
                      // A finalised harness is locked against regeneration: the
                      // gap/expansion patch is a regeneration, so the button is
                      // disabled until the user unlocks the stage (restore a
                      // version → draft). The backend rejects it either way
                      // (stage_not_generatable); this just stops the user
                      // clicking a button that only errors.
                      disabled={
                        workspaceGenerationLock.locked ||
                        activeStage.status === "finalised"
                      }
                      disabledReason={
                        activeStage.status === "finalised"
                          ? "Finalised — unlock this stage to patch or expand coverage."
                          : workspaceLockReason
                      }
                      onRegenerate={() => void requestGapPatch()}
                    />
                    <TaskValidationPanel
                      stage={activeStage}
                      evalResult={evalResult}
                      disabled={workspaceGenerationLock.locked}
                      disabledReason={workspaceLockReason}
                      onNavigateToHarness={(() => {
                        const h = stages.find((s) => s.type === "harness")
                        return h ? () => setActiveStageId(h.id) : undefined
                      })()}
                    />
                    <VersionHistoryPanel
                      stage={activeStage}
                      onRollback={performRollback}
                      disabled={workspaceGenerationLock.locked}
                      disabledReason={workspaceLockReason}
                    />
                    {/* Tasks-stage only — matches useGitHubSync's `enabled` so
                        the panel never renders (and never sticks on its loading
                        skeleton) on the harness stage that shares this aside. */}
                    {activeStage.type === "tasks" && (
                      <TaskCompletionPanel
                        data={githubSync.data}
                        repoFullName={githubSync.repoFullName}
                        repoUrl={githubSync.repoUrl}
                        connection={githubSync.connection}
                        loading={githubSync.loading}
                        resyncing={githubSync.resyncing}
                        onResync={() => {
                          if (guardWorkspaceMutation()) return
                          void githubSync.resync()
                        }}
                        refreshing={githubSync.refreshing}
                        refreshError={githubSync.refreshError}
                        onRefresh={() => void githubSync.refreshFromGitHub()}
                        disabled={workspaceGenerationLock.locked}
                        disabledReason={workspaceLockReason}
                        detailHref={id ? `/workspace/${id}/github` : undefined}
                      />
                    )}
                    {/* The living-workspace timeline: only once the baseline is
                        finalised and a GitHub App install is live (an increment
                        is a delta on a shipped baseline). */}
                    {activeStage.type === "tasks" &&
                      allFinalised &&
                      githubSync.connection === "connected" &&
                      id && (
                        <IncrementTimeline
                          workspaceId={id}
                          enabled
                          hasBaselinePush={githubSync.data !== null}
                          disabled={workspaceGenerationLock.locked}
                          disabledReason={workspaceLockReason}
                        />
                      )}
                  </>
                )}
              </aside>
            )}
          </div>
        )}
      </main>

      {pendingClarify && id && (
        <SpecClarificationModal
          workspaceId={id}
          mode={pendingClarify.mode}
          existingAnswers={
            pendingClarify.mode === "existing" ? savedClarificationAnswers : undefined
          }
          onProceed={handleClarifyProceed}
          onCancel={handleClarifyCancel}
        />
      )}

      {pendingCredit && (
        <CreditConfirmModal
          action={pendingCredit.action}
          creditCost={CREDIT_COSTS[pendingCredit.action]}
          currentBalance={balance ?? 0}
          onConfirm={confirmCredits}
          onCancel={() => setPendingCredit(null)}
        />
      )}

      {pendingReview && activeStage && (
        <HumanReviewGate
          fromStageType={STAGE_LABELS[upstreamType]}
          toStageType={
            STAGE_LABELS[stageMap[pendingReview.stageId]?.type ?? activeStage.type]
          }
          onProceed={proceedThroughReviewGate}
          onClose={() => setPendingReview(null)}
          disabled={workspaceGenerationLock.locked}
          disabledReason={workspaceLockReason}
        />
      )}

      {showGitHubExport && id && (
        <ExportGitHubModal
          workspaceId={id}
          workspaceName={currentWorkspace?.name ?? ""}
          taskCount={taskCount}
          onClose={() => setShowGitHubExport(false)}
        />
      )}

      {showShareModal && id && currentWorkspace && (
        <SharePublicLinkModal
          workspaceId={id}
          initialEnabled={Boolean(currentWorkspace.public_share_enabled)}
          initialSlug={currentWorkspace.public_share_slug ?? null}
          onClose={() => setShowShareModal(false)}
        />
      )}

      <CreateStoryboardModal
        open={showCreateStoryboard}
        stages={stages}
        currentBalance={balance}
        isPending={storyboardAction === "generate"}
        failureMessage={storyboardGenerationFailure}
        generateStoryboard={handleCreateStoryboard}
        onClose={() => {
          if (storyboardAction !== "generate") {
            setShowCreateStoryboard(false)
          }
        }}
      />

    </div>
  )
}
