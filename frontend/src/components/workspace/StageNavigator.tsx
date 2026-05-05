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
  spec: "SPEC.md",
  plan: "PLAN.md",
  harness: "HARNESS",
  tasks: "TASKS.md",
}

function StatusDot({ status }: { status: Stage["status"] }) {
  const base = "w-2 h-2 rounded-full shrink-0"
  if (status === "finalised") return <span className={`${base} bg-green-500`} />
  if (status === "locked") return <span className={`${base} bg-outline-variant`} />
  if (status === "stale")
    return (
      <span className="flex items-center gap-0.5">
        <span className={`${base} bg-secondary-container`} />
        <span className="text-xs leading-none text-secondary">⚠</span>
      </span>
    )
  return <span className={`${base} bg-primary-container`} />
}

function scoreClassName(score: number): string {
  if (score >= 80) return "text-green-600"
  if (score >= 60) return "text-on-surface-variant"
  return "text-error text-red-600"
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
    <nav className="flex flex-col gap-1 p-2">
      {STAGE_ORDER.map((type) => {
        const stage = stageMap[type]
        if (!stage) return null

        const isLocked = stage.status === "locked"
        const isActive = stage.id === activeStageId || stage.type === activeStage
        const score = stage.eval_result?.overall_score ?? null

        return (
          <button
            key={type}
            disabled={isLocked}
            onClick={() => {
              if (isLocked) return
              if (onSelectStage) onSelectStage(stage.id)
              else onSelect?.(type)
            }}
            className={[
              "flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-left transition-colors",
              isLocked
                ? "cursor-not-allowed opacity-40 text-on-surface-variant"
                : "cursor-pointer hover:bg-surface-container",
              isActive
                ? "bg-primary/10 text-on-surface font-medium ring-1 ring-primary/20"
                : "text-on-surface",
            ].join(" ")}
          >
            <StatusDot status={stage.status} />
            <span className="truncate">{STAGE_LABELS[type]}</span>
            {(score !== null || stage.status === "finalised") && (
              <span className="ml-auto flex items-center gap-2 text-xs">
                {score !== null && (
                  <span className={`font-medium ${scoreClassName(score)}`}>
                    {score}
                  </span>
                )}
                {stage.status === "finalised" && (
                  <span className="text-on-surface-variant">
                    v{stage.current_version}
                  </span>
                )}
              </span>
            )}
          </button>
        )
      })}
    </nav>
  )
}
