import { useMemo } from "react"
import { AiDisclaimer } from "../shared/AiDisclaimer"
import { ArchitectureReveal } from "./ArchitectureReveal"
import type {
  StoryboardPayload,
  StoryboardPublicDownloadKind,
  StoryboardSharePermissions,
} from "../../types/storyboard"

interface StoryboardLaunchPageProps {
  title: string
  payload: StoryboardPayload
  isOwner?: boolean
  permissions?: Partial<StoryboardSharePermissions>
  downloads?: StoryboardPublicDownloadKind[]
  sharedAt?: string
  onPresent: () => void
  onDownload: () => void
  onNotes: () => void
  onShare?: () => void
}

function firstSlide(payload: StoryboardPayload) {
  return payload.sections.flatMap((section) => section.slides)[0] ?? null
}

function architectureDiagram(payload: StoryboardPayload) {
  return (
    payload.diagrams.find((diagram) => diagram.type === "architecture_reveal") ??
    payload.diagrams[0] ??
    null
  )
}

export function StoryboardLaunchPage({
  title,
  payload,
  isOwner = false,
  permissions = {},
  downloads = [],
  sharedAt,
  onPresent,
  onDownload,
  onNotes,
  onShare,
}: StoryboardLaunchPageProps) {
  const opening = useMemo(() => firstSlide(payload), [payload])
  const diagram = useMemo(() => architectureDiagram(payload), [payload])
  const canUseNotes = isOwner || permissions.allow_notes_download === true
  const canDownloadPdf =
    isOwner ||
    (permissions.allow_pdf_download === true && downloads.includes("pdf"))

  return (
    <section className="storyboard-launch" aria-label="Storyboard launch page">
      <div className="storyboard-launch__copy">
        <span>{payload.theme.motif}</span>
        <h1>{title}</h1>
        <p>{opening?.visible_text ?? opening?.headline ?? payload.theme.transition_style}</p>

        <div className="storyboard-launch__actions">
          <button type="button" onClick={onPresent}>
            Present
          </button>
          <button
            type="button"
            onClick={onDownload}
            disabled={!canDownloadPdf}
            aria-label="Download PDF"
          >
            PDF
          </button>
          <button
            type="button"
            onClick={onNotes}
            disabled={!canUseNotes}
            aria-label="Speaker Notes"
          >
            Notes
          </button>
          {onShare && (
            <button type="button" onClick={onShare}>
              Share
            </button>
          )}
        </div>

        <dl className="storyboard-launch__meta">
          <div>
            <dt>Acts</dt>
            <dd>{payload.sections.length}</dd>
          </div>
          <div>
            <dt>Downloads</dt>
            <dd>{isOwner ? "Owner" : downloads.length}</dd>
          </div>
          {sharedAt && (
            <div>
              <dt>Shared</dt>
              <dd>{new Date(sharedAt).toLocaleDateString()}</dd>
            </div>
          )}
        </dl>
        <AiDisclaimer variant="inline" className="storyboard-launch__disclaimer" />
      </div>

      <div className="storyboard-launch__architecture">
        {diagram ? (
          <ArchitectureReveal
            diagram={diagram}
            currentStep={4}
            palette={payload.theme.palette}
            title="Architecture preview"
          />
        ) : (
          <div className="storyboard-launch__architecture-empty">
            <strong>Architecture preview</strong>
            <p>{payload.theme.diagram_style}</p>
          </div>
        )}
      </div>
    </section>
  )
}
