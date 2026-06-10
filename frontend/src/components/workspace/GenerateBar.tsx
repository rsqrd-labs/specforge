import type { Stage } from "../../types/stage"
import type { GenerationActivityOperation } from "./StreamingOverlay"

interface GenerateBarProps {
  stage: Stage
  onGenerate: () => void
  onRegenerate: () => void
  onRefine: () => void
  onFinalise: () => void
  onUnlock: () => void
  isBusy?: boolean
  busyOperation?: GenerationActivityOperation | null
  busyLabel?: string
  qualityGateBlocked?: boolean
  qualityGateBlockedMessage?: string
}

export function GenerateBar({
  stage,
  onGenerate,
  onRegenerate,
  onRefine,
  onFinalise,
  onUnlock,
  isBusy = false,
  busyOperation = null,
  busyLabel,
  qualityGateBlocked = false,
  qualityGateBlockedMessage = "Regenerate or override the quality gate before finalising",
}: GenerateBarProps) {
  if (stage.status === "locked") return null

  const stageLabel = getStageLabel(stage.type)

  if (isBusy || stage.status === "in_progress") {
    return (
      <div className="gen-btn-streaming" role="status" aria-live="polite">
        <div className="loading-ring" />
        <span>{busyLabel ?? getBusyLabel(busyOperation)}</span>
      </div>
    )
  }

  return (
    <div className="workspace-action-row">
      {(stage.status === "draft" || stage.status === "stale") && !stage.content && (
        <button
          type="button"
          onClick={onGenerate}
          className="gen-btn-primary"
          disabled={isBusy}
          aria-label={`Generate ${stageLabel}`}
        >
          Generate
        </button>
      )}

      {stage.status === "finalised" ? (
        <button
          type="button"
          onClick={onUnlock}
          className="gen-btn-secondary"
          disabled={isBusy}
          aria-label={`Unlock ${stageLabel}`}
        >
          Unlock
        </button>
      ) : (stage.status === "stale" ||
        (stage.status === "draft" && stage.content)) ? (
        <button
          type="button"
          onClick={onRegenerate}
          className="gen-btn-secondary gen-btn-deliberate"
          disabled={isBusy}
          aria-label={`Regenerate ${stageLabel}`}
        >
          Regenerate
        </button>
      ) : null}

      {stage.content && stage.status !== "finalised" && (
        <button
          type="button"
          onClick={onRefine}
          className="gen-btn-secondary"
          aria-label={`Refine ${stageLabel}`}
          disabled={isBusy}
        >
          Refine
        </button>
      )}

      {(stage.status === "draft" || stage.status === "stale") && stage.content && (
        <button
          type="button"
          onClick={onFinalise}
          className="gen-btn-primary"
          disabled={qualityGateBlocked || isBusy}
          title={qualityGateBlocked ? qualityGateBlockedMessage : undefined}
          aria-label={`Finalise ${stageLabel}`}
        >
          Finalise
        </button>
      )}
    </div>
  )
}

function getBusyLabel(operation: GenerationActivityOperation | null) {
  switch (operation) {
    case "focused-patch":
      return "Preparing refinement..."
    case "quality-gate-regenerate":
      return "Regenerating with gate feedback..."
    case "regenerate-gaps":
      return "Regenerating coverage gaps..."
    case "regenerate":
      return "Regenerating stage..."
    case "generate":
    default:
      return "Generating stage..."
  }
}

function getStageLabel(stageType: Stage["type"]) {
  switch (stageType) {
    case "spec":
      return "SPEC"
    case "plan":
      return "PLAN"
    case "harness":
      return "HARNESS"
    case "tasks":
      return "TASKS"
  }
}
