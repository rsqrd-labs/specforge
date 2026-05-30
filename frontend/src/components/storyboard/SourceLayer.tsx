import { useMemo, useState } from "react"
import type {
  SourceRef,
  StoryboardPayload,
  StoryboardSharePermissions,
  StoryboardSource,
} from "../../types/storyboard"

const SOURCE_ORDER: StoryboardSource[] = ["SPEC", "PLAN", "HARNESS", "TASKS"]
const DEFAULT_EXCERPT_MAX_LENGTH = 1200

interface SourceLayerProps {
  payload: StoryboardPayload
  source_map?: Record<string, SourceRef[]>
  currentSlideId?: string | null
  isOwner?: boolean
  permissions?: Partial<StoryboardSharePermissions>
  publicView?: boolean
  maxLength?: number
  onClose?: () => void
}

function boundedExcerpt(excerpt: string, maxLength: number): string {
  if (excerpt.length <= maxLength) return excerpt
  return `${excerpt.slice(0, maxLength).trimEnd()}...`
}

function sourceEntriesForSlide(
  source_map: Record<string, SourceRef[]>,
  currentSlideId?: string | null,
): SourceRef[] {
  const entries = Object.entries(source_map)
  const scoped = currentSlideId
    ? entries.filter(([key]) => key === currentSlideId || key.startsWith(`${currentSlideId}.`))
    : entries
  return scoped.flatMap(([, refs]) => refs)
}

export function SourceLayer({
  payload,
  source_map = payload.source_map,
  currentSlideId = null,
  isOwner = false,
  permissions,
  publicView = false,
  maxLength = DEFAULT_EXCERPT_MAX_LENGTH,
  onClose,
}: SourceLayerProps) {
  const [selectedSource, setSelectedSource] = useState<StoryboardSource | null>(null)
  const canViewSources = isOwner || permissions?.allow_source_layer === true
  const refs = useMemo(
    () => sourceEntriesForSlide(source_map, currentSlideId),
    [currentSlideId, source_map],
  )

  const grouped = useMemo(
    () =>
      SOURCE_ORDER.map((source) => ({
        source,
        refs: refs.filter((ref) => ref.source === source),
      })),
    [refs],
  )
  const activeGroup =
    selectedSource === null
      ? null
      : grouped.find((group) => group.source === selectedSource) ?? null

  if (!canViewSources) {
    return (
      <aside
        className="source-layer source-layer-locked"
        aria-label="Source layer"
        data-view={publicView ? "public" : "owner"}
      >
        <div className="source-layer__header">
          <strong>Source layer</strong>
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close source panel">
              Close
            </button>
          )}
        </div>
        <p>Source excerpts require owner access or public allow_source_layer permission.</p>
      </aside>
    )
  }

  return (
    <aside
      className="source-layer"
      aria-label="Source layer"
      data-view={publicView ? "public" : "owner"}
    >
      <div className="source-layer__header">
        <div>
          <strong>Source layer</strong>
          <span>Bounded excerpts from finalised artifacts</span>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Close source panel">
            Close
          </button>
        )}
      </div>

      <div className="source-layer__badges" aria-label="Source badges">
        {grouped.map((group) => (
          <button
            key={group.source}
            type="button"
            className={selectedSource === group.source ? "active" : ""}
            onClick={() => setSelectedSource(group.source)}
            disabled={group.refs.length === 0}
          >
            {group.source}
            <span>{group.refs.length}</span>
          </button>
        ))}
      </div>

      {activeGroup ? (
        <div className="source-layer__excerpts" aria-live="polite">
          {activeGroup.refs.map((ref, index) => (
            <article key={`${ref.source_id}-${index}`}>
              <span>{ref.source_id}</span>
              <p>{boundedExcerpt(ref.excerpt, maxLength)}</p>
            </article>
          ))}
        </div>
      ) : (
        <p className="source-layer__empty">
          Select SPEC, PLAN, HARNESS, or TASKS to open bounded excerpts.
        </p>
      )}
    </aside>
  )
}
