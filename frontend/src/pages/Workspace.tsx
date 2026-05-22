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
import { ExportGitHubModal } from "../components/workspace/ExportGitHubModal"
// ExportPDFButton — T-USE-08 contract; PDF export logic is inlined in handlePdfExport
import type { } from "../components/workspace/ExportPDFButton"
import { HarnessCoverageChip } from "../components/workspace/HarnessCoverageChip"
import { SharePublicLinkModal } from "../components/workspace/SharePublicLinkModal"
import { SpecClarificationModal } from "../components/workspace/SpecClarificationModal"
import { DownloadIcon, GitHubIcon, PDFIcon, ShareIcon } from "../components/shared/icons"
import { useCredits } from "../hooks/useCredits"
import {
  formatEffortSummaryChip,
  parseEffortSummary,
} from "../utils/tasksParser"
import { type StreamErrorState, useStream } from "../hooks/useStream"
import {
  acceptStageDiff,
  acknowledgeReviewGate,
  exportWorkspace,
  exportWorkspacePdf,
  finaliseStage,
  getStageEval,
  getApiErrorMessage,
  getGitHubIntegration,

  getWorkspace,
  refineStage,
  rejectStageDiff,
  revalidateTasks,
  rollbackStage,
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

const EVAL_POLL_ATTEMPTS = 12
const EVAL_POLL_DELAY_MS = 2500

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

const sleep = (ms: number) =>
  new Promise<void>((resolve) => window.setTimeout(resolve, ms))

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
  const exportMenuRef = useRef<HTMLDivElement>(null)
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
  const [isRefining, setIsRefining] = useState(false)
  const refineInFlightRef = useRef(false)
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
  const [error, setError] = useState<StreamErrorState | null>(null)
  const setGenericError = (message: string) => setError({ code: "generic", message })
  const [showRefineHint, setShowRefineHint] = useState(false)
  const [isExporting, setIsExporting] = useState(false)
  const [isEditMode, setIsEditMode] = useState(false)
  const [specViewMode, setSpecViewMode] = useState<"preview" | "edit">("preview")
  const [problemDraft, setProblemDraft] = useState("")
  const [problemDirty, setProblemDirty] = useState(false)
  const [isGitHubConnected, setIsGitHubConnected] = useState(false)
  const [showGitHubExport, setShowGitHubExport] = useState(false)
  const [showShareModal, setShowShareModal] = useState(false)
  const [showExportMenu, setShowExportMenu] = useState(false)
  const [isPdfExporting, setIsPdfExporting] = useState(false)
  const [pdfError, setPdfError] = useState<string | null>(null)
  const [pendingClarify, setPendingClarify] = useState<PendingCreditAction | null>(
    null,
  )

  useEffect(() => {
    let cancelled = false
    getGitHubIntegration()
      .then((g) => {
        if (!cancelled) setIsGitHubConnected(g.connected)
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

  const stages = useMemo(() => {
    const workspaceStageIds = new Set(
      currentWorkspace?.stages.map((stage) => stage.id) ?? [],
    )
    return sortStages(
      Object.values(stageMap).filter((stage) => workspaceStageIds.has(stage.id)),
    )
  }, [currentWorkspace?.stages, stageMap])
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

  // Count tasks for the GitHub modal's issue-count preview. Derived from the
  // tasks stage content via regex — no API call.
  const taskCount = useMemo(() => {
    const tasksStage = stages.find((s) => s.type === "tasks")
    if (!tasksStage?.content) return 0
    return (tasksStage.content.match(/^###\s+T-\d+:/gm) ?? []).length
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
      !activeStage.content?.trim()
    ) {
      return
    }

    const stageId = activeStage.id
    let cancelled = false

    const loadEval = async () => {
      for (let attempt = 0; attempt < EVAL_POLL_ATTEMPTS; attempt += 1) {
        try {
          const result = await getStageEval(stageId)
          if (!cancelled) {
            setEvalResults((existing) => ({ ...existing, [stageId]: result }))
          }
          return
        } catch {
          if (cancelled) {
            return
          }
          if (attempt === EVAL_POLL_ATTEMPTS - 1) {
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
  ])

  useEffect(() => {
    if (streamError) {
      if (streamError) setError(streamError)
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
    setCurrentWorkspace,
    setStages,
  ])

  // Declared before confirmCredits/proceedThroughReviewGate which call it
  const runGeneration = useCallback(
    async (action: "generate" | "regenerate" | "regenerate-gaps") => {
      setError(null)
      if (activeStage) {
        setEvalResults((existing) => ({ ...existing, [activeStage.id]: null }))
      }
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
    [activeStage, startStream, setStage, refreshWorkspace],
  )

  const requestGeneration = useCallback(
    async (action: "generate" | "regenerate") => {
      if (!activeStage) return
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
        !(currentWorkspace?.clarification_qa && currentWorkspace.clarification_qa.length > 0)
      if (needsClarification) {
        setPendingClarify({ action, stageId: activeStage.id })
        return
      }
      setPendingCredit({ action, stageId: activeStage.id })
    },
    [activeStage, currentWorkspace?.clarification_qa, saveProblemStatement],
  )

  const handleClarifyProceed = useCallback(() => {
    if (!pendingClarify) return
    const next = pendingClarify
    setPendingClarify(null)
    setPendingCredit(next)
  }, [pendingClarify])

  const handleClarifyCancel = useCallback(() => {
    setPendingClarify(null)
  }, [])

  const requestFreeRegeneration = useCallback(async () => {
    if (!activeStage) return
    await runGeneration("regenerate-gaps")
  }, [activeStage, runGeneration])

  const performRollback = useCallback(async (version: number) => {
    if (!activeStage) return
    const updated = await rollbackStage(activeStage.id, version)
    setStage(updated)
    setEvalResults((existing) => ({ ...existing, [activeStage.id]: null }))
    await refreshWorkspace()
  }, [activeStage, setStage, refreshWorkspace])

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
      setGenericError("Could not acknowledge the review gate.")
    }
  }, [pendingReview, stageMap, setStage, runGeneration])

  const runRefine = useCallback(async () => {
    if (refineInFlightRef.current) {
      return
    }
    if (!activeStage || !selection || !refineInstruction.trim()) {
      setGenericError("Add an instruction before refining.")
      return
    }

    refineInFlightRef.current = true
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
    } catch {
      setGenericError("Refine failed. Check your selection and try again.")
    } finally {
      refineInFlightRef.current = false
      setIsRefining(false)
    }
  }, [activeStage, selection, refineInstruction, refineMode, setStage])

  const acceptDiff = useCallback(
    async (proposed: string) => {
      if (!activeStage) return
      const updatedStage = await acceptStageDiff(activeStage.id, proposed)
      setStage(updatedStage)
      setEvalResults((existing) => ({ ...existing, [updatedStage.id]: null }))
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
      setGenericError("Only draft stages can be finalised.")
    }
  }, [activeStage, id, setStage, setCurrentWorkspace, setStages])

  const handleContentChange = useCallback(
    async (content: string) => {
      if (!activeStage || isStreaming) return
      setStage({ ...activeStage, content })
      setEvalResults((existing) => ({ ...existing, [activeStage.id]: null }))
      try {
        const updatedStage = await updateStageContent(activeStage.id, content)
        setStage(updatedStage)
      } catch {
        setGenericError("Could not save the latest edit.")
      }
    },
    [activeStage, isStreaming, setStage],
  )

  const handleRevalidateTasks = useCallback(async () => {
    if (!activeStage || activeStage.type !== "tasks") return
    try {
      const fresh = await revalidateTasks(activeStage.id)
      setEvalResults((existing) => ({ ...existing, [activeStage.id]: fresh }))
    } catch {
      setGenericError("Could not re-validate tasks.")
    }
  }, [activeStage])

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
    setPdfError(null)
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
      setPdfError(getApiErrorMessage(exc, "Couldn't generate PDF. Try again?"))
      setShowExportMenu(true)
    } finally {
      setIsPdfExporting(false)
    }
  }, [id, isPdfExporting, allFinalised, currentWorkspace?.name])

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
  const genuineGapIssues = taskIssues.filter(
    (i) => !i.gap_type || i.gap_type === "GENUINE_GAP"
  )
  const showRightPanel =
    Boolean(diffResult) ||
    (activeStage.type === "harness" && evalResult !== null) ||
    (activeStage.type === "tasks" && genuineGapIssues.length > 0)
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
        ? genuineGapIssues.length
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

      {/* Sidebar */}
      <aside className="workspace-sidebar">
        <div className="workspace-sidebar-header">
          <div className="workspace-brand-lockup">
            <span className="brand-mark brand-mark-sm"><span>SF</span></span>
            <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
          </div>
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
                  <button
                    type="button"
                    role="menuitem"
                    className="ws-export-item"
                    disabled={!canExport || isExporting}
                    onClick={() => { void handleExport(); setShowExportMenu(false) }}
                  >
                    <DownloadIcon />
                    <span>{isExporting ? "Exporting…" : "Download ZIP"}</span>
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    className={`ws-export-item ${allFinalised ? "ready" : ""}`}
                    disabled={!allFinalised || isPdfExporting}
                    data-tooltip={!allFinalised ? pdfDisabledReason : undefined}
                    onClick={() => void handlePdfExport()}
                  >
                    <PDFIcon />
                    <span>{isPdfExporting ? "Generating PDF…" : "Export PDF"}</span>
                  </button>
                  <div
                    className="ws-export-item-wrap"
                    data-tooltip={!isGitHubConnected ? "Connect GitHub in Settings to export" : undefined}
                  >
                    <button
                      type="button"
                      role="menuitem"
                      className={`ws-export-item ${allFinalised && isGitHubConnected ? "ready" : ""}`}
                      disabled={!canExport || !isGitHubConnected}
                      onClick={() => { setShowGitHubExport(true); setShowExportMenu(false) }}
                    >
                      <GitHubIcon />
                      <span>Push to GitHub</span>
                    </button>
                  </div>
                  {pdfError && (
                    <div className="ws-export-error" role="alert">
                      <span>{pdfError}</span>
                      <button
                        type="button"
                        onClick={() => { setPdfError(null); void handlePdfExport() }}
                      >
                        Retry
                      </button>
                    </div>
                  )}
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

        {error && error.code === "stage_not_generatable" ? (
          <div className="ws-banner ws-warning">
            <span>This stage is finalised — unlock it with Rollback before regenerating.</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="ws-banner-link"
            >
              Dismiss
            </button>
          </div>
        ) : error ? (
          <div className="ws-banner ws-error">
            <span>{error.message}</span>
            <button
              type="button"
              onClick={() => setError(null)}
              className="ws-banner-link"
            >
              ✕
            </button>
          </div>
        ) : null}

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
            onUnlock={() => void performRollback(activeStage.current_version)}
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
                  disabled={isRefining}
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
              maxLength={20000}
              placeholder="Describe how to refine the selected text…"
              className="refine-input"
              disabled={isRefining}
              autoFocus
            />
            <button
              type="button"
              onClick={() => setShowRefineInput(false)}
              className="gen-btn-secondary refine-cancel-btn"
              disabled={isRefining}
            >
              Cancel
            </button>
            <button type="submit" className="gen-btn-primary" disabled={isRefining}>
              {isRefining ? "Refining..." : activeRefineMode.label}
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
                <div className="workspace-pane-left">
                  <h2 className="workspace-pane-title spec-pane-title">Generated Spec</h2>
                  <div className="ws-pane-chips">
                    <span className={`workspace-status-chip ${activeStage.status}`}>
                      {formatStageStatus(activeStage.status)}
                    </span>
                  </div>
                </div>
                <div className="workspace-pane-actions">
                  <QualityBadge evalResult={evalResult} />
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
                <div className="workspace-pane-left">
                  <h2 className="workspace-pane-title">{STAGE_LABELS[activeStage.type]}</h2>
                  <div className="ws-pane-chips">
                    <span className={`workspace-status-chip ${activeStage.status}`}>
                      {formatStageStatus(activeStage.status)}
                    </span>
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
                <div className="workspace-pane-actions">
                  <QualityBadge evalResult={evalResult} />
                  {activeStage.type === "tasks" && evalResult !== null && genuineGapIssues.length === 0 && (
                    <span className="ws-validation-ok-chip">✓ All tasks valid</span>
                  )}
                  {activeStage.type === "tasks" && !isStreaming && (
                    <button
                      type="button"
                      className="ws-view-toggle"
                      onClick={handleRevalidateTasks}
                    >
                      Re-validate
                    </button>
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
                    <CoveragePanel
                      stage={activeStage}
                      evalResult={evalResult}
                      freeRegenUsed={activeStage.gap_patch_used}
                      onRegenerate={
                        activeStage.gap_patch_used
                          ? () => void requestGeneration("regenerate")
                          : () => void requestFreeRegeneration()
                      }
                    />
                    <TaskValidationPanel
                      stage={activeStage}
                      evalResult={evalResult}
                      onNavigateToHarness={(() => {
                        const h = stages.find((s) => s.type === "harness")
                        return h ? () => setActiveStageId(h.id) : undefined
                      })()}
                    />
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
        />
      )}

      {showGitHubExport && id && (
        <ExportGitHubModal
          workspaceId={id}
          workspaceName={currentWorkspace?.name ?? ""}
          isConnected={isGitHubConnected}
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

    </div>
  )
}
