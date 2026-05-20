import { useEffect, useState } from "react"
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

/**
 * Horizontal scrolling strip of starter templates (T-USE-12).
 *
 * - Hides itself entirely if the API returns zero templates ("no templates
 *   available" is worse than no strip per the design brief).
 * - Caches the API response at the module level (see api.ts) so re-renders
 *   don't re-fetch.
 * - Snap scrolling, no visible scrollbar — momentum on iOS via overflow.
 */
export function TemplatesStrip({ onPick, prominent }: TemplatesStripProps) {
  const [templates, setTemplates] = useState<Template[] | undefined>(undefined)

  useEffect(() => {
    let cancelled = false
    void getTemplates().then((list) => {
      if (!cancelled) setTemplates(list)
    })
    return () => {
      cancelled = true
    }
  }, [])

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
      <div className="templates-strip-rail" role="list">
        {templates.map((tpl) => (
          <div key={tpl.id} role="listitem" className="templates-strip-item">
            <TemplateCard template={tpl} onPick={onPick} />
          </div>
        ))}
      </div>
    </section>
  )
}
