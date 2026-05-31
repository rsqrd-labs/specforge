import {
  type CSSProperties,
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
  StoryboardVisual,
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

// Human label per inert visual.kind. The renderer draws a deterministic, themed
// visual from this — it never honours a media promise (e.g. "video-demo") and
// never paints raw source-artifact text onto the slide; source evidence lives in
// the toggleable Sources layer, not the hero visual.
const VISUAL_KIND_LABEL: Record<string, string> = {
  hero: "Vision",
  thesis: "Thesis",
  product: "Product",
  walkthrough: "Walkthrough",
  architecture: "Architecture",
  trust: "Trust & reliability",
  closing: "Close",
  appendix_pointer: "Appendix",
  diagram_ref: "Diagram",
  bullets: "Highlights",
  metric: "Key metric",
}

const VISUAL_POINTS_MAX = 5

// Every palette colour the LLM emits is validated as #RRGGBB at generation time;
// we guard again here before injecting into a style object so a malformed value
// can never reach the DOM. React style objects are not a JS-injection vector, but
// validating is cheap defence-in-depth and guarantees the deck stays legible.
const HEX_RE = /^#[0-9a-fA-F]{6}$/

// A vivid, accessible fallback so an empty/invalid palette still renders a
// distinctive deck rather than collapsing to a single flat colour.
const FALLBACK_PALETTE = [
  "#6d28d9",
  "#0ea5e9",
  "#f59e0b",
  "#10b981",
  "#ec4899",
  "#3b82f6",
]

function safeHex(value: unknown, fallback: string): string {
  return typeof value === "string" && HEX_RE.test(value) ? value : fallback
}

// Keep only valid hex colours; fall back to the brand palette when the model
// supplied fewer than two usable colours so per-act rotation always has range.
function safePalette(palette: string[] | undefined): string[] {
  const cleaned = (palette ?? []).filter(
    (colour): colour is string => typeof colour === "string" && HEX_RE.test(colour),
  )
  return cleaned.length >= 2 ? cleaned : FALLBACK_PALETTE
}

// The accent for a given act — cycles the palette so moving across the six acts
// visibly shifts the deck's colour, the core fix for "it always looks the same".
function actAccent(palette: string[], index: number): string {
  return palette[index % palette.length]
}

// Map the free-text transition_style mood onto one of three vetted CSS animation
// classes. The string never reaches CSS; we only ever emit a fixed class name,
// so this stays an allow-list (no free-text → CSS injection surface).
function transitionClass(style: string | undefined): "fade" | "glide" | "rise" {
  const mood = (style ?? "").toLowerCase()
  if (/(slide|glide|push|pan|sweep)/.test(mood)) return "glide"
  if (/(fade|dissolve|cinematic|cross)/.test(mood)) return "fade"
  return "rise"
}

// Descriptor keys are pure data: read them defensively (any may be absent) and
// render only strings. React escapes every value, so nothing is ever executed.
function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter(
    (item): item is string => typeof item === "string" && item.trim().length > 0,
  )
}

function visualPoints(visual: StoryboardVisual | undefined): string[] {
  if (!visual) return []
  for (const key of ["points", "items", "bullets", "highlights"]) {
    const list = asStringList((visual as Record<string, unknown>)[key])
    if (list.length > 0) return list.slice(0, VISUAL_POINTS_MAX)
  }
  return []
}

interface VisualMetric {
  value: string
  label: string
}

