import type { CSSProperties } from "react"
import type {
  StoryboardDiagram,
  StoryboardDiagramLayer,
  StoryboardLayerKind,
} from "../../types/storyboard"

// The eight fixed architecture planes, in canonical reveal order. This is a
// closed enum owned by trusted code; the LLM only ever fills a layer's
// label/summary/source_refs, never the topology. storyboard-v1.5: a diagram no
// longer has to carry all eight — only the three core planes (client/api/data)
// are required — so the renderer lays out only the planes that are present.
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
// Topology geometry (trusted code only — no LLM input reaches geometry).
//
// storyboard-v1.5: the diagram lays out only the planes the product actually
// has. The three core planes are always present (client → api → one-or-more
// sinks); optional planes (frontend; the extra sinks llm/integrations; and the
// trust/recovery overlay regions) render only when supplied. Geometry is a pure
// function of the present set, driven by small constant tables so it stays
// deterministic and the Python offline renderer (storyboard_renderer.py) can
// mirror it exactly. When all eight planes are present it reduces to the original
// fixed topology (locked by the parity test), so every legacy deck renders
// byte-identically.
//
//   client ─▶ [frontend] ─▶ api ─┬─▶ data
//                                ├─▶ [llm]
//                                └─▶ [integrations]
//   trust:    boundary overlay over present {frontend·api·data·llm}
//   recovery: backplane under present {api·data·llm·integrations}
// ---------------------------------------------------------------------------

const VIEW_W = 960
const VIEW_H = 600
const NODE_W = 168
const NODE_H = 88

// The six connectable box nodes. `trust` and `recovery` are overlay regions
// derived from these, not boxes.
const BOX_KINDS = [
  "client",
  "frontend",
  "api",
  "data",
  "llm",
  "integrations",
] as const satisfies readonly ArchitectureKind[]

type BoxKind = (typeof BOX_KINDS)[number]

// The horizontal chain client → [frontend] → api. Column x-positions depend only
// on whether the frontend plane is present; every chain node sits on the centre.
const CHAIN_Y = 300
const CHAIN_X_WITH_FRONTEND: Record<string, number> = {
  client: 104,
  frontend: 330,
  api: 556,
}
const CHAIN_X_WITHOUT_FRONTEND: Record<string, number> = { client: 104, api: 430 }

// Sinks hang off api in canonical order on a fixed column; their y-positions
// depend only on how many sinks are present, so the fan stays vertically centred.
const SINK_X = 834
const SINK_KINDS = ["data", "llm", "integrations"] as const
const SINK_Y_BY_COUNT: Record<number, readonly number[]> = {
  0: [],
  1: [300],
  2: [180, 420],
  3: [118, 300, 482],
}

// A region bounds only its present members and renders only when its own kind is
// present and at least two members remain (a boundary around < 2 boxes is noise).
const TRUST_MEMBERS: readonly BoxKind[] = ["frontend", "api", "data", "llm"]
const RECOVERY_MEMBERS: readonly BoxKind[] = ["api", "data", "llm", "integrations"]
const TRUST_PAD = 24
const RECOVERY_PAD = 38

interface Point {
  x: number
  y: number
}

interface Box {
  kind: BoxKind
  x: number
  y: number
  w: number
  h: number
  cx: number
  cy: number
}

interface Region {
  x: number
  y: number
  w: number
  h: number
}

interface Topology {
  centers: Map<BoxKind, Point>
  boxes: Box[]
  edges: [BoxKind, BoxKind][]
  trust: Region | null
  recovery: Region | null
}

function boxFromCenter(kind: BoxKind, c: Point): Box {
  return {
    kind,
    x: c.x - NODE_W / 2,
    y: c.y - NODE_H / 2,
    w: NODE_W,
    h: NODE_H,
    cx: c.x,
    cy: c.y,
  }
}

