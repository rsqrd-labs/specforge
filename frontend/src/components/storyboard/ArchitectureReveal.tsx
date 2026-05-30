import { useId, type CSSProperties } from "react"
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
  const gradientId = `storyboard-arch-line-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`

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
      <div className="architecture-reveal-stage" aria-hidden="true">
        <svg viewBox="0 0 960 420" aria-hidden="true" focusable="false">
          <defs>
            <linearGradient id={gradientId} x1="0" x2="1" y1="0" y2="1">
              <stop offset="0%" stopColor={primary} />
              <stop offset="100%" stopColor={secondary} />
            </linearGradient>
          </defs>
          {ordered.map((layer, index) => {
            const row = index % 2
            const column = Math.floor(index / 2)
            const x = 46 + column * 222
            const y = row === 0 ? 74 : 248
            const active = index < visibleCount
            return (
              <g
                key={layer.id}
                className={`architecture-node ${active ? "visible" : "pending"}`}
                data-layer-kind={layer.kind}
              >
                {index > 0 && (
                  <path
                    d={`M${x - 38} ${row === 0 ? 124 : 298} C${x - 74} ${row === 0 ? 188 : 212}, ${x - 108} ${row === 0 ? 212 : 188}, ${x - 138} ${index % 2 === 0 ? 124 : 298}`}
                    fill="none"
                    stroke={`url(#${gradientId})`}
                    strokeWidth="3"
                    strokeLinecap="round"
                    opacity={active ? 0.45 : 0.12}
                  />
                )}
                <rect
                  x={x}
                  y={y}
                  width="172"
                  height="82"
                  rx="18"
                  fill={active ? "rgba(255,255,255,0.92)" : "rgba(255,255,255,0.42)"}
                  stroke={active ? `url(#${gradientId})` : "rgba(85,67,54,0.22)"}
                  strokeWidth="2"
                />
                <circle
                  cx={x + 28}
                  cy={y + 28}
                  r="10"
                  fill={active ? secondary : accent}
                  opacity={active ? 0.92 : 0.32}
                />
                <text
                  x={x + 48}
                  y={y + 32}
                  className="architecture-node-kind"
                  fill={active ? primary : accent}
                >
                  {layer.kind}
                </text>
                <text
                  x={x + 22}
                  y={y + 62}
                  className="architecture-node-label"
                  fill="#1a1c1c"
                >
                  {layer.label.slice(0, 28)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>

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