function visualMetric(visual: StoryboardVisual | undefined): VisualMetric | null {
  if (!visual) return null
  const data = visual as Record<string, unknown>
  const rawValue = data.value ?? data.metric ?? data.stat
  if (typeof rawValue !== "string" && typeof rawValue !== "number") return null
  const rawLabel = data.label ?? data.caption ?? data.unit
  return {
    value: String(rawValue),
    label: typeof rawLabel === "string" ? rawLabel : "",
  }
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

// Deterministic, theme-driven slide visual. It renders from the slide's own
// structured data keyed by visual.kind — descriptor bullets/metric when the
// model supplied them, otherwise the headline as a clean caption — plus the
// grounding source badges. It never renders source-artifact excerpts or any
// generated media, so every slide reads as a designed keynote panel.
function SlideVisual({
  slide,
  palette,
}: {
  slide: StoryboardSlide | null
  palette: string[] | undefined
}) {
  const safe = safePalette(palette)
  const swatches = safe.slice(0, 4)
  const kind = slide?.visual?.kind ?? "hero"
  const label = VISUAL_KIND_LABEL[kind] ?? "Highlight"
  const metric = visualMetric(slide?.visual)
  const points = visualPoints(slide?.visual)
  return (
    <div className="storyboard-visual-card">
      {/* The kind label colour is themed but darkened (in CSS, mixed toward a dark
          ink) so it stays legible even when the act accent is a pale hue. */}
      <span className="storyboard-visual-kind">{label}</span>
      {metric ? (
        <div className="storyboard-visual-metric">
          <strong>{metric.value}</strong>
          {metric.label && <p>{metric.label}</p>}
        </div>
      ) : points.length > 0 ? (
        <ul className="storyboard-visual-points">
          {points.map((point, index) => (
            <li key={index}>{point}</li>
          ))}
        </ul>
      ) : (
        // No descriptor data: render a deterministic, theme-driven motif rather
        // than duplicating the headline or dumping source text onto the visual.
        <div className="storyboard-visual-motif" aria-hidden="true">
          {swatches.map((colour, index) => (
            <span key={index} style={{ background: colour }} />
          ))}
        </div>
      )}
    </div>
  )
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
  const palette = useMemo(() => safePalette(payload?.theme.palette), [payload])
  const transition = useMemo(
    () => transitionClass(payload?.theme.transition_style),
    [payload],
  )
  // Themed CSS custom properties scoped to the deck subtree. The base ink/surface
  // stays neutral and readable; the palette drives only the accent, the per-act
  // accent (which rotates as you move through the six acts), and the cover/stage
  // gradients — so each deck looks distinct without ever risking body contrast.
  const deckStyle = useMemo<CSSProperties>(() => {
    const accent = safeHex(palette[0], "#6d28d9")
    const accent2 = safeHex(palette[1] ?? palette[0], "#0ea5e9")
    const act = safeHex(actAccent(palette, activeSectionIndex), accent)
    const actNext = safeHex(actAccent(palette, activeSectionIndex + 1), accent2)
    return {
      "--sb-accent": accent,
      "--sb-accent-2": accent2,
      "--sb-act-accent": act,
      "--sb-act-accent-2": actNext,
    } as CSSProperties
  }, [palette, activeSectionIndex])
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

  return (
    <section
      ref={shellRef}
      className={`storyboard-deck-shell storyboard-theme-${transition} ${isPresentationMode ? "fullscreen" : ""}`}
      style={deckStyle}
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
        {/* Ambient, palette-driven motion behind the slide. It lives outside the
            keyed <article> so it drifts continuously rather than restarting on
            every slide change, and recolours as the active act's accent shifts. */}
        <div className="storyboard-stage-decor" aria-hidden="true">
          <span className="storyboard-decor-orb storyboard-decor-orb--1" />
          <span className="storyboard-decor-orb storyboard-decor-orb--2" />
          <span className="storyboard-decor-grid" />
        </div>
        <article
          key={activeSlideIndex}
          className={`storyboard-slide storyboard-slide--${slide?.type ?? "thesis"}${
            isArchitectureSlide ? " storyboard-slide--arch" : ""
          }`}
          aria-live="polite"
        >
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

          <div className="storyboard-slide-visual">
            {isArchitectureSlide && architectureDiagram ? (
              <ArchitectureReveal
                diagram={architectureDiagram}
                currentStep={architectureStep}
                palette={payload?.theme.palette}
                title="Technical Architecture"
              />
            ) : (
              <SlideVisual slide={slide} palette={payload?.theme.palette} />
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
