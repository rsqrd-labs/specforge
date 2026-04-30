import { useNavigate } from "react-router-dom"
import type { Stage } from "../../types/stage"
import type { Workspace } from "../../types/workspace"

interface WorkspaceCardProps {
  workspace: Workspace & { stages?: Stage[] }
}

function StageDot({ status }: { status: Stage["status"] | undefined }) {
  if (!status || status === "locked") {
    return (
      <div className="w-2.5 h-2.5 rounded-full border-2 border-outline-variant" />
    )
  }
  if (status === "finalised") {
    return <div className="w-2.5 h-2.5 rounded-full bg-primary" />
  }
  return (
    <div className="w-2.5 h-2.5 rounded-full border-2 border-primary bg-primary/30" />
  )
}

const STAGE_ORDER = ["spec", "plan", "harness", "tasks"] as const

export function WorkspaceCard({ workspace }: WorkspaceCardProps) {
  const navigate = useNavigate()

  const stageMap = Object.fromEntries(
    (workspace.stages ?? []).map((s) => [s.type, s]),
  )

  const createdDate = new Date(workspace.created_at).toLocaleDateString()

  return (
    <button
      onClick={() => navigate(`/workspace/${workspace.id}`)}
      className="w-full text-left p-4 bg-surface rounded-lg border border-outline-variant hover:border-outline hover:shadow-sm transition-all"
    >
      <div className="flex items-start justify-between mb-3">
        <h3 className="font-semibold text-on-surface truncate pr-2">
          {workspace.name}
        </h3>
        <span className="text-xs px-2 py-0.5 rounded-full bg-secondary-container text-on-secondary-container shrink-0">
          {workspace.provider}
        </span>
      </div>
      <div className="flex items-center gap-1.5 mb-3">
        {STAGE_ORDER.map((type) => (
          <StageDot key={type} status={stageMap[type]?.status} />
        ))}
      </div>
      <p className="text-xs text-on-surface-variant">{createdDate}</p>
    </button>
  )
}
