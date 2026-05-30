import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { MarkdownRenderer } from "../workspace/MarkdownRenderer"
import {
  ARCHITECTURE_LAYER_SEQUENCE,
  ArchitectureReveal,
} from "./ArchitectureReveal"
import { PresenterMode } from "./PresenterMode"
import { SourceLayer } from "./SourceLayer"
import type {
  StoryboardDiagram,
  StoryboardPayload,
  StoryboardSection,
  StoryboardSectionTitle,
  StoryboardSharePermissions,
  StoryboardSlide,
  StoryboardStatus,
} from "../../types/storyboard"

export const STORYBOARD_ACTS: StoryboardSectionTitle[] = [
  "Opening Thesis",
  "Product Vision",
  "Product Walkthrough",
  "Technical Architecture",
  "Trust, Security, Reliability",
  "Launch Close",
]

type DeckDisplayState =
  | "loading"
  | "error"
  | "not-found"
  | "empty"
  | "failed"
  | "generating"
  | "ready"
  | "stale"

interface StoryboardDeckProps {
  payload?: StoryboardPayload | null
  status?: StoryboardStatus
  title?: string
  errorMessage?: string | null
  isLoading?: boolean
  isNotFound?: boolean
  isOwner?: boolean
  allowPresenterMode?: boolean
  allowSourceLayer?: boolean
  sharePermissions?: Partial<StoryboardSharePermissions>
  publicView?: boolean
  onExit?: () => void
}

interface DeckSlide {
  section: StoryboardSection
  sectionIndex: number
  slide: StoryboardSlide
  slideIndex: number
}

interface VisualFrame {
  eyebrow: string
  title: string
  detail: string
}

const VISUAL_FRAMES: Record<StoryboardSectionTitle, VisualFrame> = {
  "Opening Thesis": {
    eyebrow: "Thesis",
    title: "Problem to product",
    detail: "The opening frame stays tied to the finalised SPEC and PLAN.",
  },
  "Product Vision": {
    eyebrow: "Vision",
    title: "Product signal",
    detail: "The deck highlights only capabilities grounded in the workspace.",
  },
  "Product Walkthrough": {
    eyebrow: "Flow",
    title: "Live workflow path",
    detail: "Presenter cues focus on browser actions, not generated media.",
  },
  "Technical Architecture": {
    eyebrow: "Architecture",
    title: "System layers",
    detail: "The reveal is rendered from structured diagram layers.",
  },
  "Trust, Security, Reliability": {
    eyebrow: "Trust",
    title: "Controls and recovery",
    detail: "Security, reliability, and testing claims stay source-backed.",
  },
  "Launch Close": {
    eyebrow: "Close",
    title: "Readiness narrative",
    detail: "The final act connects scope, confidence, and next action.",
  },
}

function sectionForAct(
  payload: StoryboardPayload | null | undefined,
  title: StoryboardSectionTitle,
): StoryboardSection {
  return (
    payload?.sections.find((section) => section.title === title) ?? {
      id: title.toLowerCase().replace(/[^a-z0-9]+/g, "-"),
      title,
      slides: [],
    }
  )
}

function sixActSections(
  payload: StoryboardPayload | null | undefined,
): StoryboardSection[] {
  return STORYBOARD_ACTS.map((title) => sectionForAct(payload, title))
}

function flattenSlides(sections: StoryboardSection[]): DeckSlide[] {
  return sections.flatMap((section, sectionIndex) =>
    section.slides.map((slide, slideIndex) => ({
      section,
      sectionIndex,
      slide,
      slideIndex,
    })),
  )
}

function findArchitectureDiagram(
  payload: StoryboardPayload | null | undefined,
): StoryboardDiagram | null {
  return payload?.diagrams.find((diagram) => diagram.type === "architecture_reveal") ?? null
}

function visualFrameFor(
  section: StoryboardSection,
  slide: StoryboardSlide | null,
): VisualFrame {
  const base = VISUAL_FRAMES[section.title]
  if (!slide) return base
  if (slide.type === "trust") return VISUAL_FRAMES["Trust, Security, Reliability"]
  if (slide.type === "walkthrough") return VISUAL_FRAMES["Product Walkthrough"]
  if (slide.type === "product") return VISUAL_FRAMES["Product Vision"]
  if (slide.type === "closing") return VISUAL_FRAMES["Launch Close"]
  if (slide.type === "architecture") return VISUAL_FRAMES["Technical Architecture"]
  return base
}

function deckState({
  payload,
  status,
  errorMessage,
  isLoading,
  isNotFound,
}: Pick<
  StoryboardDeckProps,
  "payload" | "status" | "errorMessage" | "isLoading" | "isNotFound"
>): DeckDisplayState {
  if (isLoading) return "loading"
  if (isNotFound) return "not-found"
  if (errorMessage) return "error"
  if (status === "failed") return "failed"
  if (status === "generating") return "generating"
  if (!payload) return "empty"
  if (flattenSlides(sixActSections(payload)).length === 0) return "empty"
  if (status === "stale") return "stale"
  return "ready"
}

