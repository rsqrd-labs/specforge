import { useNavigate } from "react-router-dom"
import type { Stage } from "../../types/stage"
import type { Workspace } from "../../types/workspace"

interface WorkspaceCardProps {
  workspace: Workspace & { stages?: Stage[] }
  index?: number
}

const STAGE_ORDER = ["spec", "plan", "harness", "tasks"] as const

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
}

export function WorkspaceCard({ workspace, index = 0 }: WorkspaceCardProps) {
  const navigate = useNavigate()

  const stageMap = Object.fromEntries(
    (workspace.stages ?? []).map((s) => [s.type, s]),
  )

  const finalisedCount = STAGE_ORDER.filter(
    (type) => stageMap[type]?.status === "finalised",
  ).length

  const createdDate = new Date(workspace.created_at).toLocaleDateString(
    undefined,
    { month: "short", day: "numeric", year: "numeric" },
  )

  return (
    <button
      onClick={() => navigate(`/workspace/${workspace.id}`)}
      className="workspace-card"
      style={{ animationDelay: `${index * 0.07}s` }}
    >
      <div className="workspace-card-bar" />

      <div className="workspace-card-head">
        <span className="workspace-card-name">{workspace.name}</span>
        <span className="workspace-card-provider">
          {PROVIDER_LABELS[workspace.provider] ?? workspace.provider}
        </span>
      </div>

      <div className="workspace-card-pipeline">
        {STAGE_ORDER.map((type) => {
          const status = stageMap[type]?.status
          const pipClass =
            status === "finalised"
              ? "ws-stage-pip done"
              : status && status !== "locked"
                ? "ws-stage-pip active"
                : "ws-stage-pip"
          return <div key={type} className={pipClass} />
        })}
        <span className="workspace-stages-count">
          {finalisedCount}/{STAGE_ORDER.length} done
        </span>
      </div>

      <div className="workspace-card-footer">
        <span className="workspace-card-date">{createdDate}</span>
        <span className="workspace-card-arrow">→</span>
      </div>
    </button>
  )
}
