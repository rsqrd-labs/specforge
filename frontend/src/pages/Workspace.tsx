import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react"
import { useParams } from "react-router-dom"
import { CoveragePanel } from "../components/workspace/CoveragePanel"
import { CreditConfirmModal, CREDIT_COSTS } from "../components/workspace/CreditConfirmModal"
import { DiffViewer } from "../components/workspace/DiffViewer"
import { GenerateBar } from "../components/workspace/GenerateBar"
import { HumanReviewGate } from "../components/workspace/HumanReviewGate"
import { QualityBadge } from "../components/workspace/QualityBadge"
import { StageEditor, type StageEditorHandle } from "../components/workspace/StageEditor"
import { StageNavigator } from "../components/workspace/StageNavigator"
import { StalenessWarning } from "../components/workspace/StalenessWarning"
import { StreamingOverlay } from "../components/workspace/StreamingOverlay"
import { MarkdownRenderer } from "../components/workspace/MarkdownRenderer"
import { ProblemStatementPanel } from "../components/workspace/ProblemStatementPanel"
import { TaskValidationPanel } from "../components/workspace/TaskValidationPanel"
import { PROVIDERS } from "../config/providers"
import { useCredits } from "../hooks/useCredits"
import { useStream } from "../hooks/useStream"
import {
  acceptStageDiff,
  acknowledgeReviewGate,
  exportWorkspace,
  finaliseStage,
  getStageEval,
  getApiErrorMessage,
  getWorkspace,
  refineStage,
  rejectStageDiff,
  updateWorkspace,
  updateStageContent,
} from "../services/api"
import { useStageStore } from "../store/stageStore"
import { useWorkspaceStore } from "../store/workspaceStore"
import type { EvalResult, RefineResponse, Stage, StageType } from "../types/stage"

const STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

const STAGE_LABELS: Record<StageType, string> = {
  spec: "SPEC",
  plan: "PLAN",
  harness: "HARNESS",
  tasks: "TASKS",
}

const REFINE_MODE_OPTIONS = [
  {
    mode: "focused",
    label: "Focused patch",
    detail: "Smallest safe edit",
  },
  {
    mode: "section",
    label: "Section rewrite",
    detail: "Broader local pass",
  },
  {
    mode: "full",
    label: "Full stage regenerate",
    detail: "Deliberate replacement",
  },
] as const

type CreditAction = "generate" | "regenerate"

interface PendingCreditAction {
  action: CreditAction
  stageId: string
}

