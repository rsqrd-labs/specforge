import type { Template } from "../../types/template"

interface TemplateCardProps {
  template: Template
  onPick: (template: Template) => void
}

/**
 * Single starter-template card. Cards are PICKABLE, not listable — hover
 * lifts the card and the cursor turns to pointer. Saffron is reserved for
 * the "Use this →" affordance, never for the card surface itself.
 */
export function TemplateCard({ template, onPick }: TemplateCardProps) {
  return (
    <button
      type="button"
      className="template-card"
      onClick={() => onPick(template)}
      aria-label={`Use the ${template.name} template`}
    >
      <span className="template-card-badge">{template.category}</span>
      <h3 className="template-card-name">{template.name}</h3>
      <p className="template-card-description">{template.description}</p>
      <span className="template-card-cta" aria-hidden="true">
        Use this →
      </span>
    </button>
  )
}