function StatePanel({
  state,
  title,
  message,
}: {
  state: DeckDisplayState
  title?: string
  message?: string | null
}) {
  const copy: Record<DeckDisplayState, { heading: string; body: string }> = {
    loading: {
      heading: "Loading Storyboard",
      body: "Preparing the browser-native keynote.",
    },
    error: {
      heading: "Could not load Storyboard",
      body: message ?? "The Storyboard could not be loaded. Try again from the workspace.",
    },
    "not-found": {
      heading: "Storyboard not found",
      body: "This Storyboard does not exist or is not available on your account.",
    },
    empty: {
      heading: "Storyboard is empty",
      body: "The generated payload does not contain presentable slides.",
    },
    failed: {
      heading: "Storyboard generation failed",
      body: "Credits were refunded when generation failed before a usable Storyboard was persisted.",
    },
    generating: {
      heading: "Storyboard is generating",
      body: "The deck will be ready after the generation job finishes.",
    },
    ready: {
      heading: title ?? "Storyboard",
      body: "Ready to present.",
    },
    stale: {
      heading: "Storyboard is stale",
      body: "This deck is still presentable, but source stages changed after it was generated.",
    },
  }
  const selected = copy[state]

  return (
    <div className={`storyboard-state storyboard-state-${state}`} role="status">
      <h1>{selected.heading}</h1>
      <p>{selected.body}</p>
    </div>
  )
}

