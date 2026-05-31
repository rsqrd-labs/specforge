import type { CSSProperties } from "react"
import type {
  StoryboardDiagram,
  StoryboardDiagramLayer,
  StoryboardLayerKind,
} from "../../types/storyboard"

export const ARCHITECTURE_LAYER_SEQUENCE = [
  "client",
  "frontend",
  "api",
  "data",
  "llm",
  "integrations",
  "trust",
  "recovery",
] as const satisfies readonly StoryboardLayerKind[]

const LAYER_COPY: Record<(typeof ARCHITECTURE_LAYER_SEQUENCE)[number], string> = {
  client: "User and client entry points",
  frontend: "Frontend experience",
  api: "API and backend services",
  data: "Data stores and state",
  llm: "LLM and provider layer",
  integrations: "External integrations",
  trust: "Trust boundaries",
  recovery: "Failure and recovery paths",
}

interface ArchitectureRevealProps {
  diagram?: Pick<StoryboardDiagram, "layers"> | null
  layers?: StoryboardDiagramLayer[]
  currentStep?: number
  palette?: string[]
  title?: string
}

function safeHex(value: string | undefined, fallback: string): string {
  return value && /^#[0-9A-Fa-f]{6}$/.test(value) ? value : fallback
}

function layerForKind(
  layers: StoryboardDiagramLayer[],
  kind: (typeof ARCHITECTURE_LAYER_SEQUENCE)[number],
): StoryboardDiagramLayer {
  return (
    layers.find((layer) => layer.kind === kind) ?? {
      id: `missing-${kind}`,
      kind,
      label: LAYER_COPY[kind],
      summary: "This layer was not described in the generated diagram.",
      source_refs: [],
    }
  )
}

export function orderArchitectureLayers(
  layers: StoryboardDiagramLayer[],
): StoryboardDiagramLayer[] {
  return ARCHITECTURE_LAYER_SEQUENCE.map((kind) => layerForKind(layers, kind))
}

export function ArchitectureReveal({
  diagram,
  layers,
  currentStep = ARCHITECTURE_LAYER_SEQUENCE.length,
  palette = [],
  title = "Architecture reveal",
}: ArchitectureRevealProps) {
  const ordered = orderArchitectureLayers(layers ?? diagram?.layers ?? [])
  const visibleCount = Math.max(0, Math.min(currentStep, ordered.length))
  const primary = safeHex(palette[0], "#8f4e00")
  const secondary = safeHex(palette[1], "#a1385f")
  const accent = safeHex(palette[2], "#565e74")
  // Full guarded palette for per-layer accent rotation (falls back to the three
  // derived hues when the deck palette is short), so eight layers stay colourful.
  const cycle = palette.filter((colour) => /^#[0-9A-Fa-f]{6}$/.test(colour))
  const rotation = cycle.length >= 2 ? cycle : [primary, secondary, accent]

  return (
    <figure
      className="architecture-reveal"
      aria-label={title}
      style={
        {
          "--storyboard-arch-primary": primary,
          "--storyboard-arch-secondary": secondary,
          "--storyboard-arch-accent": accent,
        } as CSSProperties
      }
    >
      <ol className="architecture-reveal-stage" aria-label={`${title} ordered layers`}>
        {ordered.map((layer, index) => {
          const active = index < visibleCount
          const summary =
            layer.summary ||
            LAYER_COPY[layer.kind as keyof typeof LAYER_COPY] ||
            layer.kind
          const sourceId = layer.source_refs[0]?.source_id
          // Each layer takes the next palette colour (with the following one as a
          // gradient partner) so the eight planes read as a colourful, distinct
          // stack rather than a monochrome grid. The whole-deck guard already
          // validated these, and safeHex re-checks before they reach the DOM.
          const layerAccent = rotation[index % rotation.length]
          const layerAccent2 = rotation[(index + 1) % rotation.length]
          return (
            <li
              key={layer.id}
              className={`architecture-layer-card ${active ? "visible" : "pending"}`}
              data-layer-kind={layer.kind}
              style={
                {
                  "--layer-accent": layerAccent,
                  "--layer-accent-2": layerAccent2,
                  "--layer-index": index,
                } as CSSProperties
              }
            >
              <span className="architecture-layer-card__index">{index + 1}</span>
              <div className="architecture-layer-card__body">
                <span className="architecture-layer-card__kind">{layer.kind}</span>
                <strong>{layer.label}</strong>
                <p>{summary}</p>
                {sourceId && <small>{sourceId}</small>}
              </div>
            </li>
          )
        })}
      </ol>

      <ol
        className="architecture-reveal-fallback sr-only"
        aria-label="Architecture reveal ordered fallback summary"
      >
        {ordered.map((layer, index) => (
          <li key={layer.id} data-layer-kind={layer.kind}>
            <strong>
              {index + 1}. {layer.label}
            </strong>
            <span>
              {layer.summary ||
                LAYER_COPY[layer.kind as keyof typeof LAYER_COPY] ||
                layer.kind}
            </span>
          </li>
        ))}
      </ol>

      <figcaption className="architecture-reveal-caption">
        {ordered.slice(0, visibleCount).length} of {ordered.length} architecture
        layers revealed in deterministic order.
      </figcaption>
    </figure>
  )
}
