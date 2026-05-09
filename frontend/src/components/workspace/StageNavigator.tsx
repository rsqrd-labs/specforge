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

function scoreClass(score: number): string {
  if (score >= 80) return "good"
  if (score >= 60) return "ok"
  return "poor"
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
        const score = stage.eval_result?.overall_score ?? null

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
            {score !== null && (
              <span className={`ws-nav-score ${scoreClass(score)}`}>{score}</span>
            )}
            {score === null && stage.status === "finalised" && (
              <span className="ws-nav-score good">✓</span>
            )}
          </button>
        )
      })}
    </nav>
  )
}
