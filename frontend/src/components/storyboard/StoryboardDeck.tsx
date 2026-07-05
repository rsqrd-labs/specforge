import {
  type CSSProperties,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react"
import { AiDisclaimer } from "../shared/AiDisclaimer"
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

// Stepped autofit: the stage frame is a fixed 16:9 box, so a slide at the
// schema maxima can overflow it. After each slide renders we measure overflow
// and bump `data-fit-step` (0..MAX_SLIDE_FIT_STEP); CSS defines a reduced,
// deterministic type scale per step (via --sb-fit). Font-size steps only —
// never a continuous transform scale, which blurs text and breaks the glass
// styling. A slide that still overflows at the last step scrolls (the CSS
// overflow-y safety net) instead of being silently clipped.
export const MAX_SLIDE_FIT_STEP = 3

// The +1 fudge absorbs sub-pixel rounding so a slide that effectively fits is
// never stepped down. Takes the minimal element surface so tests can drive it
// with a plain object.
export function applySlideFitStep(article: {
  readonly scrollHeight: number
  readonly clientHeight: number
  setAttribute(name: string, value: string): void
}): number {
  let step = 0
  article.setAttribute("data-fit-step", "0")
  while (
    step < MAX_SLIDE_FIT_STEP &&
    article.scrollHeight > article.clientHeight + 1
  ) {
    step += 1
    article.setAttribute("data-fit-step", String(step))
  }
  return step
}

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

// Per-slide-type stage layout. A keynote does not use one split layout for every
// slide: the bookends (hero / thesis / closing) are centred, oversized title
// moments; a slide whose visual is a single metric becomes one giant figure; the
// architecture slide is full-bleed; everything else keeps the text + structured
// visual split. The return value is only ever used as a fixed class suffix, so
// no free text ever reaches CSS — it stays an allow-list.
type SlideLayout = "feature" | "metric" | "arch" | "split"

function slideLayout(
  slide: StoryboardSlide | null,
  isArchitecture: boolean,
): SlideLayout {
  if (isArchitecture) return "arch"
  const type = slide?.type
  if (type === "hero" || type === "thesis" || type === "closing") return "feature"
  if (visualMetric(slide?.visual)) return "metric"
  return "split"
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
// model supplied them, otherwise a theme motif band. It never renders
// source-artifact excerpts, source citations, or any generated media, so every
// slide reads as a designed keynote panel; evidence lives in the Sources layer.
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
  const slideRef = useRef<HTMLElement>(null)
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

  // Re-fit the active slide after every remount (the article is keyed on the
  // slide index) and whenever the stage resizes. Measuring is synchronous in a
  // layout effect so the audience never sees an oversized flash. ResizeObserver
  // is guarded for test environments (jsdom) that do not implement it.
  useLayoutEffect(() => {
    const article = slideRef.current
    if (!article) return
    applySlideFitStep(article)
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(() => {
      if (slideRef.current) applySlideFitStep(slideRef.current)
    })
    observer.observe(article)
    return () => observer.disconnect()
  }, [activeSlideIndex, payload, canShowDeck])

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
  // Per-slide-type layout (centred feature / giant metric / full-bleed arch /
  // split) plus the two framing moments: the very first slide of the deck is the
  // cover, and the first slide of any act gets the act-intro treatment.
  const layout = slideLayout(slide, isArchitectureSlide)
  const isActOpening = (activeSlide?.slideIndex ?? 0) === 0
  const isDeckCover = activeSlideIndex === 0
  const actNumber = activeSectionIndex + 1

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
          ref={slideRef}
          data-fit-step="0"
          className={`storyboard-slide storyboard-slide--${slide?.type ?? "thesis"} storyboard-slide--layout-${layout}${
            isArchitectureSlide ? " storyboard-slide--arch" : ""
          }${isActOpening ? " storyboard-slide--act-open" : ""}${
            isDeckCover ? " storyboard-slide--cover" : ""
          }`}
          aria-live="polite"
        >
          <div className="storyboard-slide-content">
            <div className="storyboard-slide-kicker">
              {isDeckCover && (
                <span className="storyboard-slide-cover-mark">
                  {payload?.title ?? title ?? "Storyboard"}
                </span>
              )}
              <span className="storyboard-slide-act">{section.title}</span>
              {isActOpening && (
                <span className="storyboard-slide-act-progress">
                  Act {actNumber} of {STORYBOARD_ACTS.length}
                </span>
              )}
            </div>
            <h2>{slide?.headline}</h2>
            <div className="storyboard-slide-text">
              <MarkdownRenderer content={slide?.visible_text ?? ""} />
            </div>
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
        <AiDisclaimer variant="inline" className="storyboard-deck__disclaimer" />
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