export function StoryboardDeck({
  payload,
  status = "ready",
  title,
  errorMessage = null,
  isLoading = false,
  isNotFound = false,
  isOwner = false,
  allowPresenterMode = false,
  allowSourceLayer = false,
  sharePermissions,
  publicView = false,
  onExit,
}: StoryboardDeckProps) {
  const shellRef = useRef<HTMLDivElement>(null)
  const sections = useMemo(() => sixActSections(payload), [payload])
  const slides = useMemo(() => flattenSlides(sections), [sections])
  const architectureDiagram = useMemo(() => findArchitectureDiagram(payload), [payload])
  const [activeSlideIndex, setActiveSlideIndex] = useState(0)
  const [isPresenterVisible, setIsPresenterVisible] = useState(false)
  const [isSourceVisible, setIsSourceVisible] = useState(false)
  const [isPresentationMode, setIsPresentationMode] = useState(false)
  const state = deckState({ payload, status, errorMessage, isLoading, isNotFound })
  const canShowDeck = state === "ready" || state === "stale"
  const activeSlide = canShowDeck ? slides[activeSlideIndex] ?? null : null
  const activeSectionIndex = activeSlide?.sectionIndex ?? 0
  const presenterAllowed =
    isOwner || allowPresenterMode || sharePermissions?.allow_notes_download === true
  const sourceAllowed =
    isOwner || allowSourceLayer || sharePermissions?.allow_source_layer === true

  useEffect(() => {
    setActiveSlideIndex((current) =>
      slides.length === 0 ? 0 : Math.min(current, slides.length - 1),
    )
  }, [slides.length])

  const goNext = useCallback(() => {
    setActiveSlideIndex((current) =>
      slides.length === 0 ? 0 : Math.min(current + 1, slides.length - 1),
    )
  }, [slides.length])

  const goPrevious = useCallback(() => {
    setActiveSlideIndex((current) => Math.max(current - 1, 0))
  }, [])

  const goToAct = useCallback(
    (sectionIndex: number) => {
      const targetIndex = slides.findIndex((item) => item.sectionIndex === sectionIndex)
      setActiveSlideIndex(targetIndex >= 0 ? targetIndex : 0)
    },
    [slides],
  )

  const toggleFullscreen = useCallback(async () => {
    const target = shellRef.current
    if (!target) return
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen?.()
        setIsPresentationMode(false)
      } else {
        await target.requestFullscreen?.()
        setIsPresentationMode(true)
      }
    } catch {
      setIsPresentationMode((value) => !value)
    }
  }, [])

  const closePresentation = useCallback(async () => {
    if (document.fullscreenElement) {
      try {
        await document.exitFullscreen?.()
      } catch {
        // If the browser denies the request, still restore the in-page chrome.
      }
    }
    setIsPresentationMode(false)
    onExit?.()
  }, [onExit])

  const handleShortcut = useCallback(
    (event: globalThis.KeyboardEvent) => {
      if (!canShowDeck) return
      const target = event.target as HTMLElement | null
      if (target?.tagName === "INPUT" || target?.tagName === "TEXTAREA") return

      if (event.key === "ArrowRight" || event.code === "Space") {
        event.preventDefault()
        goNext()
        return
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault()
        goPrevious()
        return
      }
      if (event.key === "Escape") {
        event.preventDefault()
        void closePresentation()
        return
      }

      const key = event.key.toLowerCase()
      if (key === "f") {
        event.preventDefault()
        void toggleFullscreen()
      } else if (key === "p" && presenterAllowed) {
        event.preventDefault()
        setIsPresenterVisible((value) => !value)
      } else if (key === "s" && sourceAllowed) {
        event.preventDefault()
        setIsSourceVisible((value) => !value)
      }
    },
    [
      canShowDeck,
      closePresentation,
      goNext,
      goPrevious,
      presenterAllowed,
      sourceAllowed,
      toggleFullscreen,
    ],
  )

  useEffect(() => {
    window.addEventListener("keydown", handleShortcut)
    return () => window.removeEventListener("keydown", handleShortcut)
  }, [handleShortcut])

  if (!canShowDeck || !payload) {
    return (
      <section className="storyboard-deck-shell storyboard-deck-shell-empty">
        <StatePanel state={state} title={title ?? payload?.title} message={errorMessage} />
      </section>
    )
  }

  const slide = activeSlide?.slide ?? null
  const section = activeSlide?.section ?? sections[0]
  const isArchitectureSlide =
    slide?.type === "architecture" || section.title === "Technical Architecture"
  const architectureStep = ARCHITECTURE_LAYER_SEQUENCE.length
  const visualFrame = visualFrameFor(section, slide)

  return (
    <section
      ref={shellRef}
      className={`storyboard-deck-shell ${isPresentationMode ? "fullscreen" : ""}`}
      aria-label="StoryboardDeck"
      tabIndex={-1}
    >
      {state === "stale" && (
        <div className="storyboard-stale-banner" role="status">
          Stale Storyboard: source stages changed after this deck was generated.
        </div>
      )}

      <header className="storyboard-deck-header">
        <div>
          <span>{payload?.theme.motif || "Storyboard"}</span>
          <h1>{title ?? payload?.title}</h1>
        </div>
        <div className="storyboard-deck-controls">
          <button type="button" onClick={goPrevious} disabled={activeSlideIndex === 0}>
            Previous
          </button>
          <button
            type="button"
            onClick={goNext}
            disabled={activeSlideIndex >= slides.length - 1}
          >
            Next
          </button>
          <button type="button" onClick={() => void toggleFullscreen()}>
            Fullscreen
          </button>
          <button
            type="button"
            onClick={() => setIsPresenterVisible((value) => !value)}
            disabled={!presenterAllowed}
          >
            Presenter
          </button>
          <button
            type="button"
            onClick={() => setIsSourceVisible((value) => !value)}
            disabled={!sourceAllowed}
          >
            Sources
          </button>
        </div>
      </header>

      <nav className="storyboard-act-tabs" role="tablist" aria-label="Six Storyboard acts">
        {sections.map((item, index) => (
          <button
            key={item.title}
            type="button"
            role="tab"
            aria-selected={activeSectionIndex === index}
            onClick={() => goToAct(index)}
          >
            <span>{index + 1}</span>
            {item.title}
          </button>
        ))}
      </nav>

      <div className="storyboard-stage-frame">
        <article className="storyboard-slide" aria-live="polite">
          <div className="storyboard-slide-content">
            <span className="storyboard-slide-act">{section.title}</span>
            <h2>{slide?.headline}</h2>
            <div className="storyboard-slide-text">
              <MarkdownRenderer content={slide?.visible_text ?? ""} />
            </div>
            {slide?.sources && slide.sources.length > 0 && (
              <div className="storyboard-slide-source-badges" aria-label="Slide source badges">
                {slide.sources.map((source) => (
                  <span key={`${slide.id}-${source}`}>{source}</span>
                ))}
              </div>
            )}
          </div>

          <div className="storyboard-slide-visual" aria-hidden={!isArchitectureSlide}>
            {isArchitectureSlide && architectureDiagram ? (
              <ArchitectureReveal
                diagram={architectureDiagram}
                currentStep={architectureStep}
                palette={payload?.theme.palette}
                title="Technical Architecture"
              />
            ) : (
              <div className="storyboard-visual-card">
                <span>{visualFrame.eyebrow}</span>
                <strong>{visualFrame.title}</strong>
                <p>{visualFrame.detail}</p>
              </div>
            )}
          </div>
        </article>
      </div>

      <footer className="storyboard-deck-footer">
        <span>
          Slide {activeSlideIndex + 1} of {slides.length}
        </span>
        <progress value={activeSlideIndex + 1} max={slides.length} />
        <span>ArrowRight / Space next, ArrowLeft previous, F fullscreen</span>
      </footer>

      {isPresenterVisible && presenterAllowed && (
        <PresenterMode
          payload={payload}
          activeSlideIndex={activeSlideIndex}
          isOwner={isOwner}
          permissions={sharePermissions}
          publicView={publicView}
          onClose={() => setIsPresenterVisible(false)}
        />
      )}

      {isSourceVisible && sourceAllowed && (
        <SourceLayer
          payload={payload}
          currentSlideId={slide?.id ?? null}
          isOwner={isOwner}
          permissions={sharePermissions}
          publicView={publicView}
          onClose={() => setIsSourceVisible(false)}
        />
      )}
    </section>
  )
}
