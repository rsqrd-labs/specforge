export type PipelineTrackStageState = "done" | "current" | "upcoming"

export interface PipelineTrackStage {
  id: string
  number: string
  label: string
  state: PipelineTrackStageState
}

interface PipelineStageTrackProps {
  stages: PipelineTrackStage[]
  size?: "default" | "large"
}

/**
 * The 4-stage Spec/Plan/Harness/Tasks progress indicator, shared between the
 * dashboard's "continue" panel (large) and each WorkspaceCard (default) so a
 * workspace's stage state has exactly one visual source of truth instead of
 * being independently restated by each surface.
 */
export function PipelineStageTrack({ stages, size = "default" }: PipelineStageTrackProps) {
  return (
    <div className={`pipeline-stage-track${size === "large" ? " large" : ""}`}>
      {stages.map((stage, i) => (
        <div className="pipeline-stage-track-segment" key={stage.id}>
          {i > 0 && <div className={`pipeline-stage-track-rule ${stages[i - 1].state}`} />}
          <div className={`pipeline-stage-track-node ${stage.state}`}>
            {stage.state === "done" ? (
              <svg viewBox="0 0 20 20" focusable="false" aria-hidden="true">
                <path d="M5.5 10.3 8.4 13.2 14.5 6.8" />
              </svg>
            ) : (
              <span>{stage.number}</span>
            )}
            <span className="pipeline-stage-track-label">{stage.label}</span>
          </div>
        </div>
      ))}
    </div>
  )
}
