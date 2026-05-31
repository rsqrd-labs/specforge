import { type MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useState } from "react"
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

function clampIndex(value: number, length: number): number {
  if (length <= 0) return 0
  return Math.max(0, Math.min(value, length - 1))
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
  // The panel browses notes on its own (the launch screen has no deck driving it),
  // but re-syncs whenever an external active slide changes (the in-deck usage).
  const [index, setIndex] = useState(() => clampIndex(activeSlideIndex, slides.length))
  useEffect(() => {
    setIndex(clampIndex(activeSlideIndex, slides.length))
  }, [activeSlideIndex, slides.length])

  const currentIndex = clampIndex(index, slides.length)
  const current = slides[currentIndex]
  const next = slides[currentIndex + 1] ?? null
  const canViewNotes = isOwner || permissions?.allow_notes_download === true
  const note = canViewNotes ? noteForSlide(payload, current?.slide) : null
  const walkthroughCue = sourceBackedWalkthroughCue(note)

  // One continuous session timer for the whole talk — it does not reset as the
  // presenter pages through slides.
  useEffect(() => {
    const timer = window.setInterval(() => {
      setElapsedSeconds((value) => value + 1)
    }, 1000)
    return () => window.clearInterval(timer)
  }, [])

  const goPrev = useCallback(() => {
    setIndex((value) => clampIndex(value - 1, slides.length))
  }, [slides.length])
  const goNext = useCallback(() => {
    setIndex((value) => clampIndex(value + 1, slides.length))
  }, [slides.length])

  const overlayProps = {
    className: "pnotes-overlay",
    role: "dialog" as const,
    "aria-modal": true,
    "aria-label": "Presenter mode",
    "data-view": publicView ? "public" : "owner",
    onClick: (event: ReactMouseEvent) => {
      if (event.target === event.currentTarget) onClose?.()
    },
  }

  if (!canViewNotes) {
    return (
      <div {...overlayProps}>
        <div className="pnotes pnotes--locked">
          <header className="pnotes__bar">
            <span className="pnotes__eyebrow">Speaker notes</span>
            {onClose && (
              <button
                type="button"
                className="pnotes__close"
                onClick={onClose}
                aria-label="Close speaker notes"
              >
                ✕
              </button>
            )}
          </header>
          <p className="pnotes__locked-copy">
            Speaker notes are private unless public notes permission is enabled.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div {...overlayProps}>
      <div className="pnotes">
        <header className="pnotes__bar">
          <div className="pnotes__bar-left">
            <span className="pnotes__eyebrow">Speaker notes</span>
            <strong className="pnotes__pos">
              Slide {currentIndex + 1}
              <span> / {slides.length}</span>
            </strong>
          </div>
          <div className="pnotes__bar-right">
            <span className="pnotes__timer" aria-label="Session timer">
              <span className="pnotes__timer-dot" aria-hidden="true" />
              {formatTimer(elapsedSeconds)}
            </span>
            {onClose && (
              <button
                type="button"
                className="pnotes__close"
                onClick={onClose}
                aria-label="Close speaker notes"
              >
                ✕
              </button>
            )}
          </div>
        </header>

        <div className="pnotes__body">
          <section className="pnotes__current" aria-label="Current slide">
            <span className="pnotes__act">{current?.sectionTitle ?? "—"}</span>
            <h2>{current?.slide.headline ?? "No current slide"}</h2>
          </section>

          <section className="pnotes__track" aria-label="Speaker notes">
            <p>{note?.talk_track ?? "No speaker notes are available for this slide."}</p>
          </section>

          <dl className="pnotes__cues">
            <div className="pnotes__cue">
              <dt>Transition</dt>
              <dd>{note?.transition ?? "Advance when the current point lands."}</dd>
            </div>
            <div className="pnotes__cue">
              <dt>Pause</dt>
              <dd>{note?.pause_cue ?? "Pause briefly before the next slide."}</dd>
            </div>
            {walkthroughCue && (
              <div className="pnotes__cue pnotes__cue--wide">
                <dt>Walkthrough</dt>
                <dd>{walkthroughCue}</dd>
              </div>
            )}
          </dl>

          <section className="pnotes__backup" aria-label="Backup points">
            <span className="pnotes__label">Backup points</span>
            <ul>
              {(note?.backup_points.length
                ? note.backup_points
                : ["Use the appendix for deeper technical detail."]
              ).map((point) => (
                <li key={point}>{point}</li>
              ))}
            </ul>
          </section>
        </div>

        <footer className="pnotes__foot">
          <button
            type="button"
            className="pnotes__nav"
            onClick={goPrev}
            disabled={currentIndex === 0}
          >
            ‹ Previous
          </button>
          <div className="pnotes__next" aria-label="Next slide">
            <span>Up next</span>
            <strong>{next?.slide.headline ?? "End of deck"}</strong>
          </div>
          <button
            type="button"
            className="pnotes__nav pnotes__nav--primary"
            onClick={goNext}
            disabled={currentIndex >= slides.length - 1}
          >
            Next ›
          </button>
        </footer>
      </div>
    </div>
  )
}
