import type {
  SourceRef,
  StoryboardDiagramLayer,
  StoryboardLayerKind,
  StoryboardPayload,
  StoryboardPublicResponse,
  StoryboardSectionTitle,
  StoryboardSharePermissions,
} from "../../types/storyboard"

export const STORYBOARD_TEST_ACTS: StoryboardSectionTitle[] = [
  "Opening Thesis",
  "Product Vision",
  "Product Walkthrough",
  "Technical Architecture",
  "Trust, Security, Reliability",
  "Launch Close",
]

export const DEFAULT_TEST_PERMISSIONS: StoryboardSharePermissions = {
  allow_pdf_download: true,
  allow_notes_download: false,
  allow_appendix_download: false,
  allow_source_layer: false,
}

export function slideId(title: StoryboardSectionTitle): string {
  return title.toLowerCase().replace(/[^a-z0-9]+/g, "-")
}

function source(source: SourceRef["source"], excerpt = `${source} excerpt`): SourceRef {
  return {
    source,
    source_id: `${source}:source`,
    excerpt,
  }
}

function layer(kind: StoryboardLayerKind): StoryboardDiagramLayer {
  return {
    id: `${kind}-layer`,
    kind,
    label: `${kind} label`,
    summary: `${kind} summary`,
    source_refs: [source("PLAN", `${kind} architecture excerpt`)],
  }
}

export function makeStoryboardPayload(
  overrides: Partial<StoryboardPayload> = {},
): StoryboardPayload {
  const payload: StoryboardPayload = {
    title: "SpecForge Launch",
    theme: {
      palette: ["#8f4e00", "#a1385f", "#565e74"],
      typography: "Confident product sans",
      motif: "Copper circuit cards",
      transition_style: "Measured reveal",
      diagram_style: "Layered architecture cards",
    },
    sections: STORYBOARD_TEST_ACTS.map((title) => {
      const id = slideId(title)
      return {
        id,
        title,
        slides: [
          {
            id: `${id}-slide`,
            type: title === "Technical Architecture" ? "architecture" : "hero",
            headline: `${title} headline`,
            visible_text: `${title} visible text`,
            visual: { kind: `${id}-visual` },
            speaker_notes_ref: `${id}-slide`,
            sources: ["SPEC", "PLAN"],
          },
        ],
      }
    }),
    diagrams: [
      {
        id: "architecture-reveal",
        type: "architecture_reveal",
        layers: [
          layer("client"),
          layer("frontend"),
          layer("api"),
          layer("data"),
          layer("llm"),
          layer("integrations"),
          layer("trust"),
          layer("recovery"),
        ],
      },
    ],
    source_map: {
      "opening-thesis-slide.claim": [
        source("SPEC", "A".repeat(1500)),
        source("PLAN", "Plan excerpt"),
        source("HARNESS", "Harness excerpt"),
        source("TASKS", "Tasks excerpt"),
      ],
      "product-vision-slide.claim": [source("SPEC", "Vision excerpt")],
    },
    notes: Object.fromEntries(
      STORYBOARD_TEST_ACTS.map((title) => {
        const id = `${slideId(title)}-slide`
        return [
          id,
          {
            slide_id: id,
            talk_track: `${title} talk track`,
            transition: `${title} transition`,
            timing_seconds: 45,
            pause_cue: `${title} pause cue`,
            demo_cue: `${title} walkthrough cue`,
            backup_points: [`${title} backup point`],
          },
        ]
      }),
    ),
    demo_script_md: "Walkthrough script",
    technical_appendix_md: "Technical appendix",
  }

  return { ...payload, ...overrides }
}

// ---------------------------------------------------------------------------
// Max-cap fixture (Storyboard output-quality plan P1.4) — a deck at the
// generation-schema maxima from backend/prompts/storyboard.py. This is the
// regression anchor for every future layout change: if it renders un-clipped,
// every real deck does.
// ---------------------------------------------------------------------------

// 18 words / 140 characters — both headline maxima (15×7 + 3×6 chars + 17 spaces).
export const MAX_CAP_HEADLINE = [
  ...Array<string>(15).fill("maximal"),
  ...Array<string>(3).fill("stress"),
].join(" ")

// 45 words / 359 characters (≤ the 360-char cap): 45×7 chars + 44 spaces.
export const MAX_CAP_VISIBLE_TEXT = Array<string>(45).fill("connect").join(" ")

// Five points of eight words each — the visual-descriptor stress shape.
export const MAX_CAP_POINTS = Array.from({ length: 5 }, (_, index) =>
  Array<string>(8).fill(`signal${index}`).join(" "),
)

// 120 characters — the diagram-layer label maximum.
export const MAX_CAP_LAYER_LABEL = Array<string>(15).fill("maximal").join(" ")

function maxCapLayer(kind: StoryboardLayerKind): StoryboardDiagramLayer {
  return {
    id: `${kind}-layer`,
    kind,
    label: MAX_CAP_LAYER_LABEL,
    summary: `${kind} summary`,
    source_refs: [source("PLAN", `${kind} architecture excerpt`)],
  }
}

export function makeMaxCapStoryboardPayload(): StoryboardPayload {
  const sections = STORYBOARD_TEST_ACTS.map((title) => {
    const id = slideId(title)
    const isArchitecture = title === "Technical Architecture"
    return {
      id,
      title,
      slides: [
        {
          id: `${id}-slide-a`,
          type: isArchitecture ? ("architecture" as const) : ("hero" as const),
          headline: MAX_CAP_HEADLINE,
          visible_text: MAX_CAP_VISIBLE_TEXT,
          visual: { kind: "bullets", points: MAX_CAP_POINTS },
          speaker_notes_ref: `${id}-slide-a`,
          sources: ["SPEC", "PLAN", "HARNESS", "TASKS"] as SourceRef["source"][],
        },
        {
          id: `${id}-slide-b`,
          type: "product" as const,
          headline: MAX_CAP_HEADLINE,
          visible_text: MAX_CAP_VISIBLE_TEXT,
          visual: { kind: "metric", value: "99.999%", label: MAX_CAP_POINTS[0] },
          speaker_notes_ref: `${id}-slide-b`,
          sources: ["SPEC", "PLAN"] as SourceRef["source"][],
        },
      ],
    }
  })
  return makeStoryboardPayload({
    title: MAX_CAP_HEADLINE,
    sections,
    diagrams: [
      {
        id: "architecture-reveal",
        type: "architecture_reveal",
        layers: (
          [
            "client",
            "frontend",
            "api",
            "data",
            "llm",
            "integrations",
            "trust",
            "recovery",
          ] as StoryboardLayerKind[]
        ).map(maxCapLayer),
      },
    ],
  })
}

export function makePublicStoryboard(
  overrides: Partial<StoryboardPublicResponse> = {},
): StoryboardPublicResponse {
  return {
    title: "SpecForge Launch",
    presentation: makeStoryboardPayload(),
    permissions: DEFAULT_TEST_PERMISSIONS,
    downloads: ["pdf"],
    shared_at: "2026-05-30T00:00:00Z",
    ...overrides,
  }
}
