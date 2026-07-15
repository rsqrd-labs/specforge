import { useRef } from "react"
import { Link } from "react-router-dom"
import type { Stage, StageStatus, StageType } from "../../types/stage"
import type { Workspace } from "../../types/workspace"
import { HarnessCoverageChip } from "../workspace/HarnessCoverageChip"
import { PipelineStageTrack, type PipelineTrackStage } from "../shared/PipelineStageTrack"

interface WorkspaceCardProps {
  workspace: Workspace & { stages?: Stage[] }
  index?: number
  isDeleting?: boolean
  onDelete?: (workspace: Workspace) => void
}

const STAGE_ORDER = ["spec", "plan", "harness", "tasks"] as const
const ACTIVE_STAGE_STATUSES: StageStatus[] = ["draft", "in_progress", "stale"]

const STAGE_LABELS: Record<StageType, string> = {
  spec: "Spec",
  plan: "Plan",
  harness: "Harness",
  tasks: "Tasks",
}

function nextStageForCard(stageMap: Partial<Record<StageType, Stage>>): Stage | null {
  const activeStage = STAGE_ORDER
    .map((type) => stageMap[type])
    .find((stage): stage is Stage =>
      Boolean(stage && ACTIVE_STAGE_STATUSES.includes(stage.status)),
    )

  if (activeStage) return activeStage

  return STAGE_ORDER
    .map((type) => stageMap[type])
    .find((stage): stage is Stage => Boolean(stage)) ?? null
}

function actionForStage(stage: Stage | null): string {
  if (!stage) return "Open workspace"
  const stageName = STAGE_LABELS[stage.type]
  if (stage.type === "tasks" && stage.status === "finalised") return "Review export"
  if (stage.status === "stale") return `Refresh ${stageName}`
  if (stage.status === "in_progress") return `Resume ${stageName}`
  if (stage.status === "finalised") return `Review ${stageName}`
  return `Continue ${stageName}`
}

function statusLabelForStage(stage: Stage | null): string {
  if (!stage) return "Ready"
  if (stage.type === "tasks" && stage.status === "finalised") return "Ready to export"
  if (stage.status === "stale") return "Needs refresh"
  if (stage.status === "in_progress") return "In progress"
  if (stage.status === "draft") return "Draft"
  if (stage.status === "locked") return "Locked"
  return "Complete"
}

export function WorkspaceCard({
  workspace,
  index = 0,
  isDeleting = false,
  onDelete,
}: WorkspaceCardProps) {
  const cardRef = useRef<HTMLDivElement>(null)

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
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
  ) as Partial<Record<StageType, Stage>>

  const finalisedCount = STAGE_ORDER.filter(
    (type) => stageMap[type]?.status === "finalised",
  ).length
  const nextStage = nextStageForCard(stageMap)
  const progressPct = Math.round((finalisedCount / STAGE_ORDER.length) * 100)

  const trackStages: PipelineTrackStage[] = STAGE_ORDER.map((type, i) => ({
    id: type,
    number: String(i + 1).padStart(2, "0"),
    label: STAGE_LABELS[type],
    state:
      stageMap[type]?.status === "finalised"
        ? "done"
        : nextStage?.type === type
          ? "current"
          : "upcoming",
  }))

  const createdDate = new Date(workspace.created_at).toLocaleDateString(
    undefined,
    { month: "short", day: "numeric", year: "numeric" },
  )

  return (
    <article
      ref={cardRef}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      className="workspace-card"
      style={{ animationDelay: `${index * 0.07}s` }}
    >
      <div className="workspace-card-bar" />

      <Link
        to={`/workspace/${workspace.id}`}
        className="workspace-card-open"
        aria-label={`Open ${workspace.name}`}
      >
        <div className="workspace-card-head">
          <span className="workspace-card-name">{workspace.name}</span>
        </div>

        <HarnessCoverageChip
          coverage_summary={workspace.coverage_summary ?? null}
        />

        <PipelineStageTrack stages={trackStages} />

        <div className="workspace-card-next">
          <div>
            <span>{statusLabelForStage(nextStage)}</span>
            <strong>{actionForStage(nextStage)}</strong>
          </div>
          <em>{progressPct}%</em>
        </div>

        <div className="workspace-card-footer">
          <span className="workspace-card-date">{createdDate}</span>
          <span className="workspace-card-arrow">→</span>
        </div>
      </Link>

      {onDelete && (
        <button
          type="button"
          className="workspace-card-delete"
          onClick={() => onDelete(workspace)}
          disabled={isDeleting}
          aria-label={`Move ${workspace.name} to trash`}
          title="Move to trash"
        >
          {isDeleting ? (
            <span className="workspace-card-delete-spinner" aria-hidden="true" />
          ) : (
            <svg viewBox="0 0 20 20" focusable="false" aria-hidden="true">
              <path d="M7.2 4.4V3.6c0-.5.4-.9.9-.9h3.8c.5 0 .9.4.9.9v.8" />
              <path d="M4.4 5.2h11.2" />
              <path d="M6 7.2l.5 8.2c.1.7.6 1.2 1.3 1.2h4.4c.7 0 1.2-.5 1.3-1.2l.5-8.2" />
              <path d="M8.8 8.9v4.8" />
              <path d="M11.2 8.9v4.8" />
            </svg>
          )}
        </button>
      )}
    </article>
  )
}