function regionFor(
  members: readonly BoxKind[],
  centers: Map<BoxKind, Point>,
  pad: number,
): Region | null {
  const boxes = members
    .filter((kind) => centers.has(kind))
    .map((kind) => boxFromCenter(kind, centers.get(kind)!))
  if (boxes.length < 2) return null
  const minX = Math.min(...boxes.map((b) => b.x)) - pad
  const minY = Math.min(...boxes.map((b) => b.y)) - pad
  const maxX = Math.max(...boxes.map((b) => b.x + b.w)) + pad
  const maxY = Math.max(...boxes.map((b) => b.y + b.h)) + pad
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

// Pure, deterministic topology for the set of present planes. Exported for the
// parity test that locks the all-eight case to the original fixed coordinates.
export function architectureTopology(present: ReadonlySet<string>): Topology {
  const hasFrontend = present.has("frontend")
  const chainX = hasFrontend ? CHAIN_X_WITH_FRONTEND : CHAIN_X_WITHOUT_FRONTEND
  const centers = new Map<BoxKind, Point>()
  for (const kind of ["client", "frontend", "api"] as const) {
    if (present.has(kind) && chainX[kind] !== undefined) {
      centers.set(kind, { x: chainX[kind], y: CHAIN_Y })
    }
  }
  const presentSinks = SINK_KINDS.filter((kind) => present.has(kind))
  const ys = SINK_Y_BY_COUNT[presentSinks.length] ?? []
  presentSinks.forEach((kind, index) => {
    centers.set(kind, { x: SINK_X, y: ys[index] ?? CHAIN_Y })
  })

  const boxes = BOX_KINDS.filter((kind) => centers.has(kind)).map((kind) =>
    boxFromCenter(kind, centers.get(kind)!),
  )

  const edges: [BoxKind, BoxKind][] = []
  if (hasFrontend) {
    if (centers.has("client") && centers.has("frontend")) {
      edges.push(["client", "frontend"])
    }
    if (centers.has("frontend") && centers.has("api")) {
      edges.push(["frontend", "api"])
    }
  } else if (centers.has("client") && centers.has("api")) {
    edges.push(["client", "api"])
  }
  if (centers.has("api")) {
    for (const sink of presentSinks) edges.push(["api", sink])
  }

  const trust = present.has("trust")
    ? regionFor(TRUST_MEMBERS, centers, TRUST_PAD)
    : null
  const recovery = present.has("recovery")
    ? regionFor(RECOVERY_MEMBERS, centers, RECOVERY_PAD)
    : null

  return { centers, boxes, edges, trust, recovery }
}

// Smooth left-to-right connector from one node's right edge to the next node's
// left edge. Control points are pulled horizontally so vertical fan-outs
// (api → data/integrations) curve gracefully instead of kinking.
function edgePath(from: Point, to: Point): string {
  const sx = from.x + NODE_W / 2
  const sy = from.y
  const ex = to.x - NODE_W / 2
  const ey = to.y
  const dx = Math.max((ex - sx) * 0.5, 36)
  return `M ${sx} ${sy} C ${sx + dx} ${sy}, ${ex - dx} ${ey}, ${ex} ${ey}`
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

// The present canonical planes, in canonical reveal order. Unknown / `group`
// kinds are handled separately as unconnected annotations; absent planes are
// simply omitted (storyboard-v1.5 — no "this layer was not described" filler).
export function orderArchitectureLayers(
  layers: StoryboardDiagramLayer[],
): StoryboardDiagramLayer[] {
  const byKind = new Map(layers.map((layer) => [layer.kind, layer]))
  return ARCHITECTURE_LAYER_SEQUENCE.filter((kind) => byKind.has(kind)).map(
    (kind) => byKind.get(kind)!,
  )
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
  const present = new Set<string>(ordered.map((layer) => layer.kind))
  const topology = architectureTopology(present)

  // Reveal order is the position within the *present* planes, not the fixed
  // 0..7 canonical index — otherwise a core-only subset (client=0, api=2,
  // data=3) would treat `data` as beyond a visibleCount of 3 and dim it.
  const revealIndexByKind = new Map<string, number>(
    ordered.map((layer, index) => [layer.kind, index]),
  )
  const revealIndexOf = (kind: string) => revealIndexByKind.get(kind) ?? 0
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

  const isActiveKind = (kind: string) => revealIndexOf(kind) < visibleCount

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

        {/* Recovery backplane (lowest layer) — only when the plane is present. */}
        {topology.recovery && (
          <g
            className={`arch-region arch-region--recovery${
              isActiveKind("recovery") ? "" : " pending"
            }`}
            style={{ "--reveal-index": revealIndexOf("recovery") } as CSSProperties}
          >
            <rect
              className="arch-region__rect arch-region__rect--recovery"
              x={topology.recovery.x}
              y={topology.recovery.y}
              width={topology.recovery.w}
              height={topology.recovery.h}
              rx={22}
            />
            <text
              className="arch-region__label arch-region__label--recovery"
              x={topology.recovery.x + 16}
              y={topology.recovery.y + topology.recovery.h - 14}
            >
              {recoveryLayer?.label || LAYER_COPY.recovery}
            </text>
          </g>
        )}

        {/* Trust boundary (dashed outline) — only when the plane is present. */}
        {topology.trust && (
          <g
            className={`arch-region arch-region--trust${
              isActiveKind("trust") ? "" : " pending"
            }`}
            style={{ "--reveal-index": revealIndexOf("trust") } as CSSProperties}
          >
            <rect
              className="arch-region__rect arch-region__rect--trust"
              x={topology.trust.x}
              y={topology.trust.y}
              width={topology.trust.w}
              height={topology.trust.h}
              rx={20}
            />
            <text
              className="arch-region__label arch-region__label--trust"
              x={topology.trust.x + 16}
              y={topology.trust.y + 22}
            >
              {trustLayer?.label || LAYER_COPY.trust}
            </text>
          </g>
        )}

        {/* Edges: a solid connector (the static base) plus a flowing dash on top
            (the animated data flow, disabled under reduced motion). */}
        {topology.edges.map(([from, to]) => {
          const d = edgePath(topology.centers.get(from)!, topology.centers.get(to)!)
          const active = isActiveKind(from) && isActiveKind(to)
          const revealIndex = Math.max(revealIndexOf(from), revealIndexOf(to))
          return (
            <g
              key={`${from}-${to}`}
              className={`arch-edge-group${active ? "" : " pending"}`}
              style={
                {
                  "--reveal-index": revealIndex,
                  "--edge-accent": accentFor(revealIndexOf(to)),
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
        {topology.boxes.map((box) => {
          const layer = byKind.get(box.kind)!
          const index = revealIndexOf(box.kind)
          const active = isActiveKind(box.kind)
          return (
            <foreignObject
              key={box.kind}
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
              <div className="arch-node" data-arch-node={box.kind}>
                <span className="arch-node__kind">{box.kind}</span>
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
