// Storyboard types (Phase 20 — T-257).
//
// These mirror the backend Pydantic schemas (backend/schemas/storyboard.py),
// the generated payload contract (backend/prompts/storyboard.py), and the
// harness schemas (harness/schemas/storyboard-payload.schema.json and
// storyboard-public-response.schema.json). Keep them in lockstep: the public
// surface is allow-list based on the backend, and adding a field to a public
// type here is a privacy decision there.

// Lifecycle of a generated Storyboard version. `generating` is the in-flight
// placeholder, `ready` is presentable, `failed` is a refunded dead version,
// and `stale` marks a once-ready version whose source stages were refinalised.
export type StoryboardStatus = "generating" | "ready" | "failed" | "stale"

// The four finalised pipeline artifacts every claim and component maps back to.
export type StoryboardSource = "SPEC" | "PLAN" | "HARNESS" | "TASKS"

// The six fixed, ordered top-level acts of the keynote. Validation and Execution
// Plan are intentionally NOT acts.
export type StoryboardSectionTitle =
  | "Opening Thesis"
  | "Product Vision"
  | "Product Walkthrough"
  | "Technical Architecture"
  | "Trust, Security, Reliability"
  | "Launch Close"

// Slide layout kinds the trusted renderer understands.
export type StoryboardSlideType =
  | "hero"
  | "thesis"
  | "product"
  | "walkthrough"
  | "architecture"
  | "trust"
  | "closing"
  | "appendix_pointer"

// Architecture-reveal planes. Every architecture_reveal diagram layers all eight
// (client through recovery); `group` is an optional structural grouping layer.
export type StoryboardLayerKind =
  | "client"
  | "frontend"
  | "api"
  | "data"
  | "llm"
  | "integrations"
  | "trust"
  | "recovery"
  | "group"

// Owner download artifacts. `html` and `pdf` are rendered packages; the rest are
// markdown documents. The HTML package is owner-only and never offered publicly.
export type StoryboardDownloadKind =
  | "html"
  | "pdf"
  | "notes"
  | "demo-script"
  | "appendix"

// Public downloads are a strict subset of owner downloads — no offline HTML
// package — and each is gated behind the matching `allow_*` permission.
export type StoryboardPublicDownloadKind = "pdf" | "notes" | "demo-script" | "appendix"

// Speaker notes can be downloaded as raw markdown or a rendered PDF.
export type StoryboardNotesFormat = "md" | "pdf"

// ---------------------------------------------------------------------------
// Leaf payload models
// ---------------------------------------------------------------------------

// A bounded citation back to a finalised SPEC / PLAN / HARNESS / TASKS source.
export interface SourceRef {
  source: StoryboardSource
  source_id: string
  excerpt: string
}

// Per-slide presenter guidance. The deck stays sparse; depth lives here.
export interface SpeakerNote {
  slide_id: string
  talk_track: string
  transition: string
  timing_seconds: number
  pause_cue: string
  demo_cue: string
  backup_points: string[]
}

// Structured visual descriptor for a slide. `kind` names an inert layout; extra
// descriptor keys are pure data the renderer escapes and never executes.
export interface StoryboardVisual {
  kind: string
  [key: string]: unknown
}

export interface StoryboardSlide {
  id: string
  type: StoryboardSlideType
  headline: string
  visible_text: string
  visual: StoryboardVisual
  speaker_notes_ref: string
  sources: StoryboardSource[]
}

export interface StoryboardSection {
  id: string
  title: StoryboardSectionTitle
  slides: StoryboardSlide[]
}

export interface StoryboardDiagramLayer {
  id: string
  kind: StoryboardLayerKind
  label: string
  summary: string
  source_refs: SourceRef[]
}

export interface StoryboardDiagram {
  id: string
  type: string
  layers: StoryboardDiagramLayer[]
}

// Visual identity: palette (hex), typography mood, motif, transitions, diagrams.
export interface StoryboardTheme {
  palette: string[]
  typography: string
  motif: string
  transition_style: string
  diagram_style: string
}

