import type { CSSProperties } from "react"
import type {
  StoryboardDiagram,
  StoryboardDiagramLayer,
  StoryboardLayerKind,
} from "../../types/storyboard"

// The eight fixed architecture planes, in canonical reveal order. This is a
// closed enum owned by trusted code; the LLM only ever fills a layer's
// label/summary/source_refs, never the topology.
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

type ArchitectureKind = (typeof ARCHITECTURE_LAYER_SEQUENCE)[number]

const LAYER_COPY: Record<ArchitectureKind, string> = {
  client: "User and client entry points",
  frontend: "Frontend experience",
  api: "API and backend services",
  data: "Data stores and state",
  llm: "LLM and provider layer",
  integrations: "External integrations",
  trust: "Trust boundaries",
  recovery: "Failure and recovery paths",
}

// ---------------------------------------------------------------------------
// Topology constant (trusted code only — no LLM input reaches geometry).
//
//   client ─▶ frontend ─▶ api ─┬─▶ data
//                              ├─▶ llm
//                              └─▶ integrations
//   trust:    boundary overlay spanning frontend·api·data·llm
//   recovery: backplane under api·data·llm·integrations
//
// Positions/edges/regions are computed deterministically below; the Python
// offline renderer (services/pipeline/storyboard_renderer.py) mirrors these
// numbers so the downloaded deck draws the same static topology.
// ---------------------------------------------------------------------------

const VIEW_W = 960
const VIEW_H = 600
const NODE_W = 168
const NODE_H = 88

// The six connectable box nodes (center coordinates). `trust` and `recovery`
// are regions, not boxes, and are derived from these.
const BOX_KINDS = [
  "client",
  "frontend",
  "api",
  "data",
  "llm",
  "integrations",
] as const satisfies readonly ArchitectureKind[]

type BoxKind = (typeof BOX_KINDS)[number]

const NODE_CENTERS: Record<BoxKind, { x: number; y: number }> = {
  client: { x: 104, y: 300 },
  frontend: { x: 330, y: 300 },
  api: { x: 556, y: 300 },
  data: { x: 834, y: 118 },
  llm: { x: 834, y: 300 },
  integrations: { x: 834, y: 482 },
}

const EDGES: readonly (readonly [BoxKind, BoxKind])[] = [
  ["client", "frontend"],
  ["frontend", "api"],
  ["api", "data"],
  ["api", "llm"],
  ["api", "integrations"],
]

const TRUST_MEMBERS: readonly BoxKind[] = ["frontend", "api", "data", "llm"]
const RECOVERY_MEMBERS: readonly BoxKind[] = ["api", "data", "llm", "integrations"]

interface Box {
  x: number
  y: number
  w: number
  h: number
  cx: number
  cy: number
}

function nodeBox(kind: BoxKind): Box {
  const c = NODE_CENTERS[kind]
  return { x: c.x - NODE_W / 2, y: c.y - NODE_H / 2, w: NODE_W, h: NODE_H, cx: c.x, cy: c.y }
}

