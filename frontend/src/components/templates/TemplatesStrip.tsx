import { useEffect, useRef, useState } from "react"
import { getTemplates } from "../../services/api"
import type { Template } from "../../types/template"
import { TemplateCard } from "./TemplateCard"

interface TemplatesStripProps {
  onPick: (template: Template) => void
  /**
   * When true, the strip is rendered as the dominant element of the page
   * with extra vertical breathing room and the section heading + sub-line.
   * Used on the dashboard cold-start. When false, the strip is compact —
   * still present, still scrollable, but understated.
   */
  prominent?: boolean
}

const SCROLL_STEP = 320
// The rail's own padding plus scroll-snap can rest a few px off the true
// edge on load (observed scrollLeft ~4px at rest, not 0) even when there's
// nothing to scroll to on that side. This absorbs that without flickering
// the chevron's visibility right before the rail actually stops.
const SCROLL_EDGE_EPSILON = 12

/**
 * Horizontal scrolling strip of starter templates (T-USE-12).
 *
 * - Hides itself entirely if the API returns zero templates ("no templates
 *   available" is worse than no strip per the design brief).
 * - Caches the API response at the module level (see api.ts) so re-renders
 *   don't re-fetch.
 * - Snap scrolling, no visible scrollbar — momentum on iOS via overflow.
 * - The rail is deliberately sized so the last visible card crops (a "peek"
 *   pattern signalling more content). A right-edge fade plus click-to-scroll
 *   chevrons make that discoverable for pointer input, which has no
 *   horizontal-scroll gesture of its own.
 */
export function TemplatesStrip({ onPick, prominent }: TemplatesStripProps) {
  const [templates, setTemplates] = useState<Template[] | undefined>(undefined)
  const railRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  useEffect(() => {
    let cancelled = false
    void getTemplates().then((list) => {
      if (!cancelled) setTemplates(list)
    })
    return () => {
      cancelled = true
    }
  }, [])

  const updateScrollState = () => {
    const rail = railRef.current
    if (!rail) return
    setCanScrollLeft(rail.scrollLeft > SCROLL_EDGE_EPSILON)
    setCanScrollRight(
      rail.scrollLeft + rail.clientWidth < rail.scrollWidth - SCROLL_EDGE_EPSILON,
    )
  }

  useEffect(() => {
    const rail = railRef.current
    if (!rail || !templates || templates.length === 0) return
    updateScrollState()
    const handleResize = () => updateScrollState()
    rail.addEventListener("scroll", updateScrollState, { passive: true })
    window.addEventListener("resize", handleResize)
    return () => {
      rail.removeEventListener("scroll", updateScrollState)
      window.removeEventListener("resize", handleResize)
    }
  }, [templates])

  function scrollByStep(direction: 1 | -1) {
    railRef.current?.scrollBy({ left: direction * SCROLL_STEP, behavior: "smooth" })
  }

  // Hide while loading and when the catalog is empty — the alternative
  // (a skeleton or empty-state copy) is louder than the value the strip
  // adds when it's not actually populated.
  if (!templates || templates.length === 0) return null

  return (
    <section
      className={`templates-strip ${prominent ? "prominent" : "compact"}`}
      aria-labelledby="templates-strip-heading"
    >
      {prominent && (
        <header className="templates-strip-header">
          <h2 id="templates-strip-heading">Start from a template</h2>
          <p>
            Hand-tuned starting points — pick one, then edit before generating.
          </p>
        </header>
      )}
      <div className="templates-strip-viewport">
        <div className={`templates-strip-rail${canScrollRight ? " has-more" : ""}`} role="list" ref={railRef}>
          {templates.map((tpl) => (
            <div key={tpl.id} role="listitem" className="templates-strip-item">
              <TemplateCard template={tpl} onPick={onPick} />
            </div>
          ))}
        </div>
        {canScrollLeft && (
          <button
            type="button"
            className="templates-strip-nav templates-strip-nav-prev"
            onClick={() => scrollByStep(-1)}
            aria-label="Scroll templates left"
          >
            ‹
          </button>
        )}
        {canScrollRight && (
          <button
            type="button"
            className="templates-strip-nav templates-strip-nav-next"
            onClick={() => scrollByStep(1)}
            aria-label="Scroll templates right"
          >
            ›
          </button>
        )}
      </div>
    </section>
  )
}
