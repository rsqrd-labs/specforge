import { useCallback, useEffect, useMemo, useRef, useState } from "react"
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
import { TaskValidationPanel } from "../components/workspace/TaskValidationPanel"
import { useCredits } from "../hooks/useCredits"
import { useStream } from "../hooks/useStream"
import {
  acceptStageDiff,
  acknowledgeReviewGate,
  exportWorkspace,
  finaliseStage,
  getStageEval,
  getWorkspace,
  refineStage,
  rejectStageDiff,
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

export default function Workspace() {
  const { id } = useParams<{ id: string }>()
  const editorRef = useRef<StageEditorHandle>(null)
  const { currentWorkspace, isLoading, fetchWorkspace, setCurrentWorkspace } =
    useWorkspaceStore()
  const { stages: stageMap, setStage, setStages } = useStageStore()
  const { balance } = useCredits()

  const [activeStageId, setActiveStageId] = useState<string | null>(null)
  const [pendingCredit, setPendingCredit] = useState<PendingCreditAction | null>(
    null,
  )
  const [pendingReview, setPendingReview] = useState<PendingCreditAction | null>(
    null,
  )
  const [refineInstruction, setRefineInstruction] = useState("")
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
  const [isExporting, setIsExporting] = useState(false)

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

  const refreshWorkspace = useCallback(async () => {
    if (!id) return
    const workspace = await getWorkspace(id)
    setCurrentWorkspace(workspace)
    setStages(workspace.stages)
  }, [id, setCurrentWorkspace, setStages])

  // Declared before confirmCredits/proceedThroughReviewGate which call it
  const runGeneration = useCallback(
    async (action: "generate" | "regenerate") => {
      setError(null)
      const result = await startStream(action)
      if (!result) return

      setStage(result.stage)
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
    (action: "generate" | "regenerate") => {
      if (!activeStage) return
      setPendingCredit({ action, stageId: activeStage.id })
    },
    [activeStage],
  )

  const requestRefine = useCallback(() => {
    const currentSelection = editorRef.current?.getSelection()
    if (!activeStage || !currentSelection) {
      setError("Select text in the editor before refining.")
      return
    }

    setSelection(currentSelection)
    setRefineInstruction("")
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
      const result = await refineStage(activeStage.id, {
        instruction: refineInstruction.trim(),
        selection_start: selection.start,
        selection_end: selection.end,
        selected_text: selection.text,
      })
      setDiffResult(result)
      setLargeSelectionWarning(result.large_selection)
      setShowRefineInput(false)
    } catch {
      setError("Refine failed. Check your selection and try again.")
    }
  }, [activeStage, selection, refineInstruction])

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
    if (!activeStage) return
    try {
      const updatedStage = await finaliseStage(activeStage.id)
      setStage(updatedStage)
      await refreshWorkspace()
    } catch {
      setError("Only draft stages can be finalised.")
    }
  }, [activeStage, setStage, refreshWorkspace])

  const handleContentChange = useCallback(
    async (content: string) => {
      if (!activeStage || isStreaming) return
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
    if (!id || !allFinalised || isExporting) return

    setIsExporting(true)
    try {
      const blob = await exportWorkspace(id)
      const url = URL.createObjectURL(blob)
      const link = document.createElement("a")
      link.href = url
      link.download = `specforge-${id}.zip`
      link.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("Export is unavailable until all stages are finalised.")
    } finally {
      setIsExporting(false)
    }
  }, [id, allFinalised, isExporting])

  if (isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-primary" />
      </div>
    )
  }

  if (!currentWorkspace || !activeStage) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <p className="text-sm text-on-surface-variant">Workspace unavailable.</p>
      </div>
    )
  }

  const evalResult = evalResults[activeStage.id] ?? activeStage.eval_result ?? null
  const showStaleWarning =
    activeStage.status === "stale" && !dismissedStale[activeStage.id]
  const upstreamType = previousStageType(activeStage.type)

  return (
    <div className="flex min-h-screen bg-background text-on-background">
      <aside className="w-[240px] shrink-0 border-r border-outline-variant bg-surface-container-lowest/80 backdrop-blur-sm">
        <div className="border-b border-outline-variant px-4 py-3">
          <div className="mb-3 flex items-center gap-2">
            <span className="brand-mark brand-mark-sm">
              <span>SF</span>
            </span>
            <span className="brand-wordmark brand-wordmark-sm">SpecForge</span>
          </div>
          <div className="truncate text-sm font-semibold text-on-surface">
            {currentWorkspace.name}
          </div>
          <div className="mt-0.5 text-xs text-on-surface-variant">
            {balance === null ? "Credits unavailable" : `${balance} credits`}
          </div>
        </div>
        <StageNavigator
          stages={stages}
          activeStageId={activeStage.id}
          onSelectStage={setActiveStageId}
        />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex min-h-16 items-center justify-between gap-4 border-b border-outline-variant bg-surface-container-lowest/80 px-5 backdrop-blur-sm">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase text-on-surface-variant">
              {STAGE_LABELS[activeStage.type]}
            </div>
            <h1 className="truncate text-lg font-semibold text-on-surface">
              {currentWorkspace.name}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <QualityBadge evalResult={evalResult} />
            <button
              type="button"
              disabled={!allFinalised || isExporting}
              onClick={handleExport}
              className="rounded-lg border border-outline-variant px-3 py-1.5 text-sm font-semibold text-on-surface transition-colors disabled:cursor-not-allowed disabled:opacity-40 hover:bg-surface-container"
            >
              Export
            </button>
          </div>
        </header>

        {showStaleWarning && (
          <StalenessWarning
            stage={activeStage}
            upstreamStageType={STAGE_LABELS[upstreamType]}
            onRegenerate={() => requestGeneration("regenerate")}
            onDismiss={() =>
              setDismissedStale((existing) => ({
                ...existing,
                [activeStage.id]: true,
              }))
            }
          />
        )}

        {error && (
          <div className="border-b border-error/30 bg-error-container px-5 py-3 text-sm text-on-error-container">
            {error}
          </div>
        )}

        {largeSelectionWarning && (
          <div className="flex items-center justify-between gap-4 border-b border-primary-container/40 bg-primary-container/10 px-5 py-3">
            <span className="text-sm text-on-primary-container">
              This selection covers most of the document. Consider using Regenerate instead.
            </span>
            <div className="flex shrink-0 gap-2">
              <button
                type="button"
                onClick={() => setLargeSelectionWarning(false)}
                className="text-sm text-primary underline hover:text-on-primary-container"
              >
                Proceed with diff
              </button>
              <button
                type="button"
                onClick={() => {
                  void rejectDiff()
                  void requestGeneration("regenerate")
                }}
                className="rounded-lg bg-primary px-3 py-1 text-sm font-medium text-on-primary hover:opacity-90"
              >
                Use Regenerate
              </button>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 border-b border-outline-variant bg-surface-container-lowest/60 px-5 py-3">
          <GenerateBar
            stage={activeStage}
            onGenerate={() => requestGeneration("generate")}
            onRegenerate={() => requestGeneration("regenerate")}
            onRefine={requestRefine}
            onFinalise={handleFinalise}
          />
        </div>

        {showRefineInput && (
          <form
            className="flex gap-3 border-b border-outline-variant bg-surface-container-lowest/80 px-5 py-3 backdrop-blur-sm"
            onSubmit={(event) => {
              event.preventDefault()
              void runRefine()
            }}
          >
            <input
              value={refineInstruction}
              onChange={(event) => setRefineInstruction(event.target.value)}
              placeholder="Refine the selected text..."
              className="min-w-0 flex-1 rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface outline-none transition-all focus:border-primary focus:ring-2 focus:ring-primary/10"
            />
            <button
              type="button"
              onClick={() => setShowRefineInput(false)}
              className="px-3 py-2 text-sm text-on-surface-variant hover:text-on-surface"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-[0_4px_12px_rgba(143,78,0,0.2)] hover:opacity-90"
            >
              Refine
            </button>
          </form>
        )}

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_420px]">
          <section className="relative min-h-0">
            <StageEditor
              key={activeStage.id}
              ref={editorRef}
              stageId={activeStage.id}
              initialContent={activeStage.content ?? ""}
              readOnly={activeStage.status === "locked" || isStreaming}
              onContentChange={handleContentChange}
            />
            <StreamingOverlay isVisible={isStreaming} />
          </section>

          <aside className="min-h-0 overflow-auto border-l border-outline-variant bg-surface">
            {diffResult ? (
              <div className="h-full p-4">
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
        </div>
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