// The complete structured keynote payload the LLM produces and the renderers
// consume. `source_map` and the diagram `source_refs` carry bounded excerpts;
// `notes` is keyed by slide id.
export interface StoryboardPayload {
  title: string
  theme: StoryboardTheme
  sections: StoryboardSection[]
  diagrams: StoryboardDiagram[]
  source_map: Record<string, SourceRef[]>
  notes: Record<string, SpeakerNote>
  demo_script_md: string
  technical_appendix_md: string
}

// ---------------------------------------------------------------------------
// Public-share permissions (the four independent owner toggles)
// ---------------------------------------------------------------------------

export interface StoryboardSharePermissions {
  allow_pdf_download: boolean
  allow_notes_download: boolean
  allow_appendix_download: boolean
  allow_source_layer: boolean
}

// ---------------------------------------------------------------------------
// Owner responses
// ---------------------------------------------------------------------------

// Lightweight owner list item. `theme` here is the display label (motif), not
// the structured StoryboardTheme object that lives inside the payload.
export interface StoryboardSummary {
  id: string
  workspace_id: string
  version: number
  status: StoryboardStatus
  title: string
  theme: string
  public_share_enabled: boolean
  public_share_slug: string | null
  created_at: string
  updated_at: string
}

// Full owner view of one Storyboard version. `content` is the validated payload
// (its `demo_script_md` / `technical_appendix_md` live there, not at top level).
// The rendered `speaker_notes_md` and the immutable `source_stage_version_ids`
// source pin are owner-only and fetched on demand (presenter / download
// endpoints) rather than always inlined, so they are optional here.
// `source_stage_version_ids` is never exposed on the public surface.
export interface StoryboardDetail {
  id: string
  workspace_id: string
  version: number
  status: StoryboardStatus
  title: string
  theme: string
  content: StoryboardPayload
  source_map: Record<string, SourceRef[]>
  permissions: StoryboardSharePermissions
  public_share_enabled: boolean
  public_share_slug: string | null
  created_at: string
  updated_at: string
  source_stage_version_ids?: Record<string, string>
  speaker_notes_md?: string
}

// Owner presenter-mode view: the deck payload plus the per-slide speaker notes
// map and the demo script, so presenter mode does not depend on the rendered
// markdown artifact.
export interface StoryboardPresenterResponse {
  id: string
  title: string
  status: StoryboardStatus
  theme: string
  content: StoryboardPayload
  notes: Record<string, SpeakerNote>
  demo_script_md: string
}

// ---------------------------------------------------------------------------
// Share requests / responses
// ---------------------------------------------------------------------------

// Enable sharing and/or update permissions. Each field is optional: omitting it
// leaves the current value unchanged (or the default on first enable). The slug
// is server-generated and never client-supplied.
export interface StoryboardShareRequest {
  allow_pdf_download?: boolean
  allow_notes_download?: boolean
  allow_appendix_download?: boolean
  allow_source_layer?: boolean
}

export interface StoryboardShareResponse {
  slug: string
  url: string
  enabled: boolean
  permissions: StoryboardSharePermissions
}

// ---------------------------------------------------------------------------
// Public (unauthenticated, allow-list) response
// ---------------------------------------------------------------------------

// The allow-list contract for GET /storyboards/public/{slug}. It carries the
// permission-filtered presentation payload (private notes / appendix / source
// excerpts are redacted unless their permission is on) and never exposes
// user_id, workspace_id, credit data, billing data, source_stage_version_ids,
// draft/previous/failed versions, or account email.
export interface StoryboardPublicResponse {
  title: string
  presentation: StoryboardPayload
  permissions: StoryboardSharePermissions
  downloads: StoryboardPublicDownloadKind[]
  shared_at: string
}

// A safe not-found sentinel for the public route: an unknown, disabled, or
// rotated slug resolves to null rather than throwing, so the public page can
// render an empty state without an auth redirect or crash.
export type PublicStoryboardLookup = StoryboardPublicResponse | null
