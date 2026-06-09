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
  qualityGateBlocked = false,
  qualityGateBlockedMessage = "Regenerate or override the quality gate before finalising",
}: GenerateBarProps) {
  if (stage.status === "locked") return null

  const generateLabel = getGenerateLabel(stage.type)

  if (isBusy || stage.status === "in_progress") {
    return (
      <div className="gen-btn-streaming" role="status" aria-live="polite">
        <div className="loading-ring" />
        <span>{getBusyLabel(busyOperation)}</span>
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
        >
          {generateLabel}
        </button>
      )}

      {stage.status === "finalised" ? (
        <button
          type="button"
          onClick={onUnlock}
          className="gen-btn-secondary"
          disabled={isBusy}
        >
          Unlock stage
        </button>
      ) : (stage.status === "stale" ||
        (stage.status === "draft" && stage.content)) ? (
        <button
          type="button"
          onClick={onRegenerate}
          className="gen-btn-secondary gen-btn-deliberate"
          disabled={isBusy}
        >
          Full stage regenerate
        </button>
      ) : null}

      {stage.content && stage.status !== "finalised" && (
        <button
          type="button"
          onClick={onRefine}
          className="gen-btn-secondary"
          aria-label="Focused patch refine"
          disabled={isBusy}
        >
          Focused patch
        </button>
      )}

      {(stage.status === "draft" || stage.status === "stale") && stage.content && (
        <button
          type="button"
          onClick={onFinalise}
          className="gen-btn-primary"
          disabled={qualityGateBlocked || isBusy}
          title={qualityGateBlocked ? qualityGateBlockedMessage : undefined}
        >
          Final quality pass
        </button>
      )}
    </div>
  )
}

function getBusyLabel(operation: GenerationActivityOperation | null) {
  switch (operation) {
    case "focused-patch":
      return "Preparing focused patch..."
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

function getGenerateLabel(stageType: Stage["type"]) {
  switch (stageType) {
    case "spec":
      return "Generate requirements pass"
    case "plan":
      return "Generate architecture pass"
    case "harness":
      return "Generate validation harness"
    case "tasks":
      return "Generate implementation plan"
  }
}
