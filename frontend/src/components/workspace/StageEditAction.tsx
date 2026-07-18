import type { Stage } from "../../types/stage"

interface StageEditActionProps {
  stage: Pick<Stage, "status" | "type">
  isEditing: boolean
  onToggleEdit: () => void
  onUnlock: () => void
  disabled?: boolean
  disabledReason?: string
  describedBy?: string
}

const STAGE_LABELS: Record<Stage["type"], string> = {
  spec: "SPEC",
  plan: "PLAN",
  harness: "HARNESS",
  tasks: "TASKS",
}

/**
 * Keeps the stage's primary document action in the document header. A
 * finalised stage cannot be edited in place, so it offers the explicit
 * rollback action instead of showing a disabled Edit button elsewhere.
 */
export function StageEditAction({
  stage,
  isEditing,
  onToggleEdit,
  onUnlock,
  disabled = false,
  disabledReason,
  describedBy,
}: StageEditActionProps) {
  if (stage.status === "locked") return null

  const stageLabel = STAGE_LABELS[stage.type]

  if (stage.status === "finalised") {
    return (
      <button
        type="button"
        className="ws-view-toggle ws-view-toggle-compact ws-stage-unlock-action"
        onClick={onUnlock}
        disabled={disabled}
        title={
          disabled
            ? disabledReason
            : "Return this stage to draft so it can be edited"
        }
        aria-describedby={disabled ? describedBy : undefined}
        aria-label={`Unlock ${stageLabel} to edit`}
      >
        Unlock to edit
      </button>
    )
  }

  return (
    <button
      type="button"
      className="ws-view-toggle ws-view-toggle-compact"
      onClick={onToggleEdit}
      disabled={disabled}
      title={disabled ? disabledReason : undefined}
      aria-describedby={disabled ? describedBy : undefined}
    >
      {isEditing ? "Preview" : "Edit"}
    </button>
  )
}