// Smooth left-to-right connector from one node's right edge to the next node's
// left edge. The control points are pulled horizontally so vertical fan-outs
// (api → data/integrations) curve gracefully instead of kinking.
function edgePath(from: BoxKind, to: BoxKind): string {
  const a = NODE_CENTERS[from]
  const b = NODE_CENTERS[to]
  const sx = a.x + NODE_W / 2
  const sy = a.y
  const ex = b.x - NODE_W / 2
  const ey = b.y
  const dx = Math.max((ex - sx) * 0.5, 36)
  return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`
}

interface Region {
  x: number
  y: number
  w: number
  h: number
}

function boundingRegion(members: readonly BoxKind[], pad: number): Region {
  const boxes = members.map(nodeBox)
  const minX = Math.min(...boxes.map((b) => b.x)) - pad
  const minY = Math.min(...boxes.map((b) => b.y)) - pad
  const maxX = Math.max(...boxes.map((b) => b.x + b.w)) + pad
  const maxY = Math.max(...boxes.map((b) => b.y + b.h)) + pad
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

const TRUST_REGION = boundingRegion(TRUST_MEMBERS, 24)
const RECOVERY_REGION = boundingRegion(RECOVERY_MEMBERS, 38)

function seqIndex(kind: string): number {
  return ARCHITECTURE_LAYER_SEQUENCE.indexOf(kind as ArchitectureKind)
}

// ---------------------------------------------------------------------------
// Props + helpers
// ---------------------------------------------------------------------------

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
  kind: ArchitectureKind,
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

function layerSummary(layer: StoryboardDiagramLayer): string {
  return (
    layer.summary || LAYER_COPY[layer.kind as keyof typeof LAYER_COPY] || layer.kind
  )
}

export function ArchitectureReveal({
  diagram,
  layers,
  currentStep = ARCHITECTURE_LAYER_SEQUENCE.length,
  palette = [],
  title = "Architecture reveal",
}: ArchitectureRevealProps) {
  const all = layers ?? diagram?.layers ?? []
  const ordered = orderArchitectureLayers(all)
  const byKind = new Map(ordered.map((layer) => [layer.kind, layer]))
  const visibleCount = Math.max(0, Math.min(currentStep, ordered.length))

  // Layers whose kind is outside the closed enum (e.g. an optional `group`
  // annotation) are tolerated: rendered as unconnected annotation nodes, never
  // crashing the topology.
  const knownKinds = new Set<string>(ARCHITECTURE_LAYER_SEQUENCE)
  const extras = all.filter((layer) => !knownKinds.has(layer.kind))

  const primary = safeHex(palette[0], "#8f4e00")
  const secondary = safeHex(palette[1], "#a1385f")
  const accent = safeHex(palette[2], "#565e74")
  const cycle = palette.filter((colour) => /^#[0-9A-Fa-f]{6}$/.test(colour))
  const rotation = cycle.length >= 2 ? cycle : [primary, secondary, accent]
  const accentFor = (index: number) => rotation[index % rotation.length]

  const isActiveKind = (kind: string) => seqIndex(kind) < visibleCount

  const trustLayer = byKind.get("trust")
  const recoveryLayer = byKind.get("recovery")

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
      <svg
        className="architecture-topology"
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="xMidYMid meet"
        role="presentation"
        aria-hidden="true"
      >
        <defs>
          <marker
            id="arch-flow-arrow"
            viewBox="0 0 10 10"
            refX="8.5"
            refY="5"
            markerWidth="7"
            markerHeight="7"
            orient="auto-start-reverse"
          >
            <path className="arch-arrow-head" d="M0 0 L10 5 L0 10 z" />
          </marker>
        </defs>

        {/* Recovery backplane (lowest layer). */}
        <g
          className={`arch-region arch-region--recovery${
            isActiveKind("recovery") ? "" : " pending"
          }`}
          style={{ "--reveal-index": seqIndex("recovery") } as CSSProperties}
        >
          <rect
            className="arch-region__rect arch-region__rect--recovery"
            x={RECOVERY_REGION.x}
            y={RECOVERY_REGION.y}
            width={RECOVERY_REGION.w}
            height={RECOVERY_REGION.h}
            rx={22}
          />
          <text
            className="arch-region__label arch-region__label--recovery"
            x={RECOVERY_REGION.x + 16}
            y={RECOVERY_REGION.y + RECOVERY_REGION.h - 14}
          >
            {recoveryLayer?.label || LAYER_COPY.recovery}
          </text>
        </g>

        {/* Trust boundary (dashed outline). */}
        <g
          className={`arch-region arch-region--trust${
            isActiveKind("trust") ? "" : " pending"
          }`}
          style={{ "--reveal-index": seqIndex("trust") } as CSSProperties}
        >
          <rect
            className="arch-region__rect arch-region__rect--trust"
            x={TRUST_REGION.x}
            y={TRUST_REGION.y}
            width={TRUST_REGION.w}
            height={TRUST_REGION.h}
            rx={20}
          />
          <text
            className="arch-region__label arch-region__label--trust"
            x={TRUST_REGION.x + 16}
            y={TRUST_REGION.y + 22}
          >
            {trustLayer?.label || LAYER_COPY.trust}
          </text>
        </g>

        {/* Edges: a solid connector (the static base) plus a flowing dash on top
            (the animated data flow, disabled under reduced motion). */}
        {EDGES.map(([from, to]) => {
          const d = edgePath(from, to)
          const active = isActiveKind(from) && isActiveKind(to)
          const revealIndex = Math.max(seqIndex(from), seqIndex(to))
          return (
            <g
              key={`${from}-${to}`}
              className={`arch-edge-group${active ? "" : " pending"}`}
              style={
                {
                  "--reveal-index": revealIndex,
                  "--edge-accent": accentFor(seqIndex(to)),
                } as CSSProperties
              }
            >
              <path
                className="arch-edge"
                d={d}
                data-arch-edge={`${from}-${to}`}
                markerEnd="url(#arch-flow-arrow)"
              />
              <path className="arch-edge-flow" d={d} aria-hidden="true" />
            </g>
          )
        })}

        {/* Box nodes. HTML inside foreignObject gives wrapped, glass-styled text
            in the live deck; all dynamic text is escaped React text content. */}
        {BOX_KINDS.map((kind) => {
          const box = nodeBox(kind)
          const layer = byKind.get(kind) ?? layerForKind(all, kind)
          const index = seqIndex(kind)
          const active = isActiveKind(kind)
          return (
            <foreignObject
              key={kind}
              x={box.x}
              y={box.y}
              width={box.w}
              height={box.h}
              className={`arch-node-fo${active ? "" : " pending"}`}
              style={
                {
                  "--reveal-index": index,
                  "--node-accent": accentFor(index),
                  "--node-accent-2": accentFor(index + 1),
                } as CSSProperties
              }
            >
              <div className="arch-node" data-arch-node={kind}>
                <span className="arch-node__kind">{kind}</span>
                <strong className="arch-node__label">{layer.label}</strong>
              </div>
            </foreignObject>
          )
        })}

        {/* Unknown/`group` kinds: unconnected annotations, far-left bottom. */}
        {extras.map((layer, index) => (
          <foreignObject
            key={layer.id}
            x={24}
            y={444 + index * 52}
            width={184}
            height={44}
            className="arch-node-fo arch-node-fo--extra"
          >
            <div className="arch-node arch-node--extra" data-arch-node={layer.kind}>
              <span className="arch-node__kind">{layer.kind}</span>
              <strong className="arch-node__label">{layer.label}</strong>
            </div>
          </foreignObject>
        ))}
      </svg>

      <ol
        className="architecture-reveal-fallback sr-only"
        aria-label="Architecture reveal ordered fallback summary"
      >
        {ordered.map((layer, index) => (
          <li key={layer.id} data-layer-kind={layer.kind}>
            <strong>
              {index + 1}. {layer.label}
            </strong>
            <span>{layerSummary(layer)}</span>
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
