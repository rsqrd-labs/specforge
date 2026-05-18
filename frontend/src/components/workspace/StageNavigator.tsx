import type { Stage, StageType } from "../../types/stage"

interface StageNavigatorProps {
  stages: Stage[] | Partial<Record<StageType, Stage>>
  activeStageId?: string
  activeStage?: StageType
  onSelectStage?: (stageId: string) => void
  onSelect?: (stageType: StageType) => void
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
}: StageNavigatorProps) {
  const stageMap = Array.isArray(stages)
    ? Object.fromEntries(stages.map((s) => [s.type, s]))
    : stages

  return (
    <nav className="workspace-nav">
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
            disabled={isLocked}
            onClick={() => {
              if (isLocked) return
              if (onSelectStage) onSelectStage(stage.id)
              else onSelect?.(type)
            }}
            className={cls}
            style={{ animationDelay: `${i * 0.06}s` }}
          >
            <span className={`ws-nav-dot ${stage.status}`} />
            <span className="ws-nav-label">{STAGE_LABELS[type]}</span>
          </button>
        )
      })}
    </nav>
  )
}
