import { useRef } from "react"
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
  const cardRef = useRef<HTMLButtonElement>(null)

  function handleMouseMove(e: React.MouseEvent<HTMLButtonElement>) {
    const el = cardRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const cx = rect.width / 2
    const cy = rect.height / 2
    const rotX = ((y - cy) / cy) * -7
    const rotY = ((x - cx) / cx) * 7
    el.style.transition = "box-shadow 0.22s ease, border-color 0.22s"
    el.style.transform = `perspective(700px) rotateX(${rotX}deg) rotateY(${rotY}deg) translateY(-6px) scale(1.01)`
    el.style.setProperty("--mx", `${(x / rect.width) * 100}%`)
    el.style.setProperty("--my", `${(y / rect.height) * 100}%`)
  }

  function handleMouseLeave() {
    const el = cardRef.current
    if (!el) return
    el.style.transition =
      "transform 0.5s cubic-bezier(0.16, 1, 0.3, 1), box-shadow 0.22s ease, border-color 0.22s"
    el.style.transform = ""
  }

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
      ref={cardRef}
      onClick={() => navigate(`/workspace/${workspace.id}`)}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
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
        {STAGE_ORDER.map((type, i) => {
          const status = stageMap[type]?.status
          const pipClass =
            status === "finalised"
              ? "ws-stage-pip done"
              : status && status !== "locked"
                ? "ws-stage-pip active"
                : "ws-stage-pip"
          return (
            <div
              key={type}
              className={pipClass}
              style={{ animationDelay: `${index * 0.07 + i * 0.09 + 0.1}s` }}
            />
          )
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
