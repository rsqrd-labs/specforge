import { useEffect, useMemo, useState } from "react"
import type {
  SpeakerNote,
  StoryboardPayload,
  StoryboardSharePermissions,
  StoryboardSlide,
} from "../../types/storyboard"

interface PresenterSlide {
  slide: StoryboardSlide
  sectionTitle: string
}

interface PresenterModeProps {
  payload: StoryboardPayload
  activeSlideIndex?: number
  isOwner?: boolean
  permissions?: Partial<StoryboardSharePermissions>
  publicView?: boolean
  onClose?: () => void
}

function flattenSlides(payload: StoryboardPayload): PresenterSlide[] {
  return payload.sections.flatMap((section) =>
    section.slides.map((slide) => ({
      slide,
      sectionTitle: section.title,
    })),
  )
}

function formatTimer(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, "0")}`
}

function noteForSlide(
  payload: StoryboardPayload,
  slide: StoryboardSlide | undefined,
): SpeakerNote | null {
  if (!slide) return null
  return payload.notes[slide.speaker_notes_ref] ?? payload.notes[slide.id] ?? null
}

function sourceBackedWalkthroughCue(note: SpeakerNote | null): string | null {
  const cue = note?.demo_cue?.trim()
  if (!cue) return null
  if (/\b(video|recorded|recording)\s+(demo|demonstration|walkthrough)\b/i.test(cue)) {
    return null
  }
  if (/\b(demo|demonstration|walkthrough)\s+video\b/i.test(cue)) return null
  return cue
}

export function PresenterMode({
  payload,
  activeSlideIndex = 0,
  isOwner = false,
  permissions,
  publicView = false,
  onClose,
}: PresenterModeProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const slides = useMemo(() => flattenSlides(payload), [payload])
  const currentIndex = Math.max(0, Math.min(activeSlideIndex, slides.length - 1))
  const current = slides[currentIndex]
  const next = slides[currentIndex + 1] ?? null
  const canViewNotes = isOwner || permissions?.allow_notes_download === true
  const note = canViewNotes ? noteForSlide(payload, current?.slide) : null
  const walkthroughCue = sourceBackedWalkthroughCue(note)

  useEffect(() => {
    setElapsedSeconds(0)
    const timer = window.setInterval(() => {
      setElapsedSeconds((value) => value + 1)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [payload, activeSlideIndex])

  if (!canViewNotes) {
    return (
      <aside
        className="presenter-mode presenter-mode-locked"
        aria-label="Presenter mode"
        data-view={publicView ? "public" : "owner"}
      >
        <div className="presenter-mode__header">
          <strong>Presenter mode</strong>
          {onClose && (
            <button type="button" onClick={onClose} aria-label="Close presenter panel">
              Close
            </button>
          )}
        </div>
        <p>Speaker notes are private unless public notes permission is enabled.</p>
      </aside>
    )
  }

  return (
    <aside
      className="presenter-mode"
      aria-label="Presenter mode"
      data-view={publicView ? "public" : "owner"}
    >
      <div className="presenter-mode__header">
        <div>
          <span>Session timer</span>
          <strong>{formatTimer(elapsedSeconds)}</strong>
        </div>
        {onClose && (
          <button type="button" onClick={onClose} aria-label="Close presenter panel">
            Close
          </button>
        )}
      </div>

      <div className="presenter-mode__grid">
        <section aria-label="Current slide">
          <span>Current</span>
          <h2>{current?.slide.headline ?? "No current slide"}</h2>
          <p>{current?.sectionTitle}</p>
        </section>

        <section aria-label="Next slide">
          <span>Next</span>
          <h2>{next?.slide.headline ?? "End of deck"}</h2>
          <p>{next?.sectionTitle ?? "Close with audience questions."}</p>
        </section>
      </div>

      <section className="presenter-mode__notes" aria-label="Speaker notes">
        <span>Speaker</span>
        <p>{note?.talk_track ?? "No speaker notes are available for this slide."}</p>
      </section>

      <dl className="presenter-mode__cues">
        <div>
          <dt>Transition</dt>
          <dd>{note?.transition ?? "Advance when the current point lands."}</dd>
        </div>
        <div>
          <dt>Pause</dt>
          <dd>{note?.pause_cue ?? "Pause briefly before the next slide."}</dd>
        </div>
        {walkthroughCue && (
          <div>
            <dt>Walkthrough</dt>
            <dd>{walkthroughCue}</dd>
          </div>
        )}
      </dl>

      <section className="presenter-mode__backup" aria-label="Backup points">
        <span>Backup</span>
        <ul>
          {(note?.backup_points.length ? note.backup_points : ["Use the appendix for deeper technical detail."]).map(
            (point) => (
              <li key={point}>{point}</li>
            ),
          )}
        </ul>
      </section>
    </aside>
  )
}