function firstUnlockedStage(stages: Stage[]): Stage | null {
  return (
    STAGE_ORDER.map((type) => stages.find((stage) => stage.type === type)).find(
      (stage) => stage && stage.status !== "locked",
    ) ?? null
  )
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

function formatProviderModel(providerId: string, modelId: string): string {
  const provider = PROVIDERS.find((candidate) => candidate.id === providerId)
  const model = provider?.models.find((candidate) => candidate.id === modelId)

  return `${provider?.name ?? titleCaseIdentifier(providerId)} / ${
    model?.name ?? modelId
  }`
}

function titleCaseIdentifier(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
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
  const editorRef = useRef<StageEditorHandle>(null)
  const { currentWorkspace, isLoading, fetchWorkspace, setCurrentWorkspace } =
    useWorkspaceStore()
  const { stages: stageMap, setStage, setStages } = useStageStore()
  const { balance } = useCredits()
  const animatedBalance = useAnimatedNumber(balance)

  const [activeStageId, setActiveStageId] = useState<string | null>(null)
  const [pendingCredit, setPendingCredit] = useState<PendingCreditAction | null>(
    null,
  )
  const [pendingReview, setPendingReview] = useState<PendingCreditAction | null>(
    null,
  )
  const [refineInstruction, setRefineInstruction] = useState("")
  const [refineMode, setRefineMode] = useState<"focused" | "section" | "full">(
    "focused",
  )
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
  const [dismissedStale, setDismissedStale] = useState<Record<string, boolean>>(
    {},
  )
  const [error, setError] = useState<string | null>(null)
  const [showRefineHint, setShowRefineHint] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [specViewMode, setSpecViewMode] = useState<"preview" | "edit">("preview")
  const [problemDraft, setProblemDraft] = useState("")
  const [problemDirty, setProblemDirty] = useState(false)

  const activeStage = activeStageId ? stageMap[activeStageId] : null
  const { start: startStream, isStreaming, error: streamError } = useStream(
    activeStage?.id ?? null,
  )

  const stages = useMemo(() => {
    const workspaceStageIds = new Set(
      currentWorkspace?.stages.map((stage) => stage.id) ?? [],
    )
    return sortStages(
      Object.values(stageMap).filter((stage) => workspaceStageIds.has(stage.id)),
    )
  }, [currentWorkspace?.stages, stageMap])

  const allFinalised =
    stages.length === STAGE_ORDER.length &&
    stages.every((stage) => stage.status === "finalised")
  const canExport =
    allFinalised ||
    stages.some((stage) => Boolean(stage.content?.trim())) ||
    Boolean(problemDraft.trim())
  const creditFillPercent =
    balance === null ? 0 : Math.max(0, Math.min((balance / 100) * 100, 100))
  const providerModelLabel = currentWorkspace
    ? formatProviderModel(currentWorkspace.provider, currentWorkspace.model)
    : ""

  useEffect(() => {
    if (id) {
      void fetchWorkspace(id)
    }
  }, [id, fetchWorkspace])

  useEffect(() => {
    if (!currentWorkspace) return

    setStages(currentWorkspace.stages)
    setActiveStageId((existing) => {
      if (existing && currentWorkspace.stages.some((stage) => stage.id === existing)) {
        return existing
      }
      return firstUnlockedStage(currentWorkspace.stages)?.id ?? null
    })

    const seededEvalResults = Object.fromEntries(
      currentWorkspace.stages.map((stage) => [stage.id, stage.eval_result ?? null]),
    )
    setEvalResults((existing) => ({ ...seededEvalResults, ...existing }))
    setProblemDraft(currentWorkspace.problem_statement)
    setProblemDirty(false)
  }, [currentWorkspace, setStages])

  useEffect(() => {
    if (!activeStage || activeStage.status !== "finalised") return

    let cancelled = false
    getStageEval(activeStage.id)
      .then((result) => {
        if (!cancelled) {
          setEvalResults((existing) => ({ ...existing, [activeStage.id]: result }))
        }
      })
      .catch(() => undefined)

    return () => {
      cancelled = true
    }
  }, [activeStage?.id, activeStage?.status])

  useEffect(() => {
    if (streamError) {
      setError(streamError)
    }
  }, [streamError])

  useEffect(() => {
    if (!showRefineHint) return
    const t = setTimeout(() => setShowRefineHint(false), 5000)
    return () => clearTimeout(t)
  }, [showRefineHint])

  useEffect(() => {
    setIsEditMode(false)
    setSpecViewMode("preview")
  }, [activeStageId])

  const refreshWorkspace = useCallback(async () => {
    if (!id) return
    const workspace = await getWorkspace(id)
    setCurrentWorkspace(workspace)
    setStages(workspace.stages)
  }, [id, setCurrentWorkspace, setStages])

  const saveProblemStatement = useCallback(async () => {
    if (!id || !currentWorkspace || !problemDirty) return true

    const trimmed = problemDraft.trim()
    if (trimmed.length < 50) {
      setError("Problem statement needs at least 50 characters before saving.")
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
      setError(
        getApiErrorMessage(error, "Could not save the problem statement."),
      )
      return false
    }
  }, [
    id,
    currentWorkspace,
    problemDirty,
    problemDraft,
    setCurrentWorkspace,
    setStages,
  ])

  // Declared before confirmCredits/proceedThroughReviewGate which call it
  const runGeneration = useCallback(
    async (action: "generate" | "regenerate") => {
      setError(null)
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
    },
    [startStream, setStage, refreshWorkspace],
  )

  const requestGeneration = useCallback(
    async (action: "generate" | "regenerate") => {
      if (!activeStage) return
      if (activeStage.type === "spec") {
        const saved = await saveProblemStatement()
        if (!saved) return
      }
      setPendingCredit({ action, stageId: activeStage.id })
    },
    [activeStage, saveProblemStatement],
  )

  const requestRefine = useCallback(() => {
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
    setError(null)
  }, [activeStage])

  const confirmCredits = useCallback(async () => {
    if (!pendingCredit) return

    const stage = stageMap[pendingCredit.stageId]
    if (!stage) return

    if (stage.type !== "spec" && !stage.review_gate_acknowledged) {
      setPendingReview(pendingCredit)
      setPendingCredit(null)
      return
    }

    const nextAction = pendingCredit.action
    setPendingCredit(null)

    await runGeneration(nextAction)
  }, [pendingCredit, stageMap, runGeneration])

  const proceedThroughReviewGate = useCallback(async () => {
    if (!pendingReview) return

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
      setError("Could not acknowledge the review gate.")
    }
  }, [pendingReview, stageMap, setStage, runGeneration])

  const runRefine = useCallback(async () => {
    if (!activeStage || !selection || !refineInstruction.trim()) {
      setError("Add an instruction before refining.")
      return
    }

    try {
      const currentContent = editorRef.current?.getContent()
      if (currentContent !== undefined && currentContent !== activeStage.content) {
        const savedStage = await updateStageContent(activeStage.id, currentContent)
        setStage(savedStage)
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
    } catch {
      setError("Refine failed. Check your selection and try again.")
    }
  }, [activeStage, selection, refineInstruction, refineMode, setStage])

  const acceptDiff = useCallback(
    async (proposed: string) => {
      if (!activeStage) return
      const updatedStage = await acceptStageDiff(activeStage.id, proposed)
      setStage(updatedStage)
      setDiffResult(null)
      setLargeSelectionWarning(false)
    },
    [activeStage, setStage],
  )

  const rejectDiff = useCallback(async () => {
    if (!activeStage) {
      setDiffResult(null)
      return
    }

    await rejectStageDiff(activeStage.id)
    setDiffResult(null)
    setLargeSelectionWarning(false)
  }, [activeStage])

  const handleFinalise = useCallback(async () => {
    if (!activeStage || !id) return
    const finalisedType = activeStage.type
    try {
      const updatedStage = await finaliseStage(activeStage.id)
      setStage(updatedStage)
      const workspace = await getWorkspace(id)
      setCurrentWorkspace(workspace)
      setStages(workspace.stages)
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
    } catch {
      setError("Only draft stages can be finalised.")
    }
  }, [activeStage, id, setStage, setCurrentWorkspace, setStages])

  const handleContentChange = useCallback(
    async (content: string) => {
      if (!activeStage || isStreaming) return
      setStage({ ...activeStage, content })
      try {
        const updatedStage = await updateStageContent(activeStage.id, content)
        setStage(updatedStage)
      } catch {
        setError("Could not save the latest edit.")
      }
    },
    [activeStage, isStreaming, setStage],
  )

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
      setError("Export failed. Try again after saving the latest edits.")
    } finally {
      setIsExporting(false)
    }
  }, [id, canExport, isExporting, allFinalised, currentWorkspace?.name, problemDraft, stages])

  if (isLoading) {
    return (
      <div className="workspace-center">
        <div className="loading-ring" />
      </div>
    )
  }

  if (!currentWorkspace || !activeStage) {
    return (
      <div className="workspace-center">
        <p className="text-sm text-on-surface-variant">Workspace unavailable.</p>
      </div>
    )
  }

  const evalResult = evalResults[activeStage.id] ?? activeStage.eval_result ?? null
  const showStaleWarning =
    activeStage.status === "stale" && !dismissedStale[activeStage.id]
  const upstreamType = previousStageType(activeStage.type)
  const taskIssues = evalResult?.tasks_without_ref ?? []
  const showRightPanel =
    Boolean(diffResult) ||
    (activeStage.type === "harness" && evalResult !== null) ||
    (activeStage.type === "tasks" && taskIssues.length > 0)
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
      ? evalResult?.uncovered_reqs?.length ?? 0
      : activeStage.type === "tasks"
        ? taskIssues.length
        : evalResult?.flagged
          ? 1
          : 0
  const sidebarGateLabel =
    activeStage.status === "finalised"
      ? "Gate passed"
      : activeIssueCount > 0
        ? `${activeIssueCount} flagged`
        : activeStage.status === "in_progress"
          ? "Generating"
          : "Ready"
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
  const sidebarSignals = [
    [
      "Quality",
      evalResult?.overall_score === null || evalResult?.overall_score === undefined
        ? "Awaiting eval"
        : `${evalResult.overall_score}/100`,
    ],
    ["Output", activeWordCount === 0 ? "No draft yet" : `${activeWordCount.toLocaleString()} words`],
  ]

  return (
    <div className="workspace-shell">
      {/* Ambient background */}
      <div className="ambient-field" style={{ opacity: 0.35 }} aria-hidden="true">
        <div className="ambient-band band-saffron" />
        <div className="ambient-band band-lotus" />
      </div>

      {/* Sidebar */}
      <aside className="workspace-sidebar">
        <div className="workspace-sidebar-header">
          <div className="workspace-brand-lockup">
            <span className="brand-mark brand-mark-sm"><span>SF</span></span>
            <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
          </div>
        </div>
        <StageNavigator
          stages={stages}
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
            <div
              className="sidebar-readiness-ring"
              style={{ "--readiness": readiness } as CSSProperties}
            >
              <span>{finalisedCount}/{stages.length}</span>
            </div>
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

          <div className="sidebar-handoff-card">
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
      </aside>

      {/* Main */}
      <main className="workspace-main">
        {/* Header */}
        <header className="workspace-header">
          <div className="workspace-heading">
            <h1 className="workspace-title">{currentWorkspace.name}</h1>
          </div>
          <div className="workspace-header-actions">
            <div className="workspace-action-meta">
              <div className="workspace-stage-tag">{STAGE_LABELS[activeStage.type]}</div>
              <span className={`workspace-status-chip ${activeStage.status}`}>
                {formatStageStatus(activeStage.status)}
              </span>
              <span
                className="workspace-model-chip"
                title={providerModelLabel}
              >
                {providerModelLabel}
              </span>
            </div>
            <QualityBadge evalResult={evalResult} />
            <div className="workspace-credit-pill" aria-label="Available credits">
              <div>
                <span>Credits</span>
                <strong>{balance === null ? "—" : animatedBalance}</strong>
              </div>
              <div className="workspace-credit-meter" aria-hidden="true">
                <span style={{ width: `${creditFillPercent}%` }} />
              </div>
            </div>
            <button
              type="button"
              disabled={!canExport || isExporting}
              onClick={handleExport}
              className={`workspace-export-btn ${allFinalised ? "ready" : ""}`}
            >
              {isExporting ? "Exporting…" : "Export"}
            </button>
          </div>
        </header>

        {/* Banners */}
        {showStaleWarning && (
          <StalenessWarning
            stage={activeStage}
            upstreamStageType={STAGE_LABELS[upstreamType]}
            onRegenerate={() => void requestGeneration("regenerate")}
            onDismiss={() =>
              setDismissedStale((existing) => ({ ...existing, [activeStage.id]: true }))
            }
          />
        )}

        {error && (
          <div className="ws-banner ws-error">
            <span>{error}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-xs opacity-60 hover:opacity-100"
            >
              ✕
            </button>
          </div>
        )}

        {largeSelectionWarning && (
          <div className="ws-banner ws-warning">
            <span>Large selection — consider Regenerate instead of Refine.</span>
            <div className="flex shrink-0 gap-3">
              <button
                type="button"
                onClick={() => setLargeSelectionWarning(false)}
                className="text-xs underline opacity-75 hover:opacity-100"
              >
                Proceed
              </button>
              <button
                type="button"
                onClick={() => { void rejectDiff(); void requestGeneration("regenerate") }}
                className="gen-btn-primary gen-btn-compact"
              >
                Regenerate
              </button>
            </div>
          </div>
        )}

        {/* Generate bar */}
        <div className="generate-bar">
          <GenerateBar
            stage={activeStage}
            onGenerate={() => void requestGeneration("generate")}
            onRegenerate={() => void requestGeneration("regenerate")}
            onRefine={requestRefine}
            onFinalise={handleFinalise}
          />
        </div>

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
                >
                  <strong>{option.label}</strong>
                  <span>{option.detail}</span>
                </button>
              ))}
            </div>
            {isLargeRefineSelection && refineMode !== "full" && (
              <div className="refine-selection-advice" role="status">
                <strong>Large selection</strong>
                <span>Full stage regenerate may produce a cleaner result.</span>
              </div>
            )}
            <input
              value={refineInstruction}
              onChange={(e) => setRefineInstruction(e.target.value)}
              placeholder="Describe how to refine the selected text…"
              className="refine-input"
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowRefineInput(false)}
              className="gen-btn-secondary refine-cancel-btn"
            >
              Cancel
            </button>
            <button type="submit" className="gen-btn-primary">
              {activeRefineMode.label}
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
            <ProblemStatementPanel
              stage={activeStage}
              problemStatement={problemDraft}
              isDirty={problemDirty}
              readOnly={isStreaming}
              onChange={(value) => {
                setProblemDraft(value)
                setProblemDirty(true)
              }}
              onBlur={() => void saveProblemStatement()}
            />

            <section className="workspace-document-card spec-document-card">
              <div className="workspace-pane-header">
                <div>
                  <h2 className="workspace-pane-title spec-pane-title">Generated Spec</h2>
                  <p className="workspace-pane-subtitle">
                    Preview markdown, or edit/select text to refine.
                  </p>
                </div>
                {!isStreaming && !diffResult && (
                  <div className="document-mode-toggle" aria-label="Spec view mode">
                    <button
                      type="button"
                      className={specViewMode === "preview" ? "active" : ""}
                      onClick={() => setSpecViewMode("preview")}
                    >
                      Preview
                    </button>
                    <button
                      type="button"
                      className={specViewMode === "edit" ? "active" : ""}
                      onClick={() => setSpecViewMode("edit")}
                    >
                      Edit
                    </button>
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
                  />
                ) : isStreaming || specViewMode === "edit" ? (
                  <StageEditor
                    key={`${activeStage.id}-${activeStage.status}`}
                    ref={editorRef}
                    stageId={activeStage.id}
                    initialContent={activeStage.content ?? ""}
                    readOnly={isStreaming}
                    onContentChange={handleContentChange}
                  />
                ) : (
                  <div className="document-markdown-scroll">
                    <MarkdownRenderer content={activeStage.content ?? ""} />
                  </div>
                )}
                <StreamingOverlay isVisible={isStreaming} />
              </div>
            </section>
          </div>
        ) : (
          <div
            className="workspace-stage-grid"
            style={!showRightPanel ? { gridTemplateColumns: "minmax(0, 1fr)" } : undefined}
          >
            <section className="workspace-document-card workspace-stage-document">
              <div className="workspace-pane-header">
                <div>
                  <h2 className="workspace-pane-title">{STAGE_LABELS[activeStage.type]}</h2>
                  <p className="workspace-pane-subtitle">
                    {isEditMode ? "Edit this stage document." : "Rendered markdown preview."}
                  </p>
                </div>
                <div className="workspace-pane-actions">
                  {activeStage.type === "tasks" && evalResult !== null && taskIssues.length === 0 && (
                    <span className="ws-validation-ok-chip">✓ All tasks valid</span>
                  )}
                  {activeStage.status !== "locked" && !isStreaming && (
                    <button
                      type="button"
                      onClick={() => setIsEditMode((m) => !m)}
                      className="ws-view-toggle"
                    >
                      {isEditMode ? "Preview" : "Edit"}
                    </button>
                  )}
                </div>
              </div>
              <div className="stage-card-body">
                {isEditMode || isStreaming ? (
                  <StageEditor
                    key={`${activeStage.id}-${activeStage.status}`}
                    ref={editorRef}
                    stageId={activeStage.id}
                    initialContent={activeStage.content ?? ""}
                    readOnly={isStreaming}
                    onContentChange={handleContentChange}
                  />
                ) : (
                  <div className="document-markdown-scroll">
                    <MarkdownRenderer
                      content={activeStage.content ?? ""}
                      variant={activeStage.type === "harness" ? "harness" : "default"}
                    />
                  </div>
                )}
                <StreamingOverlay isVisible={isStreaming} />
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
                    />
                  </div>
                ) : (
                  <>
                    <CoveragePanel stage={activeStage} evalResult={evalResult} />
                    <TaskValidationPanel stage={activeStage} evalResult={evalResult} />
                  </>
                )}
              </aside>
            )}
          </div>
        )}
      </main>

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
        />
      )}

    </div>
  )
}
