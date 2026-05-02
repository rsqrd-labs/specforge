import { useNavigate } from "react-router-dom"
import type { Stage } from "../../types/stage"
import type { Workspace } from "../../types/workspace"

interface WorkspaceCardProps {
  workspace: Workspace & { stages?: Stage[] }
}

function StageDot({ status }: { status: Stage["status"] | undefined }) {
  if (!status || status === "locked") {
    return <div className="h-2.5 w-2.5 rounded-full border-2 border-outline-variant" />
  }
  if (status === "finalised") {
    return <div className="h-2.5 w-2.5 rounded-full bg-primary" />
  }
  return <div className="h-2.5 w-2.5 rounded-full border-2 border-secondary bg-secondary/30" />
}

const STAGE_ORDER = ["spec", "plan", "harness", "tasks"] as const

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  openai: "OpenAI",
  google: "Google",
}

export function WorkspaceCard({ workspace }: WorkspaceCardProps) {
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
      className="group relative w-full overflow-hidden rounded-xl border border-outline-variant bg-surface-container-lowest/85 p-5 text-left shadow-[0_4px_20px_rgba(47,49,49,0.07)] backdrop-blur-sm transition-all hover:-translate-y-1 hover:border-outline hover:shadow-[0_12px_40px_rgba(143,78,0,0.12)]"
    >
      <div className="absolute inset-x-0 top-0 h-[3px] rounded-t-xl bg-gradient-to-r from-primary to-secondary opacity-60 transition-opacity group-hover:opacity-100" />

      <div className="mb-3 flex items-start justify-between gap-2 pt-1">
        <h3 className="truncate pr-2 font-semibold text-on-surface">
          {workspace.name}
        </h3>
        <span className="shrink-0 rounded-full border border-outline-variant bg-surface-container-low px-2.5 py-0.5 text-xs font-semibold text-on-surface-variant">
          {PROVIDER_LABELS[workspace.provider] ?? workspace.provider}
        </span>
      </div>

      <div className="mb-4 flex items-center gap-2">
        {STAGE_ORDER.map((type) => (
          <StageDot key={type} status={stageMap[type]?.status} />
        ))}
        <span className="ml-auto text-xs font-medium text-on-surface-variant">
          {finalisedCount}/{STAGE_ORDER.length} stages
        </span>
      </div>

      <p className="text-xs text-on-surface-variant">{createdDate}</p>
    </button>
  )
}
