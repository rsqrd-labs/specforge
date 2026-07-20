import type { Stage, StageType } from "../../types/stage"

interface StageNavigatorProps {
  stages: Stage[] | Partial<Record<StageType, Stage>>
  activeStageId?: string
  activeStage?: StageType
  onSelectStage?: (stageId: string) => void
  onSelect?: (stageType: StageType) => void
  /** "horizontal" renders a numbered stepper — used below the mobile
   *  breakpoint, where the vertical rail has no room to also show content. */
  orientation?: "vertical" | "horizontal"
}

const STAGE_ORDER: StageType[] = ["spec", "plan", "harness", "tasks"]

const STAGE_LABELS: Record<StageType, string> = {
  spec: "Spec",
  plan: "Plan",
  harness: "Harness",
  tasks: "Tasks",
}

export function StageNavigator({
  stages,
  activeStageId,
  activeStage,
  onSelectStage,
  onSelect,
  orientation = "vertical",
}: StageNavigatorProps) {
  const stageMap = Array.isArray(stages)
    ? Object.fromEntries(stages.map((s) => [s.type, s]))
    : stages
  const isHorizontal = orientation === "horizontal"

  return (
    <nav
      className={isHorizontal ? "workspace-nav workspace-nav--horizontal" : "workspace-nav"}
      aria-label="Pipeline stage"
    >
      {STAGE_ORDER.map((type, i) => {
        const stage = stageMap[type]
        if (!stage) return null

        const isLocked = stage.status === "locked"
        const isActive = stage.id === activeStageId || stage.type === activeStage

        const cls = [
          "workspace-nav-item",
          isActive ? "ws-active" : "",
          isLocked ? "ws-locked" : "",
        ]
          .filter(Boolean)
          .join(" ")

        return (
          <button
            key={type}
            aria-label={`${STAGE_LABELS[type]} stage${isLocked ? " (locked)" : ""}`}
            disabled={isLocked}
            onClick={() => {
              if (isLocked) return
              if (onSelectStage) onSelectStage(stage.id)
              else onSelect?.(type)
            }}
            className={cls}
            style={{ animationDelay: `${i * 0.06}s` }}
            aria-current={isActive ? "step" : undefined}
          >
            {isHorizontal ? (
              <span className="ws-nav-step" aria-hidden="true">{i + 1}</span>
            ) : (
              <span className={`ws-nav-dot ${stage.status}`} />
            )}
            <span className="ws-nav-label">{STAGE_LABELS[type]}</span>
          </button>
        )
      })}
    </nav>
  )
}
